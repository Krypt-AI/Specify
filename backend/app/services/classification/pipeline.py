"""Classify a stored email, record the decision, then mirror its labels into Gmail.

Each step is idempotent, so a retried task skips the work that already finished.
"""
import logging
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import (
    ClassificationRule,
    ClassificationSource,
    ConnectionStatus,
    EmailMessage,
    EmailMessageGroup,
    Integration,
    Label,
    MailGroup,
    ProcessingStatus,
    User,
)
from app.schemas.preferences import UserPreferences
from app.services import labels as label_service
from app.services.classification.ai import (
    AIClassification,
    ClassificationRequest,
    EmailClassifier,
    LabelOption,
)
from app.services.classification.signals import EmailFeatures, RuleDecision, collect_hints, match_rules
from app.services.dates import ground_dates
from app.services.gmail import client as gmail_client
from app.services.gmail.client import GmailApi, GmailRetryableError
from app.services.gmail.labels import sync_message_labels
from app.services.google_credentials import ReconnectRequired, get_integration
from app.services.llm import AIOutputError, AIUnavailable
from app.services.recruitment.extraction import RecruitmentExtractor
from app.services.recruitment.pipeline import process_recruitment

logger = logging.getLogger(__name__)

STALE_CLAIM = timedelta(minutes=15)
STALE_QUEUE = timedelta(minutes=30)


@dataclass
class Decision:
    primary_group: str | None
    secondary_groups: list[str]
    confidence: float
    source: ClassificationSource
    explanation: str
    label: Label | None = None
    new_label: tuple[str, str] | None = None  # (name, description) proposed by the AI
    rule_id: uuid.UUID | None = None
    reply_required: bool = False
    recommended_action: str | None = None
    suspicious_reasons: list[str] = field(default_factory=list)
    organization: str | None = None
    key_dates: list = field(default_factory=list)


def process_email(
    db: Session,
    email_id: uuid.UUID,
    classifier: EmailClassifier | None,
    *,
    extractor: RecruitmentExtractor | None = None,
    final_attempt: bool = True,
    gmail: GmailApi | None = None,
) -> EmailMessage | None:
    """Classify one email, extract recruitment details when it is a recruitment email, then label it.

    Returns None when another worker owns the email or nothing is left to do.
    """
    email = _claim(db, email_id)
    if email is None:
        return None
    prefs = UserPreferences.of(db.get(User, email.user_id).preferences)
    try:
        if email.processing_status == ProcessingStatus.PROCESSING:
            save_classification(db, email, decide(db, email, prefs, classifier, final_attempt), prefs)
            db.commit()
        if email.awaits_recruitment_step:
            process_recruitment(db, email, prefs, extractor, final_attempt)
        if email.labels_synced_at is None:
            sync_gmail_labels(db, email, prefs, gmail)
            db.commit()
    except (AIUnavailable, GmailRetryableError):
        db.rollback()
        _set_status(db, email_id, ProcessingStatus.PENDING, only_if=ProcessingStatus.PROCESSING)
        raise
    except ReconnectRequired:
        db.rollback()  # the classification is saved; labels follow once Gmail is reconnected
    except Exception:
        db.rollback()
        _set_status(db, email_id, ProcessingStatus.FAILED, error="Unexpected error while processing this email.")
        raise
    return email


def decide(
    db: Session,
    email: EmailMessage,
    prefs: UserPreferences,
    classifier: EmailClassifier | None,
    final_attempt: bool = True,
) -> Decision:
    features = EmailFeatures.of(email)
    rules = list(
        db.scalars(
            select(ClassificationRule)
            .where(ClassificationRule.user_id == email.user_id, ClassificationRule.enabled.is_(True))
            .order_by(ClassificationRule.created_at)
        )
    )
    rule = match_rules(features, rules, prefs)
    if classifier is None:
        return _from_rule(db, rule, "AI classification is not configured.")

    labels = label_service.context_labels(db, email.user_id)
    options = [LabelOption(f"L{i}", label.name, label.description) for i, label in enumerate(labels, start=1)]
    request = ClassificationRequest(
        sender=f"{email.sender_name} <{email.sender_email}>" if email.sender_name else email.sender_email,
        reply_to=email.reply_to,
        received_at=email.received_at,
        subject=email.subject,
        body=email.body_text,
        body_truncated=email.body_truncated,
        attachment_names=[a["filename"] for a in email.attachments],
        link_domains=email.link_domains,
        labels=options,
        certification_providers=[p.name for p in prefs.certifications.providers],
        hints=collect_hints(features, prefs),
        fixed_group=rule.group if rule else None,
    )
    try:
        output = classifier.classify(request)
    except AIUnavailable:
        if not final_attempt:
            raise
        return _from_rule(db, rule, "AI classification is temporarily unavailable.")
    except AIOutputError as exc:
        return _from_rule(db, rule, str(exc))
    return _from_ai(db, output, rule, {option.ref: label for option, label in zip(options, labels)})


