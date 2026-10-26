"""Valid Google access tokens for a stored integration, refreshed on demand."""
from datetime import timedelta
from typing import NoReturn

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret, encrypt_secret
from app.db.base import utcnow
from app.models import ConnectionStatus, Integration, Notification
from app.services import google_oauth
from app.services.audit import record_audit

REFRESH_MARGIN = timedelta(minutes=2)


class ReconnectRequired(Exception):
    """The user must reconnect the integration; background work for it stops until they do."""


def get_integration(db: Session, user_id, provider: str) -> Integration | None:
    return db.scalar(
        select(Integration).where(Integration.user_id == user_id, Integration.provider == provider)
    )


class IntegrationCredentials:
    """Access-token source for one integration. Marks it for reconnection when Google refuses it."""

    def __init__(self, db: Session, integration: Integration):
        self._db = db
        self._integration = integration

    def access_token(self, force_refresh: bool = False) -> str:
        integration = self._integration
        if integration.connection_status != ConnectionStatus.CONNECTED:
            raise ReconnectRequired(integration.error_message or "Please reconnect this integration.")
        missing = set(google_oauth.PURPOSES[integration.provider].scopes) - set(integration.scopes)
        if missing:
            self.reject("Specify needs updated permissions. Please reconnect to grant them.")

        token = decrypt_secret(integration.access_token_enc) if integration.access_token_enc else None
        expires_at = integration.token_expires_at
        if token and not force_refresh and expires_at and expires_at - REFRESH_MARGIN > utcnow():
            return token
        return self._refresh()

    def _refresh(self) -> str:
        integration = self._integration
        refresh_token = (
            decrypt_secret(integration.refresh_token_enc) if integration.refresh_token_enc else None
        )
        if not refresh_token:
            self.reject("Google did not grant offline access. Please reconnect.")
        try:
            tokens = google_oauth.refresh_access_token(refresh_token)
        except google_oauth.OAuthGrantRevoked:
            self.reject("Google access was revoked or has expired. Please reconnect.")
        integration.access_token_enc = encrypt_secret(tokens["access_token"])
        integration.token_expires_at = utcnow() + timedelta(seconds=int(tokens.get("expires_in", 3600)))
        self._db.commit()
        return tokens["access_token"]

    def reject(self, message: str) -> NoReturn:
        integration = self._integration
        integration.connection_status = ConnectionStatus.NEEDS_RECONNECT
        integration.error_message = message
        record_audit(self._db, integration.user, "integration.needs_reconnect", provider=integration.provider)
        self._db.add(
            Notification(
                user_id=integration.user_id, kind="integration", title=f"Reconnect {integration.provider.capitalize()}",
                body=message, link="/settings?tab=accounts",
                idempotency_key=f"reconnect:{integration.provider}:{utcnow().date().isoformat()}",
            )
        )
        self._db.commit()
        raise ReconnectRequired(message)
