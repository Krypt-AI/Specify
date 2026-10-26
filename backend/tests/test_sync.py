from datetime import timedelta

from sqlalchemy import func, select

from app.db.base import utcnow
from app.models import EmailMessage, GmailSyncState, Integration, ProcessingStatus, SyncStatus
from app.services.gmail.sync import due_mailbox_user_ids, sync_mailbox
from app.services.google_credentials import ReconnectRequired
from tests.fakes import gmail_message


def _email_count(db) -> int:
    return db.scalar(select(func.count()).select_from(EmailMessage))


def test_initial_sync_stores_incoming_messages_once(db, user, gmail_integration, fake_gmail):
    fake_gmail.deliver(gmail_message("a"))
    fake_gmail.deliver(gmail_message("b", labels=("SENT",)))
    fake_gmail.deliver(gmail_message("c", labels=("INBOX",)))

    outcome = sync_mailbox(db, user.id, fake_gmail)

    assert outcome.status == "completed"
    assert len(outcome.new_email_ids) == 2
    stored = db.scalars(select(EmailMessage).order_by(EmailMessage.gmail_message_id)).all()
    assert [e.gmail_message_id for e in stored] == ["a", "c"]
    assert stored[0].is_unread and not stored[1].is_unread
    assert stored[0].processing_status == ProcessingStatus.PENDING
    assert stored[0].gmail_thread_url.endswith("#all/thread-a")

    state = db.scalar(select(GmailSyncState))
    assert state.history_id == str(fake_gmail.history_id)
    assert state.status == SyncStatus.IDLE
    assert db.get(Integration, gmail_integration.id).last_sync_at is not None

    assert sync_mailbox(db, user.id, fake_gmail).new_email_ids == []
    assert _email_count(db) == 2


def test_incremental_sync_adds_new_mail_and_tracks_read_state(db, user, gmail_integration, fake_gmail):
    fake_gmail.deliver(gmail_message("a"))
    sync_mailbox(db, user.id, fake_gmail)

    fake_gmail.deliver(gmail_message("b"))
    fake_gmail.mark_read("a")
    outcome = sync_mailbox(db, user.id, fake_gmail)

    assert len(outcome.new_email_ids) == 1
    first = db.scalar(select(EmailMessage).where(EmailMessage.gmail_message_id == "a"))
    db.refresh(first)
    assert first.is_unread is False


def test_expired_history_triggers_full_resync_without_duplicates(db, user, gmail_integration, fake_gmail):
    fake_gmail.deliver(gmail_message("a"))
    sync_mailbox(db, user.id, fake_gmail)

    fake_gmail.deliver(gmail_message("b"))
    fake_gmail.history_expired = True
    outcome = sync_mailbox(db, user.id, fake_gmail)

    assert outcome.status == "completed"
    assert _email_count(db) == 2


def test_running_sync_holds_a_lease(db, user, gmail_integration, fake_gmail):
    sync_mailbox(db, user.id, fake_gmail)
    state = db.scalar(select(GmailSyncState))
    state.status = SyncStatus.RUNNING
    state.lease_expires_at = utcnow() + timedelta(minutes=5)
    db.commit()

    assert sync_mailbox(db, user.id, fake_gmail).status == "skipped"

    state.lease_expires_at = utcnow() - timedelta(minutes=1)  # a crashed worker's lease expires
    db.commit()
    assert sync_mailbox(db, user.id, fake_gmail).status == "completed"


def test_reconnect_required_is_recorded(db, user, gmail_integration, fake_gmail, monkeypatch):
    def revoked():
        raise ReconnectRequired("Please reconnect Gmail.")

    monkeypatch.setattr(fake_gmail, "get_profile", revoked)
    outcome = sync_mailbox(db, user.id, fake_gmail)

    assert outcome.status == "reconnect_required"
    state = db.scalar(select(GmailSyncState))
    assert state.status == SyncStatus.ERROR
    assert state.last_error == "Please reconnect Gmail."


def test_skips_users_without_gmail(db, user, fake_gmail):
    assert sync_mailbox(db, user.id, fake_gmail).status == "skipped"


def test_due_mailboxes_respect_poll_interval(db, user, gmail_integration):
    assert due_mailbox_user_ids(db) == [user.id]
    integration = db.get(Integration, gmail_integration.id)
    integration.last_sync_at = utcnow()
    db.commit()
    assert due_mailbox_user_ids(db) == []
