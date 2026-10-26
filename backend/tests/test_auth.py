from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.api.auth import OAUTH_COOKIE
from app.api.deps import SESSION_COOKIE
from app.core.security import decode_signed_token, decrypt_secret, encrypt_secret
from app.db import session as db_session
from app.models import Integration
from app.services import google_oauth
from tests.conftest import login_as, make_user


def test_secrets_round_trip_and_are_not_plaintext():
    encrypted = encrypt_secret("ya29.token")
    assert "ya29" not in encrypted
    assert decrypt_secret(encrypted) == "ya29.token"
    assert decrypt_secret("tampered") is None


def test_protected_routes_require_session(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/integrations").status_code == 401
    client.cookies.set(SESSION_COOKIE, "forged")
    assert client.get("/api/auth/me").status_code == 401


def test_login_start_uses_pkce_and_state(client):
    response = client.get("/api/auth/google/start", follow_redirects=False)
    assert response.status_code == 307
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["scope"] == ["openid email profile"]
    flow = decode_signed_token(response.cookies[OAUTH_COOKIE])
    assert flow["state"] == params["state"][0]


def test_integration_oauth_requires_login(client):
    response = client.get("/api/auth/google/start?purpose=gmail", follow_redirects=False)
    assert response.status_code == 401


def test_callback_rejects_mismatched_state(client):
    client.get("/api/auth/google/start", follow_redirects=False)
    response = client.get("/api/auth/google/callback?code=x&state=wrong", follow_redirects=False)
    assert "error=oauth_failed" in response.headers["location"]


def test_login_callback_creates_user_and_session(client, monkeypatch):
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code, verifier: {"access_token": "at"})
    monkeypatch.setattr(
        google_oauth, "fetch_userinfo", lambda token: {"sub": "123", "email": "me@example.com"}
    )
    start = client.get("/api/auth/google/start", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    client.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert client.get("/api/auth/me").json()["email"] == "me@example.com"


def test_gmail_callback_stores_encrypted_tokens(client, monkeypatch, fake_gmail):
    user = make_user("me@example.com", "123")
    login_as(client, user)
    granted = " ".join(google_oauth.PURPOSES["gmail"].scopes)
    monkeypatch.setattr(
        google_oauth,
        "exchange_code",
        lambda code, verifier: {"access_token": "at", "refresh_token": "rt", "scope": granted},
    )
    monkeypatch.setattr(google_oauth, "fetch_userinfo", lambda token: {"sub": "123"})
    start = client.get("/api/auth/google/start?purpose=gmail", follow_redirects=False)
    params = parse_qs(urlparse(start.headers["location"]).query)
    assert params["access_type"] == ["offline"]
    client.get(f"/api/auth/google/callback?code=c&state={params['state'][0]}", follow_redirects=False)

    gmail = next(i for i in client.get("/api/integrations").json() if i["provider"] == "gmail")
    assert gmail["connected"] is True
    assert not any("token" in key for key in gmail)

    with db_session.SessionLocal() as db:
        stored = db.scalar(select(Integration).where(Integration.user_id == user.id))
    assert stored.refresh_token_enc != "rt"
    assert decrypt_secret(stored.refresh_token_enc) == "rt"


def test_integration_callback_rejects_different_google_account(client, monkeypatch):
    login_as(client, make_user("me@example.com", "123"))
    monkeypatch.setattr(google_oauth, "exchange_code", lambda code, verifier: {"access_token": "at"})
    monkeypatch.setattr(google_oauth, "fetch_userinfo", lambda token: {"sub": "someone-else"})
    start = client.get("/api/auth/google/start?purpose=gmail", follow_redirects=False)
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    response = client.get(f"/api/auth/google/callback?code=c&state={state}", follow_redirects=False)
    assert "error=account_mismatch" in response.headers["location"]