def desired_labels(db: Session, email: EmailMessage, prefs: UserPreferences) -> list[Label]:
    desired = []
    if email.processing_status == ProcessingStatus.CLASSIFIED and email.label:
        desired.append(email.label)
    if prefs.classification.apply_status_labels:
        if email.is_suspicious:
            desired.append(label_service.system_label(db, email.user_id, "suspicious"))
        if email.processing_status == ProcessingStatus.REVIEW_REQUIRED:
            desired.append(label_service.system_label(db, email.user_id, "needs_review"))
    return desired


def recoverable_email_ids(db: Session, limit: int = 200) -> list[uuid.UUID]:
    """Emails whose task was lost: claims abandoned by a dead worker, or work still queued long after."""
    now = utcnow()
    abandoned = list(
        db.scalars(
            select(EmailMessage.id)
            .where(
                EmailMessage.processing_status == ProcessingStatus.PROCESSING,
                EmailMessage.updated_at < now - STALE_CLAIM,
            )
            .limit(limit)
        )
    )
    if abandoned:
        db.execute(
            update(EmailMessage)
            .where(EmailMessage.id.in_(abandoned), EmailMessage.processing_status == ProcessingStatus.PROCESSING)
            .values(processing_status=ProcessingStatus.PENDING)
            .execution_options(synchronize_session=False)
        )
        db.commit()
    gmail_connected = and_(
        Integration.user_id == EmailMessage.user_id,
        Integration.provider == "gmail",
        Integration.connection_status == ConnectionStatus.CONNECTED,
    )
    labels_pending = and_(
        EmailMessage.processing_status.in_([ProcessingStatus.CLASSIFIED, ProcessingStatus.REVIEW_REQUIRED]),
        EmailMessage.labels_synced_at.is_(None),
        select(Integration.id).where(gmail_connected).exists(),
    )
    recruitment_pending = and_(
        EmailMessage.processing_status == ProcessingStatus.CLASSIFIED,
        EmailMessage.recruitment_processed_at.is_(None),
        EmailMessage.groups.any(
            and_(EmailMessageGroup.group_name == MailGroup.RECRUITMENT, EmailMessageGroup.is_primary.is_(True))
        ),
    )
    query = (
        select(EmailMessage.id)
        .where(
            EmailMessage.updated_at < now - STALE_QUEUE,
            or_(EmailMessage.processing_status == ProcessingStatus.PENDING, labels_pending, recruitment_pending),
        )
        .limit(limit - len(abandoned))
    )
    return abandoned + list(db.scalars(query))


