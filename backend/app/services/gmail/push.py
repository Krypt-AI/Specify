"""Gmail push notifications through Google Cloud Pub/Sub.

When GMAIL_PUBSUB_TOPIC is set, each mailbox asks Gmail to publish changes to that topic, and a
Pub/Sub push subscription calls POST /api/webhooks/gmail, which starts a sync right away.
Polling keeps running underneath, so a missed or delayed notification only delays a sync.
"""
import base64
import binascii
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import jwt
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.models import GmailSyncState
from app.services.gmail.client import GmailApi, GmailError

logger = logging.getLogger(__name__)

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["https://accounts.google.com", "accounts.google.com"]
# Gmail watches last seven days; renewing a day ahead leaves room for a failed attempt.
RENEW_BEFORE = timedelta(days=1)


class PushRejected(Exception):
    """The request is not a genuine push from our Pub/Sub subscription."""


@dataclass(frozen=True)
class GmailNotification:
    email_address: str
    history_id: str


def push_enabled() -> bool:
    return bool(get_settings().gmail_pubsub_topic)


def ensure_watch(db: Session, state: GmailSyncState, gmail: GmailApi) -> None:
    """Start or renew the mailbox watch when it is missing or about to expire."""
    if not push_enabled():
        return
    if state.watch_expires_at and state.watch_expires_at - utcnow() > RENEW_BEFORE:
        return
    try:
        response = gmail.watch(get_settings().gmail_pubsub_topic)
    except GmailError as exc:
        # Polling still covers the mailbox; the watch is retried on the next sync.
        logger.warning("Could not start Gmail push notifications: %s", exc)
        return
    state.watch_expires_at = datetime.fromtimestamp(int(response["expiration"]) / 1000, tz=timezone.utc)
    db.commit()


@lru_cache
def jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(GOOGLE_CERTS_URL)


def verify_push_request(authorization: str | None) -> None:
    """Check the OIDC token Pub/Sub attaches: signed by Google, for our endpoint and account."""
    settings = get_settings()
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise PushRejected("Missing bearer token")
    try:
        signing_key = jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.gmail_push_audience,
            issuer=GOOGLE_ISSUERS,
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise PushRejected(f"Invalid token: {exc}") from exc
    if claims.get("email") != settings.gmail_push_service_account or claims.get("email_verified") is not True:
        raise PushRejected("Token is not from the configured push service account")


def parse_notification(body: dict) -> GmailNotification:
    """Read {"message": {"data": base64(JSON {"emailAddress", "historyId"})}} from Pub/Sub."""
    try:
        payload = json.loads(base64.b64decode(body["message"]["data"], validate=False))
        return GmailNotification(str(payload["emailAddress"]).lower(), str(payload["historyId"]))
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise ValueError("Not a Gmail notification") from exc
