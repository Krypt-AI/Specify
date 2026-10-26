import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import AuditLog, User

router = APIRouter(prefix="/activity", tags=["activity"])


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action: str
    entity_type: str | None
    entity_id: str | None
    details: dict
    created_at: datetime


@router.get("", response_model=list[ActivityOut])
def list_activity(
    action: str | None = Query(None, max_length=64, description="Prefix such as opportunity. or workflow."),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ActivityOut]:
    """The user's audit log, newest first. Tokens and email content are never recorded here."""
    query = select(AuditLog).where(AuditLog.user_id == user.id)
    if action:
        query = query.where(AuditLog.action.startswith(action))
    events = db.scalars(query.order_by(AuditLog.created_at.desc()).limit(limit))
    return [ActivityOut.model_validate(e) for e in events]
