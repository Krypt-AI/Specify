"""Analytics from the user's actual data. Nothing here is estimated or invented."""
from collections import Counter
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (
    DraftStatus,
    EmailDraft,
    EmailMessage,
    EmailMessageGroup,
    FollowUpStatus,
    FollowUpTask,
    MailGroup,
    Opportunity,
    OpportunityDecision,
    RunStatus,
    User,
    WorkflowRun,
)
from app.schemas.preferences import UserPreferences

router = APIRouter(prefix="/analytics", tags=["analytics"])


class WeekActivity(BaseModel):
    week_start: date
    recruitment_emails: int
    opportunities_created: int
    decisions: int


class Analytics(BaseModel):
    days: int
    emails_by_group: dict[str, int]
    opportunities_by_status: dict[str, int]
    decisions_by_outcome: dict[str, int]
    activity_by_week: list[WeekActivity]
    follow_ups: dict[str, int]
    workflow_runs: dict[str, int]


class Summary(BaseModel):
    follow_ups_due: int
    follow_ups_overdue: int
    drafts_ready: int
    workflows_failed: int
    workflows_waiting: int


@router.get("", response_model=Analytics)
def analytics(days: int = Query(90, ge=7, le=365), user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Analytics:
    since = utcnow() - timedelta(days=days)
    zone = ZoneInfo(UserPreferences.of(user.preferences).timezone or "UTC")

    emails_by_group = dict(
        db.execute(
            select(EmailMessageGroup.group_name, func.count())
            .join(EmailMessage, EmailMessage.id == EmailMessageGroup.email_message_id)
            .where(EmailMessage.user_id == user.id, EmailMessageGroup.is_primary.is_(True), EmailMessage.received_at >= since)
            .group_by(EmailMessageGroup.group_name)
        ).all()
    )
    opportunities_by_status = dict(
        db.execute(select(Opportunity.status, func.count()).where(Opportunity.user_id == user.id).group_by(Opportunity.status)).all()
    )
    decisions = db.execute(
        select(OpportunityDecision.decision, OpportunityDecision.created_at).where(
            OpportunityDecision.user_id == user.id, OpportunityDecision.created_at >= since
        )
    ).all()
    recruitment_dates = db.scalars(
        select(EmailMessage.received_at).where(
            EmailMessage.user_id == user.id,
            EmailMessage.received_at >= since,
            EmailMessage.groups.any((EmailMessageGroup.group_name == MailGroup.RECRUITMENT) & EmailMessageGroup.is_primary.is_(True)),
        )
    ).all()
    created_dates = db.scalars(select(Opportunity.created_at).where(Opportunity.user_id == user.id, Opportunity.created_at >= since)).all()

    def week(moment) -> date:
        day = moment.astimezone(zone).date()
        return day - timedelta(days=day.weekday())

    weeks = Counter(), Counter(), Counter()
    for moment in recruitment_dates:
        weeks[0][week(moment)] += 1
    for moment in created_dates:
        weeks[1][week(moment)] += 1
    for _, moment in decisions:
        weeks[2][week(moment)] += 1
    first, last = week(since), week(utcnow())
    activity = []
    current = first
    while current <= last:
        activity.append(WeekActivity(week_start=current, recruitment_emails=weeks[0][current], opportunities_created=weeks[1][current], decisions=weeks[2][current]))
        current += timedelta(days=7)

    now = utcnow()
    tasks = db.execute(
        select(FollowUpTask.status, FollowUpTask.due_at).where(FollowUpTask.user_id == user.id, FollowUpTask.status != FollowUpStatus.CANCELLED)
    ).all()
    runs = dict(
        db.execute(
            select(WorkflowRun.status, func.count())
            .where(WorkflowRun.user_id == user.id, WorkflowRun.is_test.is_(False), WorkflowRun.created_at >= since)
            .group_by(WorkflowRun.status)
        ).all()
    )
    return Analytics(
        days=days,
        emails_by_group={group.value: emails_by_group.get(group.value, 0) for group in MailGroup},
        opportunities_by_status=opportunities_by_status,
        decisions_by_outcome=dict(Counter(decision for decision, _ in decisions)),
        activity_by_week=activity,
        follow_ups={
            "completed": sum(1 for status, _ in tasks if status == FollowUpStatus.DONE),
            "open": sum(1 for status, due in tasks if status == FollowUpStatus.OPEN and due >= now),
            "overdue": sum(1 for status, due in tasks if status == FollowUpStatus.OPEN and due < now),
        },
        workflow_runs=runs,
    )


@router.get("/summary", response_model=Summary)
def summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Summary:
    now = utcnow()
    open_tasks = select(func.count()).select_from(FollowUpTask).where(FollowUpTask.user_id == user.id, FollowUpTask.status == FollowUpStatus.OPEN)
    return Summary(
        follow_ups_due=db.scalar(open_tasks.where(FollowUpTask.due_at <= now + timedelta(days=1))),
        follow_ups_overdue=db.scalar(open_tasks.where(FollowUpTask.due_at < now)),
        drafts_ready=db.scalar(
            select(func.count()).select_from(EmailDraft).where(
                EmailDraft.user_id == user.id, EmailDraft.status == DraftStatus.READY, EmailDraft.gmail_draft_id.is_not(None)
            )
        ),
        workflows_failed=_run_count(db, user, RunStatus.FAILED),
        workflows_waiting=_run_count(db, user, RunStatus.WAITING),
    )


def _run_count(db: Session, user: User, status: RunStatus) -> int:
    return db.scalar(
        select(func.count())
        .select_from(WorkflowRun)
        .where(WorkflowRun.user_id == user.id, WorkflowRun.is_test.is_(False), WorkflowRun.status == status)
    )
