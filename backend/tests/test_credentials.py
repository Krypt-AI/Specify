from datetime import timedelta

import pytest

from app.core.security import decrypt_secret
from app.db.base import utcnow
from app.models import ConnectionStatus, Integration
from app.services import google_oauth
from app.services.google_credentials import IntegrationCredentials, ReconnectRequired


def _credentials(db, integration_id) -> tuple[IntegrationCredentials, Integration]:
    integration = db.get(Integration, integration_id)
    return IntegrationCredentials(db, integration), integration


def test_returns_stored_token_while_valid(db, gmail_integration, monkeypatch):
    monkeypatch.setattr(google_oauth, "refresh_access_token", lambda token: pytest.fail("should not refresh"))
    credentials, _ = _credentials(db, gmail_integration.id)
    assert credentials.access_token() == "access-token"


def test_refreshes_expired_token_and_stores_it_encrypted(db, gmail_integration, monkeypatch):
    monkeypatch.setattr(
        google_oauth, "refresh_access_token", lambda token: {"access_token": "fresh", "expires_in": 3600}
    )
    credentials, integration = _credentials(db, gmail_integration.id)
    integration.token_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()

    assert credentials.access_token() == "fresh"
    assert integration.access_token_enc != "fresh"
    assert decrypt_secret(integration.access_token_enc) == "fresh"
    assert integration.token_expires_at > utcnow()


def test_revoked_grant_marks_integration_for_reconnection(db, gmail_integration, monkeypatch):
    def revoked(token):
        raise google_oauth.OAuthGrantRevoked("revoked")

    monkeypatch.setattr(google_oauth, "refresh_access_token", revoked)
    credentials, integration = _credentials(db, gmail_integration.id)

    with pytest.raises(ReconnectRequired):
        credentials.access_token(force_refresh=True)
    assert integration.connection_status == ConnectionStatus.NEEDS_RECONNECT
    assert "reconnect" in integration.error_message.lower()


def test_missing_scope_requires_reconnection(db, gmail_integration):
    credentials, integration = _credentials(db, gmail_integration.id)
    integration.scopes = ["https://www.googleapis.com/auth/gmail.readonly"]
    db.commit()

    with pytest.raises(ReconnectRequired):
        credentials.access_token()
    assert integration.connection_status == ConnectionStatus.NEEDS_RECONNECT
