"""Calls from Google rather than from the user's browser. Each one authenticates itself."""
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_system_db
from app.models import ConnectionStatus, Integration, User
from app.services.gmail.push import PushRejected, parse_notification, push_enabled, verify_push_request
from app.tasks import enqueue, sync_mailbox_task

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/gmail", status_code=204)
def gmail_push(request: Request, body: dict = Body(...), db: Session = Depends(get_system_db)) -> None:
    """Pub/Sub push for Gmail changes: sync that mailbox now instead of at the next poll."""
    if not push_enabled():
        raise HTTPException(404, "Gmail push notifications are not configured")
    try:
        verify_push_request(request.headers.get("authorization"))
    except PushRejected as exc:
        raise HTTPException(401, "Not a verified push request") from exc
    try:
        notification = parse_notification(body)
    except ValueError:
        return  # acknowledged, so Pub/Sub does not redeliver a message that can never be used
    user_id = db.scalar(
        select(Integration.user_id)
        .join(User, Integration.user_id == User.id)
        .where(
            func.lower(User.email) == notification.email_address,
            Integration.provider == "gmail",
            Integration.connection_status == ConnectionStatus.CONNECTED,
        )
    )
    if user_id is not None:
        enqueue(sync_mailbox_task, str(user_id))
