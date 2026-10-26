"""Draft lifecycle: request → generate (AI or template) → check → save in Gmail → edit or discard.

Specify never sends email. A draft lives in Gmail until the user sends or deletes it there.
"""
import base64
import uuid
from contextlib import nullcontext
from email.message import EmailMessage as MimeMessage

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import (
    ConnectionStatus,
    DraftStatus,
    EmailDraft,
    EmailMessage,
    Opportunity,
    OpportunityDecision,
    User,
)
from app.schemas.preferences import UserPreferences
from app.services.drafting.generator import DraftContext, generate_with_ai
from app.services.drafting.quality import check_draft
from app.services.drafting.templates import DRAFT_DECISIONS, MISSING_QUESTIONS, SCENARIOS, render, resolve_template
from app.services.gmail import client as gmail_client
from app.services.gmail.client import GmailApi
from app.services.google_api import GoogleNotFound
from app.services.google_credentials import ReconnectRequired, get_integration
from app.services.llm import AIOutputError, AIUnavailable, LLMBackend
from app.services.recruitment.insights import missing_information
from app.services.sheets.mapping import format_salary

TONES = {"formal": "formal", "friendly": "friendly and professional", "concise": "concise", "enthusiastic": "enthusiastic"}
NO_LONGER_IN_GMAIL = "This draft is no longer in Gmail (it was sent or deleted there). Your changes are saved in Specify."


def scenario_for_email(email: EmailMessage) -> str:
    return {"university": "university_reply", "certifications": "certification_reply"}.get(
        email.primary_group or "", "general_reply"
    )


def reply_subject(subject: str) -> str:
    subject = subject.strip()
    if not subject:
        return "Re: your email"
    return subject if subject.lower().startswith("re:") else f"Re: {subject}"


def request_draft(
    db: Session,
    user: User,
    email: EmailMessage,
    *,
    scenario: str,
    key: str,
    opportunity_id: uuid.UUID | None = None,
    decision: OpportunityDecision | None = None,
    tone: str | None = None,
    instructions: str = "",
) -> EmailDraft:
    """Create the draft record (status generating). The same key always returns the same draft."""
    existing = db.scalar(select(EmailDraft).where(EmailDraft.user_id == user.id, EmailDraft.idempotency_key == key))
    if existing:
        return existing
    prefs = UserPreferences.of(user.preferences)
    draft = EmailDraft(
        user_id=user.id,
        email_message_id=email.id,
        opportunity_id=opportunity_id or email.opportunity_id,
        decision_id=decision.id if decision else None,
        idempotency_key=key,
        scenario=scenario,
        decision=decision.decision if decision else None,
        tone=(tone or TONES[prefs.draft_tone])[:40],
        instructions=instructions.strip(),
        recipient=email.reply_to or email.sender_email,
        subject=reply_subject(email.subject),
        gmail_thread_id=email.gmail_thread_id,
    )
    db.add(draft)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(EmailDraft).where(EmailDraft.user_id == user.id, EmailDraft.idempotency_key == key))
    return draft


def draft_for_decision(
    db: Session, user: User, opportunity: Opportunity, decision: OpportunityDecision
) -> EmailDraft | None:
    """Prepare the reply a decision calls for, answering the email it was made on (or the latest one)."""
    if decision.decision not in DRAFT_DECISIONS:
        return None
    email = db.get(EmailMessage, decision.email_message_id) if decision.email_message_id else None
    if email is None:
        email = db.scalar(
            select(EmailMessage)
            .where(EmailMessage.opportunity_id == opportunity.id)
            .order_by(EmailMessage.received_at.desc())
        )
    if email is None:
        return None  # created by hand without an email: nothing to reply to
    return request_draft(
        db, user, email, scenario=decision.decision, key=f"decision:{decision.id}", opportunity_id=opportunity.id, decision=decision
    )


def generate_draft(
    db: Session,
    draft_id: uuid.UUID,
    backend: LLMBackend | None,
    *,
    final_attempt: bool = True,
    gmail: GmailApi | None = None,
) -> EmailDraft | None:
    draft = db.get(EmailDraft, draft_id)
    if draft is None or draft.status in (DraftStatus.DISCARDED, DraftStatus.FAILED):
        return draft
    if draft.status == DraftStatus.READY:
        if draft.gmail_synced_at is None and not draft.error:
            save_to_gmail(db, draft, gmail)  # a retry after Gmail was unavailable
        return draft
    user = db.get(User, draft.user_id)
    prefs = UserPreferences.of(user.preferences)
    template = resolve_template(db, user.id, draft.scenario)
    context = build_context(db, draft, template.instructions, prefs)

    body, generated_by, notes = None, "template", []
    if backend is not None and template.use_ai:
        try:
            output = generate_with_ai(backend, context)
            body, generated_by = output.body.strip() or None, "ai"
            if output.notes_for_user:
                notes.append(output.notes_for_user.strip()[:300])
        except AIUnavailable:
            if not final_attempt:
                raise
            notes.append("Written from your template because the AI was unavailable.")
        except AIOutputError:
            notes.append("Written from your template because the AI's answer could not be used.")
    if body is None:
        body, generated_by = render(template.body, template_values(context, draft)), "template"

    draft.body = body
    draft.generated_by = generated_by
    draft.warnings = check_draft(
        body, decision=draft.decision, known_text=context.known_text, approved_values=list(context.profile.values())
    ) + notes
    draft.status, draft.error = DraftStatus.READY, None
    db.commit()
    save_to_gmail(db, draft, gmail)
    return draft


