from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ConnectionStatus, EmailMessage, ProcessingStatus, SyncStatus, User
from app.schemas.email import SyncStatusOut
from app.services.google_credentials import get_integration
from app.tasks import enqueue, sync_mailbox_task

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/gmail", response_model=SyncStatusOut)
def gmail_sync_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SyncStatusOut:
    integration = get_integration(db, user.id, "gmail")
    state = integration.sync_state if integration else None
    queued = db.scalar(
        select(func.count())
        .select_from(EmailMessage)
        .where(
            EmailMessage.user_id == user.id,
            EmailMessage.processing_status.in_([ProcessingStatus.PENDING, ProcessingStatus.PROCESSING]),
        )
    )
    return SyncStatusOut(
        connected=integration is not None and integration.connection_status == ConnectionStatus.CONNECTED,
        status=state.status if state else SyncStatus.IDLE,
        last_synced_at=integration.last_sync_at if integration else None,
        initial_sync_completed_at=state.initial_sync_completed_at if state else None,
        last_error=state.last_error if state else None,
        queued_emails=queued,
    )


@router.post("/gmail", status_code=202)
def trigger_gmail_sync(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, str]:
    integration = get_integration(db, user.id, "gmail")
    if integration is None or integration.connection_status != ConnectionStatus.CONNECTED:
        raise HTTPException(409, "Connect Gmail before synchronizing.")
    if not enqueue(sync_mailbox_task, str(user.id)):
        raise HTTPException(503, "The background worker is unavailable. Please try again shortly.")
    return {"status": "queued"}
