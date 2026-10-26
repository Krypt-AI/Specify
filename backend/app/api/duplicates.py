import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Company, DuplicateCandidate, Opportunity, User
from app.schemas.recruitment import DuplicateOut
from app.services.audit import record_audit
from app.services.recruitment import records
from app.tasks import schedule_sheets_sync

router = APIRouter(prefix="/duplicates", tags=["duplicates"])

MODELS = {"company": Company, "opportunity": Opportunity}


@router.get("", response_model=list[DuplicateOut])
def list_duplicates(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[DuplicateOut]:
    pending = db.scalars(
        select(DuplicateCandidate)
        .where(DuplicateCandidate.user_id == user.id, DuplicateCandidate.status == "pending")
        .order_by(DuplicateCandidate.created_at.desc())
    ).all()
    return [_with_names(db, candidate) for candidate in pending]


@router.post("/{candidate_id}/merge", status_code=204)
def merge(candidate_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    """Merge the newer record into the existing one. Only ever done on the user's request."""
    candidate = _owned_pending(db, user, candidate_id)
    model = MODELS[candidate.entity_type]
    source, target = db.get(model, candidate.record_id), db.get(model, candidate.candidate_id)
    if source is None or target is None:
        candidate.status = "dismissed"
        db.commit()
        raise HTTPException(410, "One of these records no longer exists.")
    candidate.status = "merged"
    db.flush()
    if candidate.entity_type == "company":
        records.merge_companies(db, source, target)
    else:
        records.merge_opportunities(db, source, target)
    record_audit(
        db,
        user,
        f"{candidate.entity_type}.merged",
        source=str(source.id),
        target=str(target.id),
        summary=f"Merged into {_display_name(target)}",
    )
    db.commit()
    schedule_sheets_sync(db, user.id)


@router.post("/{candidate_id}/dismiss", status_code=204)
def dismiss(candidate_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    _owned_pending(db, user, candidate_id).status = "dismissed"
    db.commit()


def _owned_pending(db: Session, user: User, candidate_id: uuid.UUID) -> DuplicateCandidate:
    candidate = db.get(DuplicateCandidate, candidate_id)
    if candidate is None or candidate.user_id != user.id or candidate.status != "pending":
        raise HTTPException(404, "Duplicate suggestion not found")
    return candidate


def _with_names(db: Session, candidate: DuplicateCandidate) -> DuplicateOut:
    model = MODELS[candidate.entity_type]
    name = lambda record_id: _display_name(db.get(model, record_id))  # noqa: E731
    return DuplicateOut.model_validate(candidate).model_copy(
        update={"record_name": name(candidate.record_id), "candidate_name": name(candidate.candidate_id)}
    )


def _display_name(record: Company | Opportunity | None) -> str:
    if record is None:
        return "(deleted)"
    if isinstance(record, Company):
        return record.name
    return f"{record.job_title} at {record.company_name}" if record.company_name else record.job_title
