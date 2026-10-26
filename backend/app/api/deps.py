import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.security import decode_signed_token
from app.db.session import SESSION_COOKIE, get_db
from app.models import User

__all__ = ["SESSION_COOKIE", "get_current_user"]


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    claims = decode_signed_token(request.cookies.get(SESSION_COOKIE, ""))
    if not claims or claims.get("typ") != "session":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    return user
