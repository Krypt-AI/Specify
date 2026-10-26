import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (
    Company,
    CompanyType,
    DuplicateCandidate,
    EmailMessage,
    Opportunity,
    OpportunityDecision,
    OpportunityStatus,
    User,
)
from app.schemas.preferences import UserPreferences
from app.schemas.recruitment import (
    DecisionCreate,
    DuplicateOut,
    OpportunityCreate,
    OpportunityDetail,
    OpportunityPage,
    OpportunityStats,
    OpportunityUpdate,
    Recommendation,
)
from app.services.drafting.service import draft_for_decision
from app.services.email_domains import business_domain
from app.services.recruitment import decisions, records
from app.services.recruitment.decisions import ConfirmationRequired
from app.services.recruitment.insights import fallback_recommendation, missing_information, preference_flags
from app.services.workflows.engine import resume_for_decision
from app.tasks import enqueue, generate_draft_task, run_workflow_task, schedule_sheets_sync

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=OpportunityPage)
def list_opportunities(
    status: OpportunityStatus | None = None,
    queue: bool = False,
    company_id: uuid.UUID | None = None,
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OpportunityPage:
    query = select(Opportunity).where(Opportunity.user_id == user.id)
    if queue:
        query = query.where(decisions.in_decision_queue())
    if status:
        query = query.where(Opportunity.status == status)
    if company_id:
        query = query.where(Opportunity.company_id == company_id)
    if q:
        pattern = f"%{q.strip().lower()}%"
        query = query.outerjoin(Company, Opportunity.company_id == Company.id).where(
            or_(func.lower(Opportunity.job_title).like(pattern), func.lower(Company.name).like(pattern))
        )
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(
        query.order_by(Opportunity.date_received.desc()).offset((page - 1) * page_size).limit(page_size)
    ).unique().all()
    return OpportunityPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=OpportunityStats)
def opportunity_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> OpportunityStats:
    by_status = dict(
        db.execute(
            select(Opportunity.status, func.count()).where(Opportunity.user_id == user.id).group_by(Opportunity.status)
        ).all()
    )
    queue = db.scalar(
        select(func.count()).select_from(Opportunity).where(Opportunity.user_id == user.id, decisions.in_decision_queue())
    )
    duplicates = db.scalar(
        select(func.count())
        .select_from(DuplicateCandidate)
        .where(DuplicateCandidate.user_id == user.id, DuplicateCandidate.status == "pending")
    )
    return OpportunityStats(
        decision_queue=queue,
        active=sum(count for status, count in by_status.items() if status not in records.CLOSED_STATUSES),
        interviews_scheduled=by_status.get(OpportunityStatus.INTERVIEW_SCHEDULED, 0),
        offers_received=by_status.get(OpportunityStatus.OFFER_RECEIVED, 0),
        pending_duplicates=duplicates,
        by_status=by_status,
    )