def _claim(db: Session, email_id: uuid.UUID) -> EmailMessage | None:
    result = db.execute(
        update(EmailMessage)
        .where(EmailMessage.id == email_id, EmailMessage.processing_status == ProcessingStatus.PENDING)
        .values(
            processing_status=ProcessingStatus.PROCESSING,
            processing_attempts=EmailMessage.processing_attempts + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    email = db.get(EmailMessage, email_id, populate_existing=True)
    if email is None:
        return None
    if result.rowcount == 1:
        return email
    finished = email.processing_status in (ProcessingStatus.CLASSIFIED, ProcessingStatus.REVIEW_REQUIRED)
    steps_left = email.labels_synced_at is None or email.awaits_recruitment_step
    return email if finished and steps_left else None


def _from_rule(db: Session, rule: RuleDecision | None, note: str) -> Decision:
    if rule is None:
        return Decision(None, [], 0.0, ClassificationSource.FALLBACK, f"{note} Please review this email.")
    return Decision(
        rule.group,
        [],
        rule.confidence,
        ClassificationSource.RULE,
        rule.reason,
        label=_enabled_label(db, rule.label_id),
        rule_id=rule.rule_id,
    )


def _from_ai(
    db: Session, output: AIClassification, rule: RuleDecision | None, labels_by_ref: dict[str, Label]
) -> Decision:
    primary = rule.group if rule else output.primary_group
    reasons = [r.strip()[:300] for r in output.suspicious_reasons if r.strip()][:10]
    if output.suspicious and not reasons:
        reasons = ["The AI flagged this email as suspicious."]
    decision = Decision(
        primary_group=primary,
        secondary_groups=[g for g in dict.fromkeys(output.secondary_groups) if g != primary],
        confidence=min(max(output.confidence, 0.0), 1.0),
        source=ClassificationSource.AI,
        explanation=output.explanation.strip()[:1000],
        reply_required=output.reply_required,
        recommended_action=output.recommended_action,
        suspicious_reasons=reasons if output.suspicious else [],
        organization=(output.organization or "").strip()[:200] or None,
        key_dates=list(output.key_dates),
    )
    if rule:
        decision.rule_id = rule.rule_id
        decision.explanation = f"{rule.reason} {decision.explanation}"
        if rule.label_id:
            decision.label = _enabled_label(db, rule.label_id)
            decision.confidence = max(decision.confidence, rule.confidence)
            return decision

    choice = output.label
    if choice.existing_label in labels_by_ref:
        decision.label = labels_by_ref[choice.existing_label]
    elif choice.new_label_name:
        decision.new_label = (choice.new_label_name, choice.new_label_description or "")
    return decision


def save_classification(db: Session, email: EmailMessage, decision: Decision, prefs: UserPreferences) -> None:
    confident = (
        decision.primary_group is not None
        and decision.confidence >= prefs.classification.auto_apply_threshold
        and not decision.suspicious_reasons
    )
    label, suggestion = decision.label, None
    if decision.new_label:
        name, description = decision.new_label
        if confident:
            try:
                label = label_service.resolve_label(db, email.user_id, name, description)
            except label_service.LabelNameError:
                label = None
        else:
            suggestion = {"label_id": None, "name": name, "description": description}
    if label and not confident:
        # Uncertain emails get no context label until the user confirms the suggestion.
        suggestion = {"label_id": str(label.id), "name": label.name, "description": label.description}
        label = None

    email.set_groups(decision.primary_group, decision.secondary_groups)
    email.label = label
    if label:
        label.last_used_at = utcnow()
    email.label_suggestion = suggestion
    email.confidence = decision.confidence
    email.classification_source = decision.source
    email.classification_explanation = decision.explanation
    email.matched_rule_id = decision.rule_id
    email.reply_required = decision.reply_required
    email.recommended_action = decision.recommended_action
    email.is_suspicious = bool(decision.suspicious_reasons)
    email.suspicious_reasons = decision.suspicious_reasons
    extracted = {"organization": decision.organization} if decision.organization else {}
    dates = ground_dates(f"{email.subject}\n{email.body_text}", email.received_at, decision.key_dates)
    if dates:
        extracted["dates"] = dates
    email.extracted_data = extracted
    email.processing_status = ProcessingStatus.CLASSIFIED if confident else ProcessingStatus.REVIEW_REQUIRED
    email.processing_error = None
    email.classified_at = utcnow()
    email.labels_synced_at = None


def sync_gmail_labels(db: Session, email: EmailMessage, prefs: UserPreferences, gmail: GmailApi | None) -> None:
    if not prefs.classification.apply_gmail_labels:
        email.labels_synced_at = utcnow()
        return
    integration = get_integration(db, email.user_id, "gmail")
    if integration is None or integration.connection_status != ConnectionStatus.CONNECTED:
        return  # stays pending until Gmail is connected again
    desired = desired_labels(db, email, prefs)
    with nullcontext(gmail) if gmail else gmail_client.gmail_client_for(db, integration) as api:
        sync_message_labels(db, api, email, desired)


def _enabled_label(db: Session, label_id: uuid.UUID | None) -> Label | None:
    label = db.get(Label, label_id) if label_id else None
    return label if label and label.enabled else None


def _set_status(
    db: Session,
    email_id: uuid.UUID,
    status: ProcessingStatus,
    *,
    only_if: ProcessingStatus | None = None,
    error: str | None = None,
) -> None:
    query = update(EmailMessage).where(EmailMessage.id == email_id)
    if only_if:
        query = query.where(EmailMessage.processing_status == only_if)
    values = {"processing_status": status}
    if error:
        values["processing_error"] = error
    db.execute(query.values(**values).execution_options(synchronize_session=False))
    db.commit()
