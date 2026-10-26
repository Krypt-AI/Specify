import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, get_current_user
from app.core.config import get_settings
from app.core.security import create_signed_token, decode_signed_token, encrypt_secret
from app.db.session import get_db, get_system_db
from app.models import ConnectionStatus, Integration, User
from app.schemas.user import UserOut
from app.services import google_oauth
from app.services.audit import record_audit
from app.services.google_oauth import PURPOSES, OAuthError
from app.tasks import enqueue, sync_mailbox_task

router = APIRouter(prefix="/auth", tags=["auth"])

OAUTH_COOKIE = "specify_oauth"
OAUTH_TTL = timedelta(minutes=10)


def _set_cookie(response: Response, key: str, value: str, max_age: int) -> None:
    response.set_cookie(
        key,
        value,
        max_age=max_age,
        httponly=True,
        secure=get_settings().is_production,
        samesite="lax",
        path="/",
    )


def _redirect_to_frontend(path: str, **params: str) -> RedirectResponse:
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{get_settings().frontend_url}{path}{query}")


@router.get("/google/start")
def start_google_oauth(
    request: Request,
    purpose: str = Query("login"),
    db: Session = Depends(get_system_db),
) -> RedirectResponse:
    oauth_purpose = PURPOSES.get(purpose)
    if oauth_purpose is None:
        raise HTTPException(400, "Unknown OAuth purpose")

    login_hint = None
    user_id = None
    if purpose != "login":
        user = get_current_user(request, db)  # integrations require an existing session
        login_hint, user_id = user.email, str(user.id)

    state = secrets.token_urlsafe(32)
    verifier, challenge = google_oauth.new_pkce_pair()
    flow_token = create_signed_token(
        {"typ": "oauth", "state": state, "verifier": verifier, "purpose": purpose, "uid": user_id},
        OAUTH_TTL,
    )
    response = RedirectResponse(
        google_oauth.build_authorization_url(oauth_purpose, state, challenge, login_hint)
    )
    _set_cookie(response, OAUTH_COOKIE, flow_token, int(OAUTH_TTL.total_seconds()))
    return response


@router.get("/google/callback")
def google_oauth_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_system_db),
) -> RedirectResponse:
    flow = decode_signed_token(request.cookies.get(OAUTH_COOKIE, ""))
    if error or not code or not flow or flow.get("typ") != "oauth" or flow.get("state") != state:
        return _redirect_to_frontend("/login", error=error or "oauth_failed")

    purpose = flow["purpose"]
    try:
        tokens = google_oauth.exchange_code(code, flow["verifier"])
        profile = google_oauth.fetch_userinfo(tokens["access_token"])
    except OAuthError:
        return _redirect_to_frontend("/login", error="oauth_failed")

    if purpose == "login":
        user = _upsert_user(db, profile)
        record_audit(db, user, "auth.login")
        db.commit()
        response = _redirect_to_frontend("/")
        session = create_signed_token(
            {"typ": "session", "sub": str(user.id)},
            timedelta(hours=get_settings().session_ttl_hours),
        )
        _set_cookie(response, SESSION_COOKIE, session, get_settings().session_ttl_hours * 3600)
    else:
        user = db.get(User, uuid.UUID(flow["uid"]))
        if user is None or profile.get("sub") != user.google_sub:
            return _redirect_to_frontend("/settings", error="account_mismatch")
        _store_integration(db, user, purpose, tokens)
        record_audit(db, user, "integration.connected", provider=purpose)
        db.commit()
        if purpose == "gmail":
            enqueue(sync_mailbox_task, str(user.id))  # start the initial sync right away
        response = _redirect_to_frontend("/settings", connected=purpose)

    response.delete_cookie(OAUTH_COOKIE, path="/")
    return response


def _upsert_user(db: Session, profile: dict) -> User:
    user = db.scalar(select(User).where(User.google_sub == profile["sub"]))
    if user is None:
        user = User(email=profile["email"], name=profile.get("name", ""), google_sub=profile["sub"])
        db.add(user)
        db.flush()
    else:
        user.email = profile["email"]
        user.name = profile.get("name", user.name)
    return user


def _store_integration(db: Session, user: User, purpose: str, tokens: dict) -> None:
    integration = db.scalar(
        select(Integration).where(Integration.user_id == user.id, Integration.provider == purpose)
    )
    if integration is None:
        integration = Integration(user_id=user.id, provider=purpose)
        db.add(integration)
    integration.connection_status = ConnectionStatus.CONNECTED
    integration.error_message = None
    integration.scopes = tokens.get("scope", "").split()
    integration.access_token_enc = encrypt_secret(tokens["access_token"])
    if tokens.get("refresh_token"):  # only returned on consent; otherwise keep the stored one
        integration.refresh_token_enc = encrypt_secret(tokens["refresh_token"])
    integration.token_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=int(tokens.get("expires_in", 3600))
    )


@router.get("/me", response_model=UserOut)
def read_current_user(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/logout", status_code=204)
def logout(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
