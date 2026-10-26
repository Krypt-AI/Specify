from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import decrypt_secret
from app.db.session import get_db
from app.models import ConnectionStatus, Integration, User
from app.schemas.user import IntegrationStatus
from app.services import google_oauth
from app.services.audit import record_audit

router = APIRouter(prefix="/integrations", tags=["integrations"])

OPTIONAL_PROVIDERS = ("gmail", "sheets")


@router.get("", response_model=list[IntegrationStatus])
def list_integrations(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[IntegrationStatus]:
    stored = {
        i.provider: i for i in db.scalars(select(Integration).where(Integration.user_id == user.id))
    }
    statuses = []
    for provider in OPTIONAL_PROVIDERS:
        purpose = google_oauth.PURPOSES[provider]
        integration = stored.get(provider)
        statuses.append(
            IntegrationStatus(
                provider=provider,
                connected=integration is not None
                and integration.connection_status == ConnectionStatus.CONNECTED,
                connection_status=integration.connection_status if integration else "not_connected",
                explanation=purpose.explanation,
                scopes=list(purpose.scopes),
                last_sync_at=integration.last_sync_at if integration else None,
                error_message=integration.error_message if integration else None,
            )
        )
    return statuses


@router.delete("/{provider}", status_code=204)
def disconnect_integration(
    provider: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    integration = db.scalar(
        select(Integration).where(Integration.user_id == user.id, Integration.provider == provider)
    )
    if integration is None:
        raise HTTPException(404, "Integration not connected")
    # Revoking the refresh token also invalidates the access token; fall back to the latter.
    for encrypted in (integration.refresh_token_enc, integration.access_token_enc):
        token = decrypt_secret(encrypted) if encrypted else None
        if token:
            google_oauth.revoke_token(token)
            break
    db.delete(integration)
    record_audit(db, user, "integration.disconnected", provider=provider)
    db.commit()
