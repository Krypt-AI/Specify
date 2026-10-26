"""Follow-up reminders and notifications, created only by the user's reminder rules."""
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import (
    Decision,
    EmailMessage,
    FollowUpStatus,
    FollowUpTask,
    Notification,
    Opportunity,
    OpportunityDecision,
    User,
)
from app.schemas.preferences import UserPreferences

# kind → (rule switch, days-before setting, title prefix)
DATE_RULES = {
    "deadline": ("deadlines", "deadline_days_before", "Deadline"),
    "payment": ("deadlines", "deadline_days_before", "Payment due"),
    "exam": ("exams", "exam_days_before", "Exam"),
    "interview": ("interviews", "interview_days_before", "Interview"),
    "renewal": ("renewals", "renewal_days_before", "Renewal"),
}
RECRUITER_WAITING = {
    Decision.INTERESTED, Decision.INTERESTED_NEED_INFO, Decision.REQUEST_SALARY,
    Decision.REQUEST_JOB_DESCRIPTION, Decision.REQUEST_INTERVIEW_DETAILS,
}


def reminders_from_email(db: Session, email: EmailMessage, prefs: UserPreferences) -> dict:
    """Create reminders for the email's unambiguous dates; flag ambiguous ones for checking."""
    rules = prefs.reminders
    zone = ZoneInfo(prefs.timezone or "UTC")
    created, ambiguous = 0, []
    for found in email.extracted_data.get("dates", []):
        if found.get("ambiguous") or not found.get("date"):
            ambiguous.append(found["text"])
            continue
        rule = DATE_RULES.get(found["kind"])
        if rule is None or not getattr(rules, rule[0]):
            continue
        day = datetime.fromisoformat(found["date"]).date() - timedelta(days=getattr(rules, rule[1]))
        due = datetime.combine(day, time(9), zone)
        if due < utcnow() - timedelta(days=1):
            continue  # already past
        created += _insert_once(
            db,
            FollowUpTask(
                user_id=email.user_id, email_message_id=email.id, opportunity_id=email.opportunity_id,
                kind=found["kind"], title=f"{rule[2]}: {email.subject or found['text']}"[:300],
                notes=f"From the email: “{found['text']}”", due_at=due, source="email",
                idempotency_key=f"email:{email.id}:{found['kind']}:{found['date']}",
            ),
        )
    if rules.reply_needed and email.reply_required:
        created += _insert_once(
            db,
            FollowUpTask(
                user_id=email.user_id, email_message_id=email.id, opportunity_id=email.opportunity_id, kind="reply",
                title=f"Reply to {email.sender_name or email.sender_email}: {email.subject}"[:300],
                due_at=utcnow() + timedelta(days=2), source="email", idempotency_key=f"email:{email.id}:reply",
            ),
        )
    if ambiguous:
        notify(
            db, email.user_id, "date_check", f"Check a date in “{email.subject}”"[:200],
            "Specify could not read this date with certainty: " + "; ".join(ambiguous), f"/inbox?email={email.id}",
            key=f"email:{email.id}:ambiguous",
        )
    return {"created": created, "ambiguous": ambiguous}


def follow_ups_for_decision(db: Session, user: User, opportunity: Opportunity, decision: OpportunityDecision) -> None:
    """Deferred decisions come back as reminders; replies the user awaits get a recruiter follow-up."""
    rules = UserPreferences.of(user.preferences).reminders
    if decision.decision in (Decision.SAVE_FOR_LATER, Decision.REQUEST_MORE_TIME) and opportunity.next_follow_up_at:
        task = FollowUpTask(
            user_id=user.id, opportunity_id=opportunity.id, kind="decision", title=f"Decide on {opportunity.job_title}"[:300],
            due_at=opportunity.next_follow_up_at, source="decision", idempotency_key=f"decision:{decision.id}",
        )
    elif decision.decision in RECRUITER_WAITING and rules.recruiter_follow_up_days:
        who = (opportunity.recruiter.name or opportunity.recruiter.email) if opportunity.recruiter else opportunity.company_name
        task = FollowUpTask(
            user_id=user.id, opportunity_id=opportunity.id, kind="recruiter",
            title=f"Follow up with {who or 'the recruiter'} about {opportunity.job_title}"[:300],
            notes="Closes on its own when they reply.",
            due_at=utcnow() + timedelta(days=rules.recruiter_follow_up_days), source="decision",
            idempotency_key=f"decision:{decision.id}",
        )
    else:
        return
    _insert_once(db, task, commit=False)


def close_recruiter_follow_ups(db: Session, opportunity_id: uuid.UUID) -> None:
    """A reply from the recruiter completes the follow-up waiting for it."""
    db.execute(
        update(FollowUpTask)
        .where(
            FollowUpTask.opportunity_id == opportunity_id,
            FollowUpTask.kind == "recruiter",
            FollowUpTask.status == FollowUpStatus.OPEN,
        )
        .values(status=FollowUpStatus.DONE, completed_at=utcnow())
        .execution_options(synchronize_session=False)
    )


def notify_due_reminders(db: Session) -> int:
    """Turn reminders that have come due into notifications, once each."""
    now = utcnow()
    due = db.scalars(
        select(FollowUpTask).where(
            FollowUpTask.status == FollowUpStatus.OPEN,
            FollowUpTask.due_at <= now,
            FollowUpTask.notified_at.is_(None),
            or_(FollowUpTask.snoozed_until.is_(None), FollowUpTask.snoozed_until <= now),
        ).limit(500)
    ).all()
    for task in due:
        notify(
            db, task.user_id, "reminder", f"Reminder: {task.title}"[:200], task.notes, "/follow-ups",
            key=f"reminder:{task.id}:{task.due_at.isoformat()}", commit=False,
        )
        task.notified_at = now
    db.commit()
    return len(due)


def notify(
    db: Session, user_id: uuid.UUID, kind: str, title: str, body: str = "", link: str | None = None,
    *, key: str | None = None, commit: bool = True,
) -> bool:
    """Create an in-app notification; a repeated key is ignored."""
    if key and db.scalar(select(Notification.id).where(Notification.user_id == user_id, Notification.idempotency_key == key)):
        return False
    db.add(Notification(user_id=user_id, kind=kind, title=title, body=body, link=link, idempotency_key=key))
    if commit:
        db.commit()
    return True


def _insert_once(db: Session, record, commit: bool = True) -> int:
    existing = db.scalar(
        select(type(record).id).where(type(record).user_id == record.user_id, type(record).idempotency_key == record.idempotency_key)
    )
    if existing:
        return 0
    db.add(record)
    if commit:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return 0
    return 1