@router.get("/{opportunity_id}", response_model=OpportunityDetail)
def get_opportunity(
    opportunity_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> OpportunityDetail:
    return opportunity_detail(db, user, owned_opportunity(db, user, opportunity_id))


@router.post("", response_model=OpportunityDetail, status_code=201)
def create_opportunity(
    body: OpportunityCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> OpportunityDetail:
    email = None
    if body.from_email_id:
        email = db.get(EmailMessage, body.from_email_id)
        if email is None or email.user_id != user.id:
            raise HTTPException(404, "Email not found")
    seen_at = email.received_at if email else utcnow()

    company = None
    if body.company_id:
        company = db.get(Company, body.company_id)
        if company is None or company.user_id != user.id:
            raise HTTPException(404, "Company not found")
    elif body.company_name:
        domain = business_domain(email.sender_email) if email else None
        company = records.upsert_company(
            db, user.id, records.CompanyData(name=body.company_name, domain=domain, company_type=CompanyType.EMPLOYER), seen_at
        )
    recruiter = (
        records.upsert_contact(db, user.id, email.sender_email, name=email.sender_name, phone=None, role=None, company=company)
        if email
        else None
    )
    opportunity = Opportunity(
        user_id=user.id,
        company=company,
        recruiter=recruiter,
        job_title=body.job_title.strip(),
        date_received=seen_at,
        application_source="email" if email else "manual",
        gmail_thread_id=email.gmail_thread_id if email else None,
        gmail_thread_url=email.gmail_thread_url if email else None,
        last_contact_at=seen_at if email else None,
        status=OpportunityStatus.NEW,
    )
    _apply_fields(opportunity, body.model_dump(exclude_unset=True, exclude={"job_title", "company_id", "company_name", "from_email_id"}))
    records.add_opportunity(db, opportunity)
    if email:
        email.opportunity_id = opportunity.id
        email.recruitment_processed_at = utcnow()
        email.recruitment_note = "Opportunity created by you."
    db.commit()
    schedule_sheets_sync(db, user.id)
    return opportunity_detail(db, user, opportunity)


@router.patch("/{opportunity_id}", response_model=OpportunityDetail)
def update_opportunity(
    opportunity_id: uuid.UUID,
    body: OpportunityUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OpportunityDetail:
    opportunity = owned_opportunity(db, user, opportunity_id)
    changes = body.model_dump(exclude_unset=True, exclude={"status", "confirm"})
    if "company_id" in changes and changes["company_id"] is not None:
        company = db.get(Company, changes["company_id"])
        if company is None or company.user_id != user.id:
            raise HTTPException(404, "Company not found")
    if body.status is not None:
        try:
            decisions.change_status(db, user, opportunity, body.status, confirmed=body.confirm)
        except ConfirmationRequired as exc:
            raise HTTPException(409, str(exc)) from exc
    if "job_title" in changes:
        opportunity.job_title = changes.pop("job_title").strip()
        opportunity.normalized_title = records.normalize_title(opportunity.job_title)
    _apply_fields(opportunity, changes)
    db.commit()
    schedule_sheets_sync(db, user.id)
    return opportunity_detail(db, user, opportunity)


@router.post("/{opportunity_id}/decision", response_model=OpportunityDetail)
def decide(
    opportunity_id: uuid.UUID,
    body: DecisionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OpportunityDetail:
    """Record the user's decision and prepare the reply it calls for as a Gmail draft (never sent)."""
    opportunity = owned_opportunity(db, user, opportunity_id)
    if body.email_id:
        email = db.get(EmailMessage, body.email_id)
        if email is None or email.user_id != user.id:
            raise HTTPException(404, "Email not found")
    try:
        entry = decisions.record_decision(
            db,
            user,
            opportunity,
            body.decision,
            notes=body.notes,
            custom_decision=body.custom_decision,
            email_id=body.email_id,
            confirmed=body.confirm,
        )
    except ConfirmationRequired as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.commit()
    resumed = resume_for_decision(db, user.id, opportunity.id, entry.id)
    for run_id in resumed:
        enqueue(run_workflow_task, str(run_id))  # the workflow writes the draft and syncs
    if not resumed:
        if UserPreferences.of(user.preferences).automation.generate_drafts:
            draft = draft_for_decision(db, user, opportunity, entry)
            if draft is not None:
                enqueue(generate_draft_task, str(draft.id))
        schedule_sheets_sync(db, user.id)
    return opportunity_detail(db, user, opportunity)


def owned_opportunity(db: Session, user: User, opportunity_id: uuid.UUID) -> Opportunity:
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None or opportunity.user_id != user.id:
        raise HTTPException(404, "Opportunity not found")
    return opportunity


def opportunity_detail(db: Session, user: User, opportunity: Opportunity) -> OpportunityDetail:
    db.refresh(opportunity)
    prefs = UserPreferences.of(user.preferences).recruitment
    advice = (
        Recommendation(**opportunity.recommendation, source="ai")
        if opportunity.recommendation
        else Recommendation(**fallback_recommendation(opportunity), source="rules")
    )
    emails = db.scalars(
        select(EmailMessage).where(EmailMessage.opportunity_id == opportunity.id).order_by(EmailMessage.received_at)
    ).unique().all()
    history = db.scalars(
        select(OpportunityDecision)
        .where(OpportunityDecision.opportunity_id == opportunity.id)
        .order_by(OpportunityDecision.created_at.desc())
    ).all()
    duplicates = db.scalars(
        select(DuplicateCandidate).where(
            DuplicateCandidate.entity_type == "opportunity",
            DuplicateCandidate.status == "pending",
            or_(DuplicateCandidate.record_id == opportunity.id, DuplicateCandidate.candidate_id == opportunity.id),
        )
    ).all()
    return OpportunityDetail.model_validate(opportunity).model_copy(
        update={
            "advice": advice,
            "missing_information": missing_information(opportunity),
            "preference_flags": preference_flags(opportunity, prefs),
            "emails": emails,
            "decisions": history,
            "duplicates": [DuplicateOut.model_validate(d) for d in duplicates],
        }
    )


def _apply_fields(opportunity: Opportunity, changes: dict) -> None:
    for field, value in changes.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(opportunity, field, [] if field == "benefits" and value is None else value)
