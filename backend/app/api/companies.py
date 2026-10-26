import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import Company, CompanyType, Opportunity, RecruiterContact, User
from app.schemas.recruitment import (
    CompanyCreate,
    CompanyDetail,
    CompanyOut,
    CompanyPage,
    CompanyUpdate,
    ContactOut,
    ContactUpdate,
)
from app.services.recruitment import records
from app.tasks import schedule_sheets_sync

router = APIRouter(tags=["companies"])


@router.get("/companies", response_model=CompanyPage)
def list_companies(
    q: str | None = Query(None, max_length=200),
    company_type: CompanyType | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CompanyPage:
    query = select(Company).where(Company.user_id == user.id)
    if q:
        query = query.where(func.lower(Company.name).like(f"%{q.strip().lower()}%"))
    if company_type:
        query = query.where(Company.company_type == company_type)
    companies = db.scalars(query.order_by(Company.last_contact_at.desc().nulls_last(), Company.name)).all()
    opportunity_counts = _counts(db, Opportunity.company_id, user.id, Opportunity.user_id)
    contact_counts = _counts(db, RecruiterContact.company_id, user.id, RecruiterContact.user_id)
    items = [
        CompanyOut.model_validate(company).model_copy(
            update={
                "opportunity_count": opportunity_counts.get(company.id, 0),
                "contact_count": contact_counts.get(company.id, 0),
            }
        )
        for company in companies
    ]
    return CompanyPage(items=items, total=len(items))


@router.get("/companies/{company_id}", response_model=CompanyDetail)
def get_company(company_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> CompanyDetail:
    return _detail(db, _owned_company(db, user, company_id))


@router.post("/companies", response_model=CompanyDetail, status_code=201)
def create_company(body: CompanyCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> CompanyDetail:
    key = records.normalize_company_name(body.name)
    if db.scalar(select(Company).where(Company.user_id == user.id, Company.normalized_name == key)):
        raise HTTPException(409, "A company with this name already exists.")
    company = Company(user_id=user.id, name=body.name.strip(), normalized_name=key, company_type=CompanyType.UNKNOWN)
    _apply(company, body.model_dump(exclude_unset=True, exclude={"name"}))
    db.add(company)
    db.commit()
    return _detail(db, company)


@router.patch("/companies/{company_id}", response_model=CompanyDetail)
def update_company(
    company_id: uuid.UUID, body: CompanyUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> CompanyDetail:
    company = _owned_company(db, user, company_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes:
        key = records.normalize_company_name(changes["name"])
        clash = db.scalar(
            select(Company).where(Company.user_id == user.id, Company.normalized_name == key, Company.id != company.id)
        )
        if clash:
            raise HTTPException(409, f'"{clash.name}" already exists. Merge the two companies instead.')
        company.normalized_name = key
    _apply(company, changes)
    db.commit()
    schedule_sheets_sync(db, user.id)
    return _detail(db, company)


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: uuid.UUID, body: ContactUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RecruiterContact:
    contact = db.get(RecruiterContact, contact_id)
    if contact is None or contact.user_id != user.id:
        raise HTTPException(404, "Contact not found")
    changes = body.model_dump(exclude_unset=True)
    if changes.get("company_id"):
        _owned_company(db, user, changes["company_id"])
    _apply(contact, changes)
    db.commit()
    schedule_sheets_sync(db, user.id)
    return contact


def _owned_company(db: Session, user: User, company_id: uuid.UUID) -> Company:
    company = db.get(Company, company_id)
    if company is None or company.user_id != user.id:
        raise HTTPException(404, "Company not found")
    return company


def _detail(db: Session, company: Company) -> CompanyDetail:
    db.refresh(company)
    contacts = db.scalars(select(RecruiterContact).where(RecruiterContact.company_id == company.id)).unique().all()
    opportunities = db.scalars(
        select(Opportunity).where(Opportunity.company_id == company.id).order_by(Opportunity.date_received.desc())
    ).unique().all()
    return CompanyDetail.model_validate(company).model_copy(
        update={
            "contacts": [ContactOut.model_validate(c) for c in contacts],
            "opportunities": opportunities,
            "opportunity_count": len(opportunities),
            "contact_count": len(contacts),
        }
    )


def _counts(db: Session, column, user_id: uuid.UUID, owner_column) -> dict:
    return dict(
        db.execute(
            select(column, func.count()).where(owner_column == user_id, column.is_not(None)).group_by(column)
        ).all()
    )


def _apply(target, changes: dict) -> None:
    for field, value in changes.items():
        setattr(target, field, value.strip() if isinstance(value, str) else value)
