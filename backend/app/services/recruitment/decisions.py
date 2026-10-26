"""The user's decisions and status changes. Consequential changes need explicit confirmation."""
import uuid
from datetime import timedelta

from sqlalchemy import ColumnElement, and_, or_
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import Decision, Opportunity, OpportunityDecision, OpportunityStatus, User
from app.services.audit import record_audit
from app.services.reminders import follow_ups_for_decision


class ConfirmationRequired(Exception):
    """The change is consequential; repeat the request with confirmation."""


DECISION_STATUS: dict[Decision, OpportunityStatus | None] = {
    Decision.INTERESTED: OpportunityStatus.INTERESTED,
    Decision.INTERESTED_NEED_INFO: OpportunityStatus.MORE_INFO_REQUIRED,
    Decision.REQUEST_SALARY: OpportunityStatus.MORE_INFO_REQUIRED,
    Decision.REQUEST_JOB_DESCRIPTION: OpportunityStatus.MORE_INFO_REQUIRED,
    Decision.REQUEST_INTERVIEW_DETAILS: OpportunityStatus.MORE_INFO_REQUIRED,
    Decision.REQUEST_MORE_TIME: OpportunityStatus.AWAITING_DECISION,
    Decision.DECLINE: OpportunityStatus.WITHDRAWN,
    Decision.ALREADY_APPLIED: OpportunityStatus.APPLIED,
    Decision.SAVE_FOR_LATER: OpportunityStatus.AWAITING_DECISION,
    Decision.IRRELEVANT: OpportunityStatus.ARCHIVED,
    Decision.CUSTOM: None,
}
# Decisions that defer the choice bring the opportunity back to the queue after this long.
REVISIT_AFTER = {Decision.SAVE_FOR_LATER: timedelta(days=7), Decision.REQUEST_MORE_TIME: timedelta(days=3)}
CONSEQUENTIAL_STATUSES = {
    OpportunityStatus.OFFER_ACCEPTED,
    OpportunityStatus.OFFER_DECLINED,
    OpportunityStatus.WITHDRAWN,
}


def in_decision_queue() -> ColumnElement[bool]:
    """New opportunities, plus deferred ones whose revisit date has arrived."""
    return or_(
        Opportunity.status == OpportunityStatus.NEW,
        and_(
            Opportunity.status == OpportunityStatus.AWAITING_DECISION,
            or_(Opportunity.next_follow_up_at.is_(None), Opportunity.next_follow_up_at <= utcnow()),
        ),
    )


def record_decision(
    db: Session,
    user: User,
    opportunity: Opportunity,
    decision: Decision,
    *,
    notes: str = "",
    custom_decision: str | None = None,
    email_id: uuid.UUID | None = None,
    confirmed: bool = False,
) -> OpportunityDecision:
    if decision == Decision.CUSTOM and not (custom_decision or "").strip():
        raise ValueError("Describe your custom decision.")
    if decision == Decision.DECLINE and not confirmed:
        raise ConfirmationRequired("Declining closes this opportunity. Confirm to continue.")

    status = DECISION_STATUS[decision]
    if decision == Decision.DECLINE and opportunity.status == OpportunityStatus.OFFER_RECEIVED:
        status = OpportunityStatus.OFFER_DECLINED
    if status:
        opportunity.status = status
    opportunity.decision = decision
    opportunity.custom_decision = custom_decision.strip()[:200] if decision == Decision.CUSTOM else None
    if decision in REVISIT_AFTER:
        opportunity.next_follow_up_at = utcnow() + REVISIT_AFTER[decision]

    entry = OpportunityDecision(
        user_id=user.id,
        opportunity_id=opportunity.id,
        email_message_id=email_id,
        decision=decision,
        custom_decision=opportunity.custom_decision,
        notes=notes.strip(),
    )
    db.add(entry)
    db.flush()
    follow_ups_for_decision(db, user, opportunity, entry)
    record_audit(
        db,
        user,
        "opportunity.decision",
        opportunity_id=str(opportunity.id),
        company_id=str(opportunity.company_id) if opportunity.company_id else None,
        decision=decision,
        summary=f"Decision: {opportunity.custom_decision or decision.replace('_', ' ')} ({opportunity.job_title})",
    )
    return entry


def change_status(
    db: Session, user: User, opportunity: Opportunity, status: OpportunityStatus, *, confirmed: bool = False
) -> None:
    if status == opportunity.status:
        return
    if status in CONSEQUENTIAL_STATUSES and not confirmed:
        raise ConfirmationRequired(f"Changing the status to {status.replace('_', ' ')} is significant. Confirm to continue.")
    record_audit(
        db,
        user,
        "opportunity.status",
        opportunity_id=str(opportunity.id),
        company_id=str(opportunity.company_id) if opportunity.company_id else None,
        previous=opportunity.status,
        status=status,
        summary=f"Status changed to {status.replace('_', ' ')} ({opportunity.job_title})",
    )
    opportunity.status = status
