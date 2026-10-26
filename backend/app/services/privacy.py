"""Data retention, export and account deletion."""
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, inspect, select, update
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret
from app.db.base import utcnow
from app.models import (
    AuditLog,
    ClassificationFeedback,
    ClassificationRule,
    Company,
    DraftTemplate,
    DuplicateCandidate,
    EmailDraft,
    EmailMessage,
    EmailMessageGroup,
    FollowUpTask,
    Integration,
    Label,
    Notification,
    Opportunity,
    OpportunityDecision,
    RecruiterContact,
    SheetConflict,
    SheetsConnection,
    SyncJob,
    User,
    WorkflowDefinition,
    WorkflowNodeRun,
    WorkflowRun,
)
from app.schemas.preferences import UserPreferences
from app.services import google_oauth

logger = logging.getLogger(__name__)

READ_NOTIFICATION_RETENTION = timedelta(days=90)
# Credentials stay out of exports; everything else the user owns is included.
_NEVER_EXPORTED = {"access_token_enc", "refresh_token_enc", "lease_expires_at"}

EXPORTED_TABLES: list[tuple[str, type]] = [
    ("integrations", Integration),
    ("labels", Label),
    ("classification_rules", ClassificationRule),
    ("classification_feedback", ClassificationFeedback),
    ("emails", EmailMessage),
    ("companies", Company),
    ("recruiter_contacts", RecruiterContact),
    ("opportunities", Opportunity),
    ("decisions", OpportunityDecision),
    ("duplicate_candidates", DuplicateCandidate),
    ("drafts", EmailDraft),
    ("draft_templates", DraftTemplate),
    ("sheets_connections", SheetsConnection),
    ("sync_jobs", SyncJob),
    ("workflow_definitions", WorkflowDefinition),
    ("workflow_runs", WorkflowRun),
    ("follow_up_tasks", FollowUpTask),
    ("notifications", Notification),
    ("activity", AuditLog),
]


def purge_expired_data(db: Session, now: datetime | None = None) -> dict[str, int]:
    """Remove email bodies past each user's retention period and old read notifications.

    Subjects, senders, classifications and the records built from them stay, so folders and
    opportunities keep working; the full email remains in Gmail.
    """
    now = now or utcnow()
    bodies = 0
    for user in db.scalars(select(User)):
        days = UserPreferences.of(user.preferences).privacy.email_body_retention_days
        if not days:
            continue
        result = db.execute(
            update(EmailMessage)
            .where(
                EmailMessage.user_id == user.id,
                EmailMessage.received_at < now - timedelta(days=days),
                EmailMessage.body_purged_at.is_(None),
            )
            .values(body_text="", body_truncated=False, body_purged_at=now)
        )
        bodies += result.rowcount
    notifications = db.execute(
        delete(Notification).where(Notification.read_at.is_not(None), Notification.read_at < now - READ_NOTIFICATION_RETENTION)
    ).rowcount
    db.commit()
    return {"email_bodies": bodies, "notifications": notifications}


def export_user_data(db: Session, user: User) -> dict[str, Any]:
    """Everything Specify stores for the user, as JSON-ready data. Tokens are never included."""
    data: dict[str, Any] = {
        "exported_at": utcnow(),
        "account": _row(user),
    }
    for name, model in EXPORTED_TABLES:
        data[name] = [_row(row) for row in db.scalars(select(model).where(model.user_id == user.id))]
    data["email_groups"] = [
        _row(row)
        for row in db.scalars(select(EmailMessageGroup).join(EmailMessage).where(EmailMessage.user_id == user.id))
    ]
    data["workflow_steps"] = [
        _row(row) for row in db.scalars(select(WorkflowNodeRun).join(WorkflowRun).where(WorkflowRun.user_id == user.id))
    ]
    data["sheet_conflicts"] = [
        _row(row) for row in db.scalars(select(SheetConflict).join(SheetsConnection).where(SheetsConnection.user_id == user.id))
    ]
    return jsonable_encoder(data)


def delete_account(db: Session, user: User) -> None:
    """Revoke Google access and delete every record of the user. This cannot be undone.

    Gmail labels and drafts, and the user's own spreadsheet, stay in their Google account.
    """
    for integration in db.scalars(select(Integration).where(Integration.user_id == user.id)):
        for encrypted in (integration.refresh_token_enc, integration.access_token_enc):
            token = decrypt_secret(encrypted) if encrypted else None
            if token:
                google_oauth.revoke_token(token)
                break
    # Audit entries would otherwise outlive the account (their user is set to NULL).
    db.execute(delete(AuditLog).where(AuditLog.user_id == user.id))
    db.delete(user)  # every other table cascades from users
    db.commit()
    logger.info("Deleted account %s at the user's request", user.id)


def _row(instance) -> dict[str, Any]:
    return {
        attr.key: getattr(instance, attr.key)
        for attr in inspect(instance).mapper.column_attrs
        if attr.key not in _NEVER_EXPORTED
    }
