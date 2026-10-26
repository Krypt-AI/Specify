"""Google OAuth 2.0 (authorization code + PKCE) with incremental, per-feature scopes."""
import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.core.config import get_settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"


@dataclass(frozen=True)
class OAuthPurpose:
    key: str
    scopes: tuple[str, ...]
    explanation: str


# Each purpose requests only what its feature needs; the UI shows users why.
PURPOSES: dict[str, OAuthPurpose] = {
    "login": OAuthPurpose(
        "login",
        ("openid", "email", "profile"),
        "Identify you and create your Specify account.",
    ),
    "gmail": OAuthPurpose(
        "gmail",
        # gmail.modify is the narrowest scope that can apply labels to messages; it also covers
        # reading and drafts. It cannot permanently delete mail.
        ("https://www.googleapis.com/auth/gmail.modify",),
        "Read messages to classify them, apply Specify labels, and create reply drafts. "
        "Specify never sends email without your approval.",
    ),
    "sheets": OAuthPurpose(
        "sheets",
        ("https://www.googleapis.com/auth/spreadsheets",),
        "Create and update the recruitment tracking spreadsheet you select.",
    ),
}


class OAuthError(Exception):
    pass


class OAuthGrantRevoked(OAuthError):
    """The refresh token was revoked or expired; the user must authorize again."""


def new_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    return verifier, challenge.decode()


def build_authorization_url(
    purpose: OAuthPurpose, state: str, code_challenge: str, login_hint: str | None
) -> str:
    settings = get_settings()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(purpose.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "include_granted_scopes": "true",
    }
    if purpose.key != "login":
        # Offline access yields a refresh token for background sync.
        params["access_type"] = "offline"
        params["prompt"] = "consent"
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str, code_verifier: str) -> dict:
    settings = get_settings()
    response = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        },
        timeout=15,
    )
    if response.status_code != 200:
        raise OAuthError("Google rejected the authorization code.")
    return response.json()


def refresh_access_token(refresh_token: str) -> dict:
    settings = get_settings()
    response = httpx.post(
        TOKEN_URL,
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    if response.status_code == 400 and response.json().get("error") == "invalid_grant":
        raise OAuthGrantRevoked("Google access was revoked or has expired.")
    if response.status_code != 200:
        raise OAuthError("Could not refresh the Google access token.")
    return response.json()


def fetch_userinfo(access_token: str) -> dict:
    response = httpx.get(
        USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}, timeout=15
    )
    if response.status_code != 200:
        raise OAuthError("Could not read the Google profile.")
    return response.json()


def revoke_token(token: str) -> None:
    """Best-effort revocation; failure must not block local disconnection."""
    try:
        httpx.post(REVOKE_URL, data={"token": token}, timeout=10)
    except httpx.HTTPError:
        pass
