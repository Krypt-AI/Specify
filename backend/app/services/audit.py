import uuid

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.models.user import User


def record_audit(db: Session, user: User | None, action: str, **details) -> None:
    record_event(db, user.id if user else None, action, **details)


def record_event(
    db: Session,
    user_id: uuid.UUID | None,
    action: str,
    *,
    entity_type: str | None = None,
    entity_id: uuid.UUID | str | None = None,
    **details,
) -> None:
    """Append to the audit log, which also feeds the activity log and the Activity sheet."""
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            details=details,
        )
    )