def save_to_gmail(db: Session, draft: EmailDraft, gmail: GmailApi | None = None, *, recreate: bool = False) -> None:
    """Create or update the Gmail draft in the original thread. Retryable errors propagate."""
    integration = get_integration(db, draft.user_id, "gmail")
    if integration is None or integration.connection_status != ConnectionStatus.CONNECTED:
        draft.error = "Connect Gmail to save this draft there."
        db.commit()
        return
    if draft.gmail_synced_at and not draft.gmail_draft_id and not recreate:
        draft.error = NO_LONGER_IN_GMAIL
        db.commit()
        return
    raw = build_raw_message(draft)
    try:
        with nullcontext(gmail) if gmail else gmail_client.gmail_client_for(db, integration) as api:
            if draft.gmail_draft_id:
                try:
                    result = api.update_draft(draft.gmail_draft_id, raw, draft.gmail_thread_id)
                except GoogleNotFound:
                    # Sent or deleted in Gmail: never recreate it behind the user's back.
                    draft.gmail_draft_id, draft.error = None, NO_LONGER_IN_GMAIL
                    db.commit()
                    return
            else:
                result = api.create_draft(raw, draft.gmail_thread_id)
    except ReconnectRequired as exc:
        draft.error = str(exc)
        db.commit()
        return
    draft.gmail_draft_id = result["id"]
    draft.gmail_message_id = result.get("message", {}).get("id")
    draft.gmail_synced_at, draft.error = utcnow(), None
    db.commit()


def discard_draft(db: Session, draft: EmailDraft, gmail: GmailApi | None = None) -> None:
    integration = get_integration(db, draft.user_id, "gmail")
    if draft.gmail_draft_id and integration and integration.connection_status == ConnectionStatus.CONNECTED:
        try:
            with nullcontext(gmail) if gmail else gmail_client.gmail_client_for(db, integration) as api:
                api.delete_draft(draft.gmail_draft_id)
        except (GoogleNotFound, ReconnectRequired):
            pass  # already gone, or Gmail is disconnected; the draft is discarded in Specify either way
    draft.status, draft.gmail_draft_id = DraftStatus.DISCARDED, None
    db.commit()


def build_raw_message(draft: EmailDraft) -> str:
    """An RFC 2822 reply that Gmail threads with the original message."""
    original = draft.email
    message = MimeMessage()
    message["To"] = draft.recipient
    message["Subject"] = draft.subject
    message_id = original.headers.get("message-id")
    if message_id:
        message["In-Reply-To"] = message_id
        message["References"] = f"{original.headers.get('references', '')} {message_id}".strip()
    message.set_content(draft.body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode()


def build_context(db: Session, draft: EmailDraft, instructions: str, prefs: UserPreferences) -> DraftContext:
    email = draft.email
    opportunity = db.get(Opportunity, draft.opportunity_id) if draft.opportunity_id else None
    decision = db.get(OpportunityDecision, draft.decision_id) if draft.decision_id else None
    facts = {}
    missing = []
    if opportunity:
        deadline = opportunity.application_deadline.isoformat() if opportunity.application_deadline else opportunity.deadline_text
        salary = format_salary(opportunity.salary_min, opportunity.salary_max)
        facts = {
            "Role": opportunity.job_title,
            "Company": opportunity.company_name or "",
            "Salary": f"{opportunity.salary_currency or ''} {salary} per {opportunity.salary_period or 'period'}".strip() if salary else "",
            "Work arrangement": opportunity.work_arrangement or "",
            "Location": opportunity.location or "",
            "Deadline": deadline or "",
        }
        missing = [key.replace("_", " ") for key in missing_information(opportunity)]
    earlier = [
        f"{e.sender_name or e.sender_email}: {e.subject} — {e.snippet[:200]}"
        for e in db.scalars(
            select(EmailMessage)
            .where(
                EmailMessage.user_id == draft.user_id,
                EmailMessage.gmail_thread_id == email.gmail_thread_id,
                EmailMessage.id != email.id,
                EmailMessage.received_at < email.received_at,
            )
            .order_by(EmailMessage.received_at.desc())
            .limit(3)
        ).unique()
    ]
    profile = prefs.drafting.profile
    approved = {"Name": profile.full_name, "Signature": profile.signature, "Phone": profile.phone, "LinkedIn": profile.linkedin_url}
    notes = " ".join(filter(None, (decision.custom_decision if decision else None, decision.notes if decision else None)))
    known = "\n".join([email.subject, email.body_text, *facts.values(), *earlier, notes, draft.instructions])
    return DraftContext(
        scenario_label=SCENARIOS[draft.scenario].label,
        instructions=instructions,
        user_instructions=draft.instructions,
        tone=draft.tone,
        length=prefs.drafting.length,
        language=prefs.drafting.language,
        recipient_name=email.sender_name or "Sir or Madam",
        original_from=f"{email.sender_name} <{email.sender_email}>" if email.sender_name else email.sender_email,
        original_subject=email.subject,
        original_body=email.body_text,
        earlier_messages=earlier,
        facts=facts,
        missing_information=missing,
        decision_notes=notes,
        profile=approved,
        known_text=known,
    )


def template_values(context: DraftContext, draft: EmailDraft) -> dict[str, str]:
    profile = context.profile
    company = context.facts.get("Company")
    keys = [k.replace(" ", "_") for k in context.missing_information]
    return {
        "recipient": context.recipient_name,
        "role": context.facts.get("Role") or "open",
        "at_company": f" at {company}" if company else "",
        "subject": context.original_subject or "your message",
        "signature": profile.get("Signature") or profile.get("Name") or "[Your name]",
        "missing_questions": "\n".join(MISSING_QUESTIONS[k] for k in keys if k in MISSING_QUESTIONS) or "- [your questions]",
        "custom_decision": context.decision_notes or "describe your reply",
    }
