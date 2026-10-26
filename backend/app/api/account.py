from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, get_current_user
from app.db.base import utcnow
from app.db.session import get_db
from app.models import User
from app.services.audit import record_audit
from app.services.privacy import delete_account, export_user_data

router = APIRouter(prefix="/account", tags=["account"])


class DeleteAccountRequest(BaseModel):
    confirm_email: str


@router.get("/export")
def export_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JSONResponse:
    """Download everything Specify stores about the user as one JSON file (never tokens)."""
    record_audit(db, user, "account.exported")
    db.commit()
    filename = f"specify-export-{utcnow():%Y-%m-%d}.json"
    return JSONResponse(export_user_data(db, user), headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.delete("", status_code=204)
def delete_my_account(
    body: DeleteAccountRequest,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Revoke Google access and permanently delete the account and all of its data."""
    if body.confirm_email.strip().lower() != user.email.lower():
        raise HTTPException(400, "Type your account email exactly to confirm.")
    delete_account(db, user)
    response.delete_cookie(SESSION_COOKIE, path="/")
