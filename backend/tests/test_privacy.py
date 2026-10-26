"""Retention, data export and account deletion."""
from datetime import timedelta

from sqlalchemy import func, select

from app.db.base import utcnow
from app.models import AuditLog, EmailMessage, Integration, Notification, User
from app.services import google_oauth
from app.services.gmail.sync import sync_mailbox
from app.services.privacy import purge_expired_data
from tests.conftest import connect_gmail, login_as, make_user
from tests.fakes import gmail_message


def _sync(db, fake_gmail, user, *messages: dict) -> list[EmailMessage]:
    for message in messages:
        fake_gmail.deliver(message)
    sync_mailbox(db, user.id)
    return list(db.scalars(select(EmailMessage).where(EmailMessage.user_id == user.id)))


def _age(db, email: EmailMessage, days: int) -> None:
    email.received_at = utcnow() - timedelta(days=days)
    db.commit()


def test_retention_removes_old_bodies_but_keeps_the_email(db, fake_gmail, user, gmail_integration):
    old, recent = _sync(db, fake_gmail, user, gmail_message(body="Old offer details"), gmail_message(body="New offer"))
    _age(db, old, 400)
    _age(db, recent, 1)

    assert purge_expired_data(db)["email_bodies"] == 1
    db.refresh(old)
    db.refresh(recent)
    assert old.body_text == "" and old.body_purged_at is not None
    assert old.subject and old.gmail_thread_url  # still listed, and still opens in Gmail
    assert recent.body_text == "New offer"
    assert purge_expired_data(db)["email_bodies"] == 0  # idempotent


def test_retention_zero_keeps_bodies_forever(db, client, fake_gmail, user, gmail_integration):
    login_as(client, user)
    client.put("/api/settings", json={"preferences": {"privacy": {"email_body_retention_days": 0}}})
    (email,) = _sync(db, fake_gmail, user, gmail_message(body="Keep me"))
    _age(db, email, 3000)

    assert purge_expired_data(db)["email_bodies"] == 0


def test_old_read_notifications_are_cleared(db, user):
    now = utcnow()
    db.add_all([
        Notification(user_id=user.id, kind="info", title="old read", body="", read_at=now - timedelta(days=120)),
        Notification(user_id=user.id, kind="info", title="old unread", body=""),
        Notification(user_id=user.id, kind="info", title="recent read", body="", read_at=now - timedelta(days=5)),
    ])
    db.commit()

    assert purge_expired_data(db)["notifications"] == 1
    assert sorted(db.scalars(select(Notification.title))) == ["old unread", "recent read"]


def test_export_contains_the_users_data_and_never_tokens(db, client, fake_gmail, user, gmail_integration):
    _sync(db, fake_gmail, user, gmail_message(subject="Offer from Grab"))
    other = make_user("other@example.com", "sub-other")
    connect_gmail(other)
    login_as(client, user)

    response = client.get("/api/account/export")

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith('attachment; filename="specify-export-')
    data = response.json()
    assert data["account"]["email"] == user.email
    assert [e["subject"] for e in data["emails"]] == ["Offer from Grab"]
    assert [i["provider"] for i in data["integrations"]] == ["gmail"]
    stored = db.scalar(select(Integration).where(Integration.user_id == user.id))
    assert "token_enc" not in response.text and stored.refresh_token_enc not in response.text
    assert "other@example.com" not in response.text


def test_delete_account_requires_typing_the_email(client, user):
    login_as(client, user)
    response = client.request("DELETE", "/api/account", json={"confirm_email": "wrong@example.com"})
    assert response.status_code == 400


def test_delete_account_revokes_access_and_removes_everything(db, client, fake_gmail, user, gmail_integration, monkeypatch):
    revoked: list[str] = []
    monkeypatch.setattr(google_oauth, "revoke_token", revoked.append)
    _sync(db, fake_gmail, user, gmail_message())
    other = make_user("other@example.com", "sub-other")
    login_as(client, user)
    client.put("/api/settings", json={"preferences": {"draft_tone": "formal"}})  # leaves an audit entry

    response = client.request("DELETE", "/api/account", json={"confirm_email": " ME@example.com "})

    assert response.status_code == 204
    assert revoked == ["refresh-token"]
    assert 'specify_session=""' in response.headers["set-cookie"]
    db.expire_all()
    assert db.scalars(select(User.email)).all() == [other.email]
    assert db.scalar(select(func.count()).select_from(EmailMessage)) == 0
    assert db.scalar(select(func.count()).select_from(Integration)) == 0
    assert db.scalar(select(func.count()).select_from(AuditLog)) == 0
    assert client.get("/api/auth/me").status_code == 401
