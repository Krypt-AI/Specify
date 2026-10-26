from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import EmailMessage, ProcessingStatus, RunStatus, User, WorkflowRun
from app.schemas.preferences import UserPreferences, deep_merge
from app.schemas.user import PreferencesUpdate, UserOut
from app.services.audit import record_audit
from app.services.workflows.engine import resume
from app.tasks import enqueue, process_email_task, run_workflow_task

router = APIRouter(prefix="/settings", tags=["settings"])


@router.put("", response_model=UserOut)
def update_settings(
    body: PreferencesUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    current = UserPreferences.of(user.preferences).model_dump(mode="json")
    try:
        merged = UserPreferences.model_validate(deep_merge(current, body.preferences))
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
    was_paused = UserPreferences.of(user.preferences).automation.paused
    user.preferences = merged.model_dump(mode="json")
    if body.setup_completed is not None:
        user.setup_completed = body.setup_completed
    record_audit(db, user, "settings.updated", sections=sorted(body.preferences))
    db.commit()
    if was_paused and not merged.automation.paused:
        resume_after_global_pause(db, user)
    return user


def resume_after_global_pause(db: Session, user: User) -> None:
    """Continue runs held by the pause and start workflows for emails that arrived meanwhile."""
    waiting = db.scalars(select(WorkflowRun).where(WorkflowRun.user_id == user.id, WorkflowRun.status == RunStatus.WAITING))
    for run in waiting:
        if (run.waiting_for or {}).get("kind") == "paused" and resume(db, run):
            enqueue(run_workflow_task, str(run.id))
    queued = db.scalars(
        select(EmailMessage.id)
        .where(EmailMessage.user_id == user.id, EmailMessage.processing_status == ProcessingStatus.PENDING)
        .limit(500)
    )
    for email_id in queued:
        enqueue(process_email_task, str(email_id))
