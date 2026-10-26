"""Gmail push notifications: watch renewal and verification of Pub/Sub push requests."""
import base64
import json
import time
from datetime import timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api import webhooks
from app.core.config import get_settings
from app.db.base import utcnow
from app.models import GmailSyncState
from app.services.gmail import push
from app.services.gmail.sync import sync_mailbox

TOPIC = "projects/specify-test/topics/gmail"
AUDIENCE = "https://specify.example/api/webhooks/gmail"
PUSHER = "gmail-push@specify-test.iam.gserviceaccount.com"
GOOGLE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def push_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "gmail_pubsub_topic", TOPIC)
    monkeypatch.setattr(settings, "gmail_push_audience", AUDIENCE)
    monkeypatch.setattr(settings, "gmail_push_service_account", PUSHER)
    monkeypatch.setattr(push, "jwks_client", lambda: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=GOOGLE_KEY.public_key())))


@pytest.fixture
def enqueued(monkeypatch) -> list[tuple]:
    calls: list[tuple] = []
    monkeypatch.setattr(webhooks, "enqueue", lambda task, *args, **kw: calls.append((task.name, *args)))
    return calls


def _token(key=GOOGLE_KEY, **overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://accounts.google.com",
        "aud": AUDIENCE,
        "email": PUSHER,
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
        **overrides,
    }
    return jwt.encode(claims, key, algorithm="RS256")


def _push_body(email_address: str = "me@example.com") -> dict:
    data = base64.b64encode(json.dumps({"emailAddress": email_address, "historyId": "12345"}).encode()).decode()
    return {"message": {"data": data, "messageId": "1"}, "subscription": "projects/specify-test/subscriptions/gmail"}


def _post(client, body: dict, token: str | None) -> int:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/api/webhooks/gmail", json=body, headers=headers).status_code


def test_push_is_off_until_configured(client):
    assert _post(client, _push_body(), _token()) == 404


def test_verified_push_starts_a_sync_for_that_mailbox(client, user, gmail_integration, push_configured, enqueued):
    assert _post(client, _push_body("ME@example.com"), _token()) == 204
    assert enqueued == [("app.tasks.sync_mailbox_task", str(user.id))]


@pytest.mark.parametrize(
    "token",
    [
        None,
        "not-a-jwt",
        _token(aud="https://other.example/hook"),
        _token(email="someone-else@example.com"),
        _token(email_verified=False),
        _token(iss="https://evil.example"),
        _token(exp=int(time.time()) - 60),
        _token(key=rsa.generate_private_key(public_exponent=65537, key_size=2048)),
    ],
    ids=["missing", "garbage", "audience", "account", "unverified", "issuer", "expired", "forged"],
)
def test_unverified_pushes_are_rejected(client, user, gmail_integration, push_configured, enqueued, token):
    assert _post(client, _push_body(), token) == 401
    assert enqueued == []


def test_pushes_for_unknown_or_malformed_mailboxes_are_acknowledged_and_ignored(client, user, gmail_integration, push_configured, enqueued):
    assert _post(client, _push_body("stranger@example.com"), _token()) == 204
    assert _post(client, {"message": {"data": "%%%"}}, _token()) == 204
    assert enqueued == []


def test_sync_starts_and_renews_the_watch(db, fake_gmail, user, gmail_integration, push_configured):
    sync_mailbox(db, user.id)
    state = db.query(GmailSyncState).one()
    assert fake_gmail.watched_topics == [TOPIC]
    assert state.watch_expires_at > utcnow() + timedelta(days=6)

    sync_mailbox(db, user.id)
    assert fake_gmail.watched_topics == [TOPIC]  # still valid: not renewed on every sync

    state.watch_expires_at = utcnow() + timedelta(hours=12)
    db.commit()
    sync_mailbox(db, user.id)
    assert fake_gmail.watched_topics == [TOPIC, TOPIC]


def test_sync_without_push_never_watches(db, fake_gmail, user, gmail_integration):
    sync_mailbox(db, user.id)
    assert fake_gmail.watched_topics == []
