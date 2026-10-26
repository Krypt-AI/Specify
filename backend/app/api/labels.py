import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import ConnectionStatus, EmailMessage, Label, LabelOrigin, User
from app.schemas.label import LabelCreate, LabelOut, LabelUpdate
from app.services import labels as label_service
from app.services.gmail import client as gmail_client
from app.services.gmail.client import GmailError
from app.services.google_credentials import ReconnectRequired, get_integration

router = APIRouter(prefix="/labels", tags=["labels"])


@router.get("", response_model=list[LabelOut])
def list_labels(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[LabelOut]:
    counts = dict(
        db.execute(
            select(EmailMessage.label_id, func.count())
            .where(EmailMessage.user_id == user.id, EmailMessage.label_id.is_not(None))
            .group_by(EmailMessage.label_id)
        ).all()
    )
    labels = db.scalars(select(Label).where(Label.user_id == user.id).order_by(Label.system_key.is_not(None), Label.name))
    return [
        LabelOut.model_validate(label).model_copy(update={"email_count": counts.get(label.id, 0)})
        for label in labels
    ]


@router.post("", response_model=LabelOut, status_code=201)
def create_label(body: LabelCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Label:
    try:
        name = label_service.clean_label_name(body.name)
    except label_service.LabelNameError as exc:
        raise HTTPException(422, str(exc)) from exc
    existing = label_service.find_similar(label_service.context_labels(db, user.id, include_disabled=True), name)
    if existing:
        raise HTTPException(409, f'A similar label already exists: "{existing.name}".')
    label = label_service.resolve_label(db, user.id, name, body.description, created_by=LabelOrigin.USER)
    db.commit()
    return label


@router.patch("/{label_id}", response_model=LabelOut)
def update_label(
    label_id: uuid.UUID, body: LabelUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Label:
    label = db.get(Label, label_id)
    if label is None or label.user_id != user.id:
        raise HTTPException(404, "Label not found")
    if body.name is not None and body.name != label.name:
        _rename(db, user, label, body.name)
    if body.description is not None:
        label.description = body.description.strip()
    if body.enabled is not None:
        label.enabled = body.enabled
    db.commit()
    return label


def _rename(db: Session, user: User, label: Label, new_name: str) -> None:
    """Rename locally and in Gmail. Specify created this Gmail label, so renaming it is safe."""
    try:
        name = label_service.clean_label_name(new_name)
    except label_service.LabelNameError as exc:
        raise HTTPException(422, str(exc)) from exc
    others = [other for other in label_service.context_labels(db, user.id, include_disabled=True) if other.id != label.id]
    if label_service.normalize_label_name(name) in {other.normalized_name for other in others}:
        raise HTTPException(409, "Another label already has this name.")

    label.name = name
    if not label.system_key:
        label.normalized_name = label_service.normalize_label_name(name)
    if not label.gmail_label_id:
        return
    integration = get_integration(db, user.id, "gmail")
    if integration is None or integration.connection_status != ConnectionStatus.CONNECTED:
        label.gmail_label_id = None  # a label with the new name is created on next use
        return
    try:
        with gmail_client.gmail_client_for(db, integration) as gmail:
            gmail.rename_label(label.gmail_label_id, label.gmail_name)
    except (GmailError, ReconnectRequired) as exc:
        db.rollback()
        raise HTTPException(502, f"Could not rename the label in Gmail: {exc}") from exc
