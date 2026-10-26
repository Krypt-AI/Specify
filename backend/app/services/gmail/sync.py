"""Initial and incremental Gmail synchronization with a per-mailbox lease and resumable cursor."""
import logging
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal
from urllib.parse import quote

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import (
    ConnectionStatus,
    EmailMessage,
    GmailSyncState,
    Integration,
    ProcessingStatus,
    SyncStatus,
    User,
)
from app.schemas.preferences import SyncPreferences, UserPreferences
from app.services.gmail import client as gmail_client
from app.services.gmail import push
from app.services.gmail.client import GmailApi, GmailError, GmailNotFound, HistoryExpired
from app.services.gmail.parser import ParsedMessage, parse_message
from app.services.google_credentials import ReconnectRequired, get_integration

logger = logging.getLogger(__name__)

LEASE_DURATION = timedelta(minutes=10)
# Outgoing, chat and junk messages are not classified.
EXCLUDED_LABELS = {"SENT", "DRAFT", "CHAT", "SPAM", "TRASH"}


@dataclass
class SyncOutcome:
    status: Literal["completed", "skipped", "reconnect_required"]
    new_email_ids: list[uuid.UUID] = field(default_factory=list)
    detail: str = ""


def sync_mailbox(db: Session, user_id: uuid.UUID, gmail: GmailApi | None = None) -> SyncOutcome:
    integration = get_integration(db, user_id, "gmail")
    if integration is None or integration.connection_status != ConnectionStatus.CONNECTED:
        return SyncOutcome("skipped", detail="Gmail is not connected.")
    state = _get_or_create_state(db, integration)
    if not _acquire_lease(db, state):
        return SyncOutcome("skipped", detail="A sync is already running.")

    try:
        with nullcontext(gmail) if gmail else gmail_client.gmail_client_for(db, integration) as api:
            new_ids = _run(db, integration.user, state, api)
            push.ensure_watch(db, state, api)
    except ReconnectRequired as exc:
        _release(db, state, error=str(exc))
        return SyncOutcome("reconnect_required", detail=str(exc))
    except Exception as exc:
        db.rollback()
        _release(db, state, error=str(exc) if isinstance(exc, GmailError) else "Unexpected sync error.")
        raise
    integration.last_sync_at = utcnow()
    _release(db, state)
    return SyncOutcome("completed", new_ids)


def due_mailbox_user_ids(db: Session) -> list[uuid.UUID]:
    """Users whose poll interval has elapsed since their last successful sync."""
    now = utcnow()
    rows = db.execute(
        select(Integration, User)
        .join(User, Integration.user_id == User.id)
        .where(Integration.provider == "gmail", Integration.connection_status == ConnectionStatus.CONNECTED)
    ).all()
    due = []
    for integration, user in rows:
        interval = timedelta(minutes=UserPreferences.of(user.preferences).sync.poll_interval_minutes)
        if integration.last_sync_at is None or integration.last_sync_at + interval <= now:
            due.append(user.id)
    return due


def _run(db: Session, user: User, state: GmailSyncState, gmail: GmailApi) -> list[uuid.UUID]:
    if state.history_id:
        try:
            return _incremental_sync(db, user, state, gmail)
        except HistoryExpired:
            logger.info("History cursor expired for user %s; running a full resync", user.id)
            state.history_id = None
    return _initial_sync(db, user, state, gmail, UserPreferences.of(user.preferences).sync)


def _initial_sync(
    db: Session, user: User, state: GmailSyncState, gmail: GmailApi, prefs: SyncPreferences
) -> list[uuid.UUID]:
    # Take the cursor first so mail arriving during the listing is picked up incrementally.
    start_history_id = str(gmail.get_profile()["historyId"])
    query = f"-in:sent -in:drafts -in:chats newer_than:{prefs.initial_sync_days}d"
    ids: list[str] = []
    page_token = None
    while len(ids) < prefs.initial_sync_max_messages:
        batch, page_token = gmail.list_message_ids(
            query, page_token, max_results=min(500, prefs.initial_sync_max_messages - len(ids))
        )
        ids.extend(batch)
        if not page_token:
            break
    created = _store_messages(db, user, gmail, ids)
    state.history_id = start_history_id
    state.initial_sync_completed_at = utcnow()
    db.commit()
    return created


