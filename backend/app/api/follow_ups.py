import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import utcnow
from app.db.session import get_db
from app.models import EmailMessage, FollowUpStatus, FollowUpTask, Opportunity, User
from app.schemas.reminders import FollowUpCreate, FollowUpOut, FollowUpUpdate, SnoozeRequest

router = APIRouter(prefix="/follow-ups", tags=["follow-ups"])


@router.get("", response_model=list[FollowUpOut])
def list_follow_ups(
    status: Literal["open", "done", "all"] = "open",
    kind: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FollowUpOut]:
    query = select(FollowUpTask).where(FollowUpTask.user_id == user.id, FollowUpTask.status != FollowUpStatus.CANCELLED)
    if status != "all":
        query = query.where(FollowUpTask.status == status)
    if kind:
        query = query.where(FollowUpTask.kind == kind)
    order = FollowUpTask.due_at if status == "open" else FollowUpTask.due_at.desc()
    return [_out(db, task) for task in db.scalars(query.order_by(order).limit(300))]


@router.post("", response_model=FollowUpOut, status_code=201)
def create_follow_up(body: FollowUpCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FollowUpOut:
    for model, record_id in ((Opportunity, body.opportunity_id), (EmailMessage, body.email_id)):
        record = db.get(model, record_id) if record_id else None
        if record_id and (record is None or record.user_id != user.id):
            raise HTTPException(404, f"{model.__name__} not found")
    task = FollowUpTask(
        user_id=user.id, title=body.title.strip(), notes=body.notes.strip(), due_at=body.due_at,
        opportunity_id=body.opportunity_id, email_message_id=body.email_id, source="manual",
    )
    db.add(task)
    db.commit()
    return _out(db, task)


@router.patch("/{task_id}", response_model=FollowUpOut)
def update_follow_up(task_id: uuid.UUID, body: FollowUpUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    task = _owned(db, user, task_id)
    if body.title is not None:
        task.title = body.title.strip()
    if body.notes is not None:
        task.notes = body.notes.strip()
    if body.due_at is not None:
        task.due_at, task.notified_at, task.snoozed_until = body.due_at, None, None
    db.commit()
    return _out(db, task)


@router.post("/{task_id}/complete", response_model=FollowUpOut)
def complete(task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FollowUpOut:
    task = _owned(db, user, task_id)
    task.status, task.completed_at = FollowUpStatus.DONE, utcnow()
    db.commit()
    return _out(db, task)


@router.post("/{task_id}/reopen", response_model=FollowUpOut)
def reopen(task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FollowUpOut:
    task = _owned(db, user, task_id)
    task.status, task.completed_at = FollowUpStatus.OPEN, None
    db.commit()
    return _out(db, task)


@router.post("/{task_id}/snooze", response_model=FollowUpOut)
def snooze(task_id: uuid.UUID, body: SnoozeRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.until <= utcnow():
        raise HTTPException(422, "Snooze until a time in the future.")
    task = _owned(db, user, task_id)
    task.snoozed_until, task.due_at, task.notified_at = body.until, body.until, None
    db.commit()
    return _out(db, task)


@router.delete("/{task_id}", status_code=204)
def cancel(task_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    _owned(db, user, task_id).status = FollowUpStatus.CANCELLED
    db.commit()


def _owned(db: Session, user: User, task_id: uuid.UUID) -> FollowUpTask:
    task = db.get(FollowUpTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(404, "Reminder not found")
    return task


def _out(db: Session, task: FollowUpTask) -> FollowUpOut:
    context = None
    if task.opportunity_id:
        opportunity = db.get(Opportunity, task.opportunity_id)
        context = f"{opportunity.job_title}" + (f" at {opportunity.company_name}" if opportunity.company_name else "") if opportunity else None
    elif task.email_message_id:
        email = db.get(EmailMessage, task.email_message_id)
        context = email.subject if email else None
    return FollowUpOut.model_validate(task).model_copy(
        update={"overdue": task.status == FollowUpStatus.OPEN and task.due_at < utcnow(), "context": context}
    )
