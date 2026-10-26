"""What each workflow step does. Steps reuse the same services as the rest of Specify.

In a test run, steps with lasting effects (database writes, Gmail, Sheets, reminders) are
simulated and report what they would have done.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from functools import cached_property

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import (
    Company,
    EmailMessage,
    FollowUpTask,
    Notification,
    Opportunity,
    OpportunityDecision,
    OpportunityStatus,
    ProcessingStatus,
    User,
    WorkflowRun,
)
from app.schemas.preferences import UserPreferences
from app.services import llm
from app.services.classification import ai
from app.services.classification.pipeline import decide, desired_labels, save_classification, sync_gmail_labels
from app.services.drafting.service import draft_for_decision, generate_draft
from app.services.drafting.templates import DRAFT_DECISIONS
from app.services.email_domains import domain_of
from app.services.recruitment import extraction
from app.services.recruitment.decisions import CONSEQUENTIAL_STATUSES, in_decision_queue
from app.services.recruitment.extraction import ExtractionRequest
from app.services.recruitment.pipeline import process_recruitment
from app.services.reminders import reminders_from_email
from app.services.workflows.nodes import NodeResult


class NodeError(Exception):
    """A step cannot run as configured; retrying will not help."""


@dataclass
class NodeContext:
    db: Session
    run: WorkflowRun
    node_id: str
    node_type: str
    config: dict
    user: User
    prefs: UserPreferences
    attempt: int
    final_attempt: bool

    @property
    def test(self) -> bool:
        return self.run.is_test

    @property
    def context(self) -> dict:
        return self.run.execution_context

    def remember(self, **values) -> None:
        # JSON columns only notice reassignment, so always store a fresh copy.
        self.run.execution_context = {**self.run.execution_context, **values}

    @cached_property
    def email(self) -> EmailMessage | None:
        email_id = self.context.get("email_id")
        email = self.db.get(EmailMessage, uuid.UUID(email_id)) if email_id else None
        return email if email and email.user_id == self.user.id else None

    @property
    def opportunity(self) -> Opportunity | None:
        opportunity_id = self.context.get("opportunity_id") or (
            str(self.email.opportunity_id) if self.email and self.email.opportunity_id else None
        )
        opportunity = self.db.get(Opportunity, uuid.UUID(opportunity_id)) if opportunity_id else None
        return opportunity if opportunity and opportunity.user_id == self.user.id else None

    def require_email(self) -> EmailMessage:
        if self.email is None:
            raise NodeError("This step needs the email that started the workflow.")
        return self.email


def run_node(ctx: NodeContext) -> NodeResult:
    return EXECUTORS[ctx.node_type](ctx)


def facts(ctx: NodeContext) -> dict:
    """Values a Condition step can check. Test runs see their simulated results."""
    values: dict = {}
    email, opportunity = ctx.email, ctx.opportunity
    if email:
        values.update({
            "email.primary_group": email.primary_group,
            "email.secondary_groups": email.secondary_groups,
            "email.processing_status": email.processing_status,
            "email.is_suspicious": email.is_suspicious,
            "email.confidence": email.confidence,
            "email.reply_required": email.reply_required,
            "email.sender_domain": domain_of(email.sender_email),
            "email.label": email.label.name if email.label else None,
        })
    values["opportunity.exists"] = opportunity is not None
    if opportunity:
        awaiting = ctx.db.scalar(select(Opportunity.id).where(Opportunity.id == opportunity.id, in_decision_queue()))
        values.update({
            "opportunity.status": opportunity.status,
            "opportunity.decision": opportunity.decision,
            "opportunity.awaiting_decision": awaiting is not None,
            "opportunity.priority": opportunity.priority,
        })
    decision = _decision(ctx)
    values["decision.value"] = decision.decision if decision else None
    values.update(ctx.context.get("simulated", {}))
    return values


def evaluate(operator: str, actual, expected: str) -> bool:
    if operator == "is_true":
        return bool(actual)
    if operator == "is_false":
        return not actual
    if operator in ("greater_than", "less_than"):
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            return False
        return left > right if operator == "greater_than" else left < right
    if operator == "contains":
        items = actual if isinstance(actual, list) else str(actual or "")
        return expected.lower() in ([str(i).lower() for i in items] if isinstance(items, list) else items.lower())
    matches = str(actual if actual is not None else "").lower() == expected.strip().lower()
    return matches if operator == "equals" else not matches


def render_text(template: str, ctx: NodeContext) -> str:
    opportunity, email = ctx.opportunity, ctx.email
    values = {
        "job_title": opportunity.job_title if opportunity else "an opportunity",
        "company": (opportunity.company_name if opportunity else None) or "an unknown company",
        "subject": email.subject if email else "",
        "sender": (email.sender_name or email.sender_email) if email else "",
    }
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


# --- Triggers and logic -----------------------------------------------------------------------

def _trigger(ctx: NodeContext) -> NodeResult:
    return NodeResult(output={"email_id": ctx.context.get("email_id")} if ctx.context.get("email_id") else {})


def _email_filter(ctx: NodeContext) -> NodeResult:
    email = ctx.require_email()
    config = ctx.config
    sender_domain = domain_of(email.sender_email)
    reasons = []
    if any(sender_domain == d or sender_domain.endswith(f".{d}") for d in config["skip_sender_domains"]):
        reasons.append(f"sender domain {sender_domain}")
    if email.sender_email.lower() in [a.lower() for a in config["skip_sender_addresses"]]:
        reasons.append("sender address")
    if any(k.lower() in email.subject.lower() for k in config["skip_subject_keywords"]):
        reasons.append("subject keyword")
    if config["skip_bulk"] and ("list-unsubscribe" in email.headers or email.headers.get("precedence") in ("bulk", "list")):
        reasons.append("bulk mail")
    days = config["skip_older_than_days"]
    if days and email.received_at < utcnow() - timedelta(days=days):
        reasons.append(f"older than {days} days")
    if reasons:
        return NodeResult(branch="false", output={"skipped_because": reasons})
    return NodeResult(branch="true", output={"passed": True})


def _condition(ctx: NodeContext) -> NodeResult:
    field, operator, expected = ctx.config["field"], ctx.config["operator"], str(ctx.config.get("value", ""))
    actual = facts(ctx).get(field)
    result = evaluate(operator, actual, expected)
    return NodeResult(branch="true" if result else "false", output={"field": field, "value": actual, "result": result})


def _delay(ctx: NodeContext) -> NodeResult:
    if ctx.test:
        return NodeResult(status="simulated", output={"would_wait_minutes": ctx.config["minutes"]})
    key = f"wait_until:{ctx.node_id}"
    until = ctx.context.get(key)
    if until and datetime.fromisoformat(until) <= utcnow():
        return NodeResult(output={"waited_until": until})
    if not until:
        until = (utcnow() + timedelta(minutes=ctx.config["minutes"])).isoformat()
        ctx.remember(**{key: until})
    seconds = max(1, int((datetime.fromisoformat(until) - utcnow()).total_seconds()))
    return NodeResult(status="waiting", waiting_for={"kind": "delay", "until": until}, resume_after_seconds=seconds)


def _end(ctx: NodeContext) -> NodeResult:
    return NodeResult(output={"finished": True})


# --- Email and AI steps ------------------------------------------------------------------------

def _classification(ctx: NodeContext) -> NodeResult:
    email = ctx.require_email()
    if email.processing_status in (ProcessingStatus.CLASSIFIED, ProcessingStatus.REVIEW_REQUIRED) and not ctx.test:
        return NodeResult(status="skipped", output={"already": email.processing_status})
    decision = decide(ctx.db, email, ctx.prefs, ai.get_classifier(), final_attempt=ctx.final_attempt)
    summary = {
        "primary_group": decision.primary_group,
        "confidence": round(decision.confidence, 2),
        "label": decision.label.name if decision.label else (decision.new_label[0] if decision.new_label else None),
        "suspicious": bool(decision.suspicious_reasons),
        "explanation": decision.explanation[:300],
    }
    if ctx.test:
        ctx.remember(simulated={**ctx.context.get("simulated", {}), "email.primary_group": decision.primary_group})
        return NodeResult(status="simulated", output=summary)
    email.processing_status = ProcessingStatus.PROCESSING
    save_classification(ctx.db, email, decision, ctx.prefs)
    ctx.db.commit()
    return NodeResult(output={**summary, "status": email.processing_status})


def _extraction(ctx: NodeContext) -> NodeResult:
    email = ctx.require_email()
    group = ctx.context.get("simulated", {}).get("email.primary_group") if ctx.test else email.primary_group
    if group != "recruitment":
        return NodeResult(status="skipped", output={"reason": "Not a recruitment email."})
    if ctx.test:
        extractor = extraction.get_extractor()
        if extractor is None:
            return NodeResult(status="simulated", output={"reason": "AI is off; nothing would be extracted."})
        result = extractor.extract(
            ExtractionRequest(
                sender=email.sender_email, received_at=email.received_at, subject=email.subject, body=email.body_text,
                body_truncated=email.body_truncated, attachment_names=[], preferences=ctx.prefs.recruitment,
            )
        )
        return NodeResult(status="simulated", output={"would_extract": result.model_dump(include={"email_type", "employer", "job"})})
    if not ctx.prefs.automation.update_records:
        return NodeResult(status="skipped", output={"reason": "Automatic record updates are off."})
    if not email.awaits_recruitment_step:
        return NodeResult(status="skipped", output={"reason": email.recruitment_note or "Already processed."})
    process_recruitment(ctx.db, email, ctx.prefs, extraction.get_extractor(), ctx.final_attempt)
    if email.opportunity_id:
        ctx.remember(opportunity_id=str(email.opportunity_id))
    return NodeResult(output={"note": email.recruitment_note, "opportunity_id": ctx.context.get("opportunity_id")})


def _company_lookup(ctx: NodeContext) -> NodeResult:
    opportunity = ctx.opportunity
    company = ctx.db.get(Company, opportunity.company_id) if opportunity and opportunity.company_id else None
    if company is None:
        return NodeResult(status="skipped", output={"found": False})
    ctx.remember(company_id=str(company.id))
    return NodeResult(output={"found": True, "company": company.name, "type": company.company_type})


def _opportunity_lookup(ctx: NodeContext) -> NodeResult:
    opportunity = ctx.opportunity
    if opportunity is None:
        return NodeResult(status="skipped", output={"found": False})
    ctx.remember(opportunity_id=str(opportunity.id))
    return NodeResult(output={"found": True, "job_title": opportunity.job_title, "status": opportunity.status})


def _gmail_label(ctx: NodeContext) -> NodeResult:
    email = ctx.require_email()
    if ctx.test:
        names = [label.name for label in desired_labels(ctx.db, email, ctx.prefs)]
        return NodeResult(status="simulated", output={"would_apply": names})
    if email.processing_status not in (ProcessingStatus.CLASSIFIED, ProcessingStatus.REVIEW_REQUIRED):
        return NodeResult(status="skipped", output={"reason": "The email is not classified yet."})
    email.labels_synced_at = None
    sync_gmail_labels(ctx.db, email, ctx.prefs, None)
    ctx.db.commit()
    return NodeResult(output={"labels": [label.name for label in desired_labels(ctx.db, email, ctx.prefs)]})


# --- People steps -------------------------------------------------------------------------------

def _decision(ctx: NodeContext) -> OpportunityDecision | None:
    decision_id = ctx.context.get("decision_id")
    return ctx.db.get(OpportunityDecision, uuid.UUID(decision_id)) if decision_id else None


def _decision_input(ctx: NodeContext) -> NodeResult:
    opportunity = ctx.opportunity
    if opportunity is None:
        return NodeResult(status="skipped", output={"reason": "No opportunity to decide on."})
    if ctx.test:
        return NodeResult(status="simulated", output={"would_wait_for_decision_on": opportunity.job_title})
    decision = _decision(ctx)
    if decision is None and ctx.db.scalar(select(Opportunity.id).where(Opportunity.id == opportunity.id, in_decision_queue())) is None:
        # Decided before this step was reached: continue with the latest decision.
        decision = ctx.db.scalar(
            select(OpportunityDecision)
            .where(OpportunityDecision.opportunity_id == opportunity.id)
            .order_by(OpportunityDecision.created_at.desc())
        )
        if decision:
            ctx.remember(decision_id=str(decision.id))
    if decision is None:
        return NodeResult(
            status="waiting",
            waiting_for={"kind": "decision", "opportunity_id": str(opportunity.id), "message": f"Decide on {opportunity.job_title}"},
        )
    return NodeResult(output={"decision": decision.decision})


def _approval(ctx: NodeContext) -> NodeResult:
    key = f"approval:{ctx.node_id}"
    if ctx.test:
        return NodeResult(status="simulated", branch="true", output={"would_ask": ctx.config["message"]})
    if key in ctx.context:
        approved = bool(ctx.context[key])
        return NodeResult(branch="true" if approved else "false", output={"approved": approved})
    return NodeResult(status="waiting", waiting_for={"kind": "approval", "node_id": ctx.node_id, "message": render_text(ctx.config["message"], ctx)})


def _reminder(ctx: NodeContext) -> NodeResult:
    opportunity, email = ctx.opportunity, ctx.require_email()
    days = ctx.config["due_in_days"]
    start = utcnow()
    if ctx.config["relative_to"] == "application_deadline":
        if not (opportunity and opportunity.application_deadline):
            return NodeResult(status="skipped", output={"reason": "No application deadline."})
        start = datetime.combine(opportunity.application_deadline, time(9), utcnow().tzinfo)
        days = -days  # remind before the deadline
    due = start + timedelta(days=days)
    title = render_text(ctx.config["title"], ctx)[:300]
    if ctx.test:
        return NodeResult(status="simulated", output={"would_remind": title, "due": due.isoformat()})
    created = _insert_once(
        ctx.db,
        FollowUpTask(
            user_id=ctx.user.id, opportunity_id=opportunity.id if opportunity else None, email_message_id=email.id,
            kind="follow_up", title=title, due_at=due, source="workflow", idempotency_key=f"run:{ctx.run.id}:{ctx.node_id}",
        ),
    )
    return NodeResult(output={"title": title, "due": due.isoformat(), "created": created})


def _date_reminders(ctx: NodeContext) -> NodeResult:
    email = ctx.require_email()
    dates = email.extracted_data.get("dates", [])
    if ctx.test:
        return NodeResult(status="simulated", output={"dates": dates})
    if not dates and not (ctx.prefs.reminders.reply_needed and email.reply_required):
        return NodeResult(status="skipped", output={"reason": "No dates in this email."})
    return NodeResult(output=reminders_from_email(ctx.db, email, ctx.prefs))


def _notification(ctx: NodeContext) -> NodeResult:
    title, body = render_text(ctx.config["title"], ctx)[:200], render_text(ctx.config["message"], ctx)
    if ctx.test:
        return NodeResult(status="simulated", output={"would_notify": title})
    if ctx.prefs.automation.notify_new_opportunities is False and "opportunity" in title.lower():
        return NodeResult(status="skipped", output={"reason": "New-opportunity notifications are off."})
    opportunity = ctx.opportunity
    link = f"/decisions?id={opportunity.id}" if opportunity else (f"/inbox?email={ctx.email.id}" if ctx.email else None)
    created = _insert_once(
        ctx.db,
        Notification(user_id=ctx.user.id, kind="workflow", title=title, body=body, link=link, idempotency_key=f"run:{ctx.run.id}:{ctx.node_id}"),
    )
    return NodeResult(output={"title": title, "created": created})


# --- Records and integrations -------------------------------------------------------------------

def _database_update(ctx: NodeContext) -> NodeResult:
    opportunity = ctx.opportunity
    if opportunity is None:
        return NodeResult(status="skipped", output={"reason": "No opportunity."})
    action, value = ctx.config["action"], str(ctx.config["value"]).strip()
    if action == "set_status":
        try:
            status = OpportunityStatus(value)
        except ValueError as exc:
            raise NodeError(f"Unknown status {value!r}.") from exc
        if status in CONSEQUENTIAL_STATUSES:
            raise NodeError("That status needs your confirmation, so automation cannot set it.")
    elif action == "set_priority" and value not in ("low", "normal", "high"):
        raise NodeError("Priority must be low, normal or high.")
    if ctx.test:
        return NodeResult(status="simulated", output={"would": action, "value": value})
    if action == "set_status":
        opportunity.status = value
    elif action == "set_priority":
        opportunity.priority = value
    else:
        opportunity.notes = "\n".join(filter(None, (opportunity.notes, render_text(value, ctx))))
    ctx.db.commit()
    return NodeResult(output={action: value})


def _sheets_sync(ctx: NodeContext) -> NodeResult:
    if ctx.test:
        return NodeResult(status="simulated", output={"would_sync": True})
    from app.tasks import schedule_sheets_sync  # imported here: tasks import the workflow engine

    schedule_sheets_sync(ctx.db, ctx.user.id)
    return NodeResult(output={"requested": True})


def _gmail_draft(ctx: NodeContext) -> NodeResult:
    if not ctx.prefs.automation.generate_drafts:
        return NodeResult(status="skipped", output={"reason": "Draft generation is off."})
    decision, opportunity = _decision(ctx), ctx.opportunity
    if decision is None or opportunity is None:
        return NodeResult(status="skipped", output={"reason": "No decision to reply to."})
    if decision.decision not in DRAFT_DECISIONS:
        return NodeResult(status="skipped", output={"reason": f"“{decision.decision}” needs no reply."})
    if ctx.test:
        return NodeResult(status="simulated", output={"would_draft": decision.decision})
    approval = f"approval:{ctx.node_id}"
    if ctx.prefs.automation.approve_before_drafting and approval not in ctx.context:
        return NodeResult(status="waiting", waiting_for={"kind": "approval", "node_id": ctx.node_id, "message": "Write the reply draft?"})
    if approval in ctx.context and not ctx.context[approval]:
        return NodeResult(status="skipped", output={"reason": "You chose not to draft a reply."})
    draft = draft_for_decision(ctx.db, ctx.user, opportunity, decision)
    if draft is None:
        return NodeResult(status="skipped", output={"reason": "No email to reply to."})
    generate_draft(ctx.db, draft.id, llm.get_backend(), final_attempt=ctx.final_attempt)
    ctx.remember(draft_id=str(draft.id))
    return NodeResult(output={"draft_id": str(draft.id), "status": draft.status})


# --- Reliability --------------------------------------------------------------------------------

def _error_handler(ctx: NodeContext) -> NodeResult:
    error = ctx.context.get("last_error", {})
    if not ctx.test and ctx.prefs.automation.notify_failures:
        _insert_once(
            ctx.db,
            Notification(
                user_id=ctx.user.id, kind="workflow_error", title="A workflow step failed",
                body=f"{error.get('node_id', 'A step')}: {error.get('message', 'unknown error')}",
                link=f"/activity?run={ctx.run.id}", idempotency_key=f"run:{ctx.run.id}:{ctx.node_id}",
            ),
        )
    return NodeResult(output={"handled": error})


def _retry(ctx: NodeContext) -> NodeResult:
    error = ctx.context.get("last_error", {})
    target = error.get("node_id")
    used = ctx.context.get(f"retries:{ctx.node_id}", 0)
    if not target or used >= ctx.config["max_attempts"]:
        return NodeResult(output={"gave_up_after": used})
    ctx.remember(**{f"retries:{ctx.node_id}": used + 1})
    return NodeResult(status="rewind", rewind_to=target, resume_after_seconds=ctx.config["delay_minutes"] * 60, output={"retrying": target, "attempt": used + 1})


def _insert_once(db: Session, record) -> bool:
    """Insert unless a record with the same idempotency key exists (a step re-run after a crash)."""
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


EXECUTORS = {
    "gmail_new_email": _trigger,
    "scheduled_trigger": _trigger,
    "email_filter": _email_filter,
    "classification": _classification,
    "information_extraction": _extraction,
    "company_lookup": _company_lookup,
    "opportunity_lookup": _opportunity_lookup,
    "conditional_branch": _condition,
    "user_approval": _approval,
    "decision_input": _decision_input,
    "database_update": _database_update,
    "sheets_sync": _sheets_sync,
    "gmail_label": _gmail_label,
    "gmail_draft": _gmail_draft,
    "date_reminders": _date_reminders,
    "reminder": _reminder,
    "notification": _notification,
    "delay": _delay,
    "error_handler": _error_handler,
    "retry": _retry,
    "end": _end,
}