def _incremental_sync(db: Session, user: User, state: GmailSyncState, gmail: GmailApi) -> list[uuid.UUID]:
    added: list[str] = []
    label_changes: dict[str, list[str]] = {}
    latest = state.history_id
    page_token = None
    while True:
        data = gmail.list_history(state.history_id, page_token)
        for record in data.get("history", []):
            for item in record.get("messagesAdded", []):
                if not EXCLUDED_LABELS & set(item["message"].get("labelIds", [])):
                    added.append(item["message"]["id"])
            for item in record.get("labelsAdded", []) + record.get("labelsRemoved", []):
                label_changes[item["message"]["id"]] = item["message"].get("labelIds", [])
        latest = str(data.get("historyId", latest))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    _apply_label_changes(db, user.id, label_changes)
    created = _store_messages(db, user, gmail, added)
    state.history_id = latest
    db.commit()
    return created


def _apply_label_changes(db: Session, user_id: uuid.UUID, changes: dict[str, list[str]]) -> None:
    """Keep read/unread state and label ids current for messages already stored."""
    if not changes:
        return
    emails = db.scalars(
        select(EmailMessage).where(
            EmailMessage.user_id == user_id, EmailMessage.gmail_message_id.in_(list(changes))
        )
    )
    for email in emails:
        email.gmail_label_ids = changes[email.gmail_message_id]
        email.is_unread = "UNREAD" in email.gmail_label_ids
    db.commit()


def _store_messages(db: Session, user: User, gmail: GmailApi, message_ids: list[str]) -> list[uuid.UUID]:
    unique_ids = list(dict.fromkeys(message_ids))
    if not unique_ids:
        return []
    existing = set(
        db.scalars(
            select(EmailMessage.gmail_message_id).where(
                EmailMessage.user_id == user.id, EmailMessage.gmail_message_id.in_(unique_ids)
            )
        )
    )
    created = []
    for message_id in unique_ids:
        if message_id in existing:
            continue
        try:
            raw = gmail.get_message(message_id)
        except GmailNotFound:
            continue  # deleted between listing and fetching
        try:
            parsed = parse_message(raw)
        except (KeyError, ValueError):
            logger.exception("Skipping malformed Gmail message %s", message_id)
            continue
        if EXCLUDED_LABELS & set(parsed.label_ids):
            continue
        email = _to_model(user, parsed)
        db.add(email)
        try:
            db.commit()  # per message, so progress survives a crash mid-sync
        except IntegrityError:
            db.rollback()  # stored concurrently by another worker
            continue
        created.append(email.id)
    return created


def _to_model(user: User, parsed: ParsedMessage) -> EmailMessage:
    return EmailMessage(
        user_id=user.id,
        gmail_message_id=parsed.gmail_message_id,
        gmail_thread_id=parsed.gmail_thread_id,
        gmail_thread_url=f"https://mail.google.com/mail/?authuser={quote(user.email)}#all/{parsed.gmail_thread_id}",
        sender_name=parsed.sender_name,
        sender_email=parsed.sender_email,
        reply_to=parsed.reply_to,
        recipients=parsed.recipients,
        subject=parsed.subject,
        snippet=parsed.snippet,
        body_text=parsed.body_text,
        body_truncated=parsed.body_truncated,
        received_at=parsed.received_at,
        gmail_label_ids=parsed.label_ids,
        is_unread="UNREAD" in parsed.label_ids,
        attachments=parsed.attachments,
        headers=parsed.headers,
        link_domains=parsed.link_domains,
        processing_status=ProcessingStatus.PENDING,
    )


def _get_or_create_state(db: Session, integration: Integration) -> GmailSyncState:
    if integration.sync_state is None:
        integration.sync_state = GmailSyncState()
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            db.refresh(integration)
    return integration.sync_state


def _acquire_lease(db: Session, state: GmailSyncState) -> bool:
    now = utcnow()
    result = db.execute(
        update(GmailSyncState)
        .where(
            GmailSyncState.id == state.id,
            or_(GmailSyncState.status != SyncStatus.RUNNING, GmailSyncState.lease_expires_at < now),
        )
        .values(status=SyncStatus.RUNNING, lease_expires_at=now + LEASE_DURATION, last_attempt_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    db.refresh(state)
    return result.rowcount == 1


def _release(db: Session, state: GmailSyncState, error: str | None = None) -> None:
    state.status = SyncStatus.ERROR if error else SyncStatus.IDLE
    state.lease_expires_at = None
    state.last_error = error
    state.consecutive_failures = state.consecutive_failures + 1 if error else 0
    db.commit()
