import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import DraftStatus, DraftTemplate, EmailDraft, EmailMessage, User
from app.schemas.drafts import DraftOut, DraftRequest, DraftUpdate, TemplateOut, TemplateUpdate
from app.services.drafting import service
from app.services.drafting.templates import SCENARIOS, resolve_template
from app.services.google_api import GoogleApiError
from app.tasks import enqueue, generate_draft_task

router = APIRouter(tags=["drafts"])


@router.get("/drafts", response_model=list[DraftOut])
def list_drafts(status: DraftStatus | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(EmailDraft).where(EmailDraft.user_id == user.id)
    query = query.where(EmailDraft.status == status) if status else query.where(EmailDraft.status != DraftStatus.DISCARDED)
    return db.scalars(query.order_by(EmailDraft.updated_at.desc()).limit(200)).unique().all()


@router.get("/drafts/templates", response_model=list[TemplateOut])
def list_templates(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[TemplateOut]:
    return [_template_out(db, user, key) for key in SCENARIOS]


@router.put("/drafts/templates/{scenario}", response_model=TemplateOut)
def save_template(scenario: str, body: TemplateUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if scenario not in SCENARIOS:
        raise HTTPException(404, "Unknown scenario")
    template = db.scalar(select(DraftTemplate).where(DraftTemplate.user_id == user.id, DraftTemplate.scenario == scenario))
    if template is None:
        template = DraftTemplate(user_id=user.id, scenario=scenario)
        db.add(template)
    template.instructions, template.body, template.use_ai = body.instructions.strip(), body.body.strip(), body.use_ai
    db.commit()
    return _template_out(db, user, scenario)


@router.delete("/drafts/templates/{scenario}", status_code=204)
def reset_template(scenario: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    template = db.scalar(select(DraftTemplate).where(DraftTemplate.user_id == user.id, DraftTemplate.scenario == scenario))
    if template:
        db.delete(template)
        db.commit()


@router.get("/drafts/{draft_id}", response_model=DraftOut)
def get_draft(draft_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> EmailDraft:
    return _owned(db, user, draft_id)


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
def edit_draft(draft_id: uuid.UUID, body: DraftUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Save the user's edits and update the Gmail draft."""
    draft = _editable(db, user, draft_id)
    if body.subject is not None:
        draft.subject = body.subject.strip()
    if body.body is not None:
        draft.body = body.body
    draft.edited_by_user = True
    db.commit()
    _save_to_gmail(db, draft)
    return draft


@router.post("/drafts/{draft_id}/regenerate", response_model=DraftOut, status_code=202)
def regenerate(draft_id: uuid.UUID, body: DraftRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    draft = _editable(db, user, draft_id)
    if body.tone:
        draft.tone = body.tone
    draft.instructions = body.instructions.strip()
    draft.status, draft.edited_by_user = DraftStatus.GENERATING, False
    db.commit()
    enqueue(generate_draft_task, str(draft.id))
    db.refresh(draft)
    return draft


@router.post("/drafts/{draft_id}/gmail", response_model=DraftOut)
def save_again(draft_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> EmailDraft:
    """Save a draft to Gmail again after it was sent or deleted there; only on the user's request."""
    draft = _editable(db, user, draft_id)
    _save_to_gmail(db, draft, recreate=True)
    return draft


@router.delete("/drafts/{draft_id}", status_code=204)
def discard(draft_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    service.discard_draft(db, _owned(db, user, draft_id))


@router.post("/emails/{email_id}/drafts", response_model=DraftOut, status_code=202)
def draft_reply(email_id: uuid.UUID, body: DraftRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Draft a reply to any email, such as one from a lecturer or a certification provider."""
    email = db.get(EmailMessage, email_id)
    if email is None or email.user_id != user.id:
        raise HTTPException(404, "Email not found")
    scenario = body.scenario or service.scenario_for_email(email)
    if scenario not in SCENARIOS:
        raise HTTPException(422, "Unknown scenario")
    draft = service.request_draft(
        db, user, email, scenario=scenario, key=f"manual:{email.id}:{uuid.uuid4()}", tone=body.tone, instructions=body.instructions
    )
    enqueue(generate_draft_task, str(draft.id))
    db.refresh(draft)
    return draft


def _owned(db: Session, user: User, draft_id: uuid.UUID) -> EmailDraft:
    draft = db.get(EmailDraft, draft_id)
    if draft is None or draft.user_id != user.id:
        raise HTTPException(404, "Draft not found")
    return draft


def _editable(db: Session, user: User, draft_id: uuid.UUID) -> EmailDraft:
    draft = _owned(db, user, draft_id)
    if draft.status == DraftStatus.DISCARDED:
        raise HTTPException(409, "This draft was discarded.")
    if draft.status == DraftStatus.GENERATING:
        raise HTTPException(409, "This draft is still being written.")
    return draft


def _save_to_gmail(db: Session, draft: EmailDraft, recreate: bool = False) -> None:
    try:
        service.save_to_gmail(db, draft, recreate=recreate)
    except GoogleApiError as exc:
        db.rollback()
        draft.error = f"Saved in Specify, but Gmail could not be updated: {exc}"
        db.commit()
    db.refresh(draft)


def _template_out(db: Session, user: User, scenario: str) -> TemplateOut:
    resolved = resolve_template(db, user.id, scenario)
    return TemplateOut(
        scenario=scenario,
        label=resolved.scenario.label,
        instructions=resolved.instructions,
        body=resolved.body,
        use_ai=resolved.use_ai,
        customized=resolved.customized,
    )
