"""Session tokens and encryption of secrets at rest."""
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

_ALGORITHM = "HS256"


def create_signed_token(claims: dict[str, Any], ttl: timedelta) -> str:
    payload = {**claims, "exp": datetime.now(timezone.utc) + ttl}
    return jwt.encode(payload, get_settings().session_secret, algorithm=_ALGORITHM)


def decode_signed_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, get_settings().session_secret, algorithms=[_ALGORITHM])
    except jwt.PyJWTError:
        return None


def _fernet() -> Fernet:
    return Fernet(get_settings().token_encryption_key.encode())


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str | None:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        return None
