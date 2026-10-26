"""Companies, contacts and opportunities: matching, creation and merging.

Exact identifiers (domain, normalized name, email thread, job reference) match automatically.
Anything weaker becomes a DuplicateCandidate for the user to confirm; records are never merged
on a guess, and two opportunities are never merged just because company and title agree.
"""
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import (
    Company,
    CompanyType,
    DuplicateCandidate,
    EmailMessage,
    Opportunity,
    OpportunityDecision,
    OpportunityStatus,
    RecruiterContact,
)

COMPANY_SIMILARITY = 0.85
_LEGAL_SUFFIXES = {
    "sdn", "bhd", "berhad", "inc", "ltd", "limited", "llc", "llp", "plc", "corp", "corporation",
    "co", "company", "gmbh", "pte", "pty", "ag", "bv", "group",
}

STATUS_RANK = {
    OpportunityStatus.NEW: 0,
    OpportunityStatus.AWAITING_DECISION: 1,
    OpportunityStatus.INTERESTED: 2,
    OpportunityStatus.MORE_INFO_REQUIRED: 2,
    OpportunityStatus.PREPARING_APPLICATION: 3,
    OpportunityStatus.APPLIED: 4,
    OpportunityStatus.INTERVIEW_SCHEDULED: 5,
    OpportunityStatus.INTERVIEW_COMPLETED: 6,
    OpportunityStatus.OFFER_RECEIVED: 7,
}
CLOSED_STATUSES = {
    OpportunityStatus.OFFER_ACCEPTED,
    OpportunityStatus.OFFER_DECLINED,
    OpportunityStatus.REJECTED,
    OpportunityStatus.WITHDRAWN,
    OpportunityStatus.ARCHIVED,
}
STATUS_FOR_EMAIL_TYPE = {
    "new_opportunity": OpportunityStatus.NEW,
    "follow_up": OpportunityStatus.NEW,
    "application_update": OpportunityStatus.APPLIED,
    "assessment": OpportunityStatus.APPLIED,
    "interview_invitation": OpportunityStatus.INTERVIEW_SCHEDULED,
    "offer": OpportunityStatus.OFFER_RECEIVED,
    "rejection": OpportunityStatus.REJECTED,
}


@dataclass
class CompanyData:
    name: str
    domain: str | None = None
    website: str | None = None
    industry: str | None = None
    country: str | None = None
    location: str | None = None
    company_type: CompanyType = CompanyType.UNKNOWN


def normalize_company_name(name: str) -> str:
    words = re.findall(r"[a-z0-9]+", name.lower())
    while len(words) > 1 and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def normalize_title(title: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", title.lower()))


def upsert_company(db: Session, user_id: uuid.UUID, data: CompanyData, seen_at: datetime) -> Company:
    company = None
    if data.domain:
        company = db.scalar(select(Company).where(Company.user_id == user_id, Company.domain == data.domain))
    key = normalize_company_name(data.name)
    if company is None and key:
        company = db.scalar(select(Company).where(Company.user_id == user_id, Company.normalized_name == key))

    if company is None:
        company = Company(user_id=user_id, name=data.name.strip()[:200], normalized_name=key or data.name.lower())
        db.add(company)
        _fill_company(company, data)
        db.flush()
        _flag_similar_companies(db, company)
    else:
        _fill_company(company, data)
    company.first_contact_at = min(filter(None, (company.first_contact_at, seen_at)))
    company.last_contact_at = max(filter(None, (company.last_contact_at, seen_at)))
    return company


def upsert_contact(
    db: Session,
    user_id: uuid.UUID,
    email: str,
    *,
    name: str | None,
    phone: str | None,
    role: str | None,
    company: Company | None,
) -> RecruiterContact:
    email = email.strip().lower()
    contact = db.scalar(
        select(RecruiterContact).where(RecruiterContact.user_id == user_id, RecruiterContact.email == email)
    )
    if contact is None:
        contact = RecruiterContact(user_id=user_id, email=email, name="")
        db.add(contact)
    contact.name = contact.name or (name or "").strip()[:200]
    contact.phone = contact.phone or (phone.strip()[:64] if phone else None)
    contact.role = contact.role or (role.strip()[:120] if role else None)
    if contact.company is None and company is not None:
        contact.company = company
    db.flush()
    return contact


def find_opportunity(
    db: Session, user_id: uuid.UUID, thread_id: str, company: Company | None, reference: str | None
) -> Opportunity | None:
    """Same email thread, or the same job reference at the same company."""
    by_thread = db.scalar(
        select(Opportunity)
        .where(Opportunity.user_id == user_id, Opportunity.gmail_thread_id == thread_id)
        .order_by(Opportunity.created_at)
    )
    if by_thread or not (company and reference):
        return by_thread
    return db.scalar(
        select(Opportunity).where(
            Opportunity.user_id == user_id,
            Opportunity.company_id == company.id,
            func.lower(Opportunity.job_reference) == reference.strip().lower(),
        )
    )


def add_opportunity(db: Session, opportunity: Opportunity) -> Opportunity:
    opportunity.normalized_title = normalize_title(opportunity.job_title)
    db.add(opportunity)
    db.flush()
    _flag_similar_opportunities(db, opportunity)
    return opportunity


def advance_status(opportunity: Opportunity, email_type: str) -> bool:
    """Move the status forward when an email reports progress; closed opportunities stay closed."""
    target = STATUS_FOR_EMAIL_TYPE.get(email_type)
    if target is None or opportunity.status in CLOSED_STATUSES:
        return False
    if target == OpportunityStatus.REJECTED or STATUS_RANK[target] > STATUS_RANK.get(opportunity.status, 0):
        opportunity.status = target
        return True
    return False


def merge_companies(db: Session, source: Company, target: Company) -> None:
    """Fold source into target: contacts and opportunities move, missing details are filled in."""
    db.execute(update(RecruiterContact).where(RecruiterContact.company_id == source.id).values(company_id=target.id))
    db.execute(update(Opportunity).where(Opportunity.company_id == source.id).values(company_id=target.id))
    _fill_company(
        target,
        CompanyData(
            name=target.name,
            domain=source.domain,
            website=source.website,
            industry=source.industry,
            country=source.country,
            location=source.location,
            company_type=CompanyType(source.company_type),
        ),
    )
    target.notes = "\n\n".join(filter(None, (target.notes, source.notes)))
    target.first_contact_at = min(filter(None, (target.first_contact_at, source.first_contact_at)), default=None)
    target.last_contact_at = max(filter(None, (target.last_contact_at, source.last_contact_at)), default=None)
    _forget_duplicate_pairs(db, source.id)
    # Reload the (now empty) collections so deleting source cannot detach the moved records.
    db.expire(source, ["contacts", "opportunities"])
    db.delete(source)


def merge_opportunities(db: Session, source: Opportunity, target: Opportunity) -> None:
    """Fold source into target: linked emails and decision history move, missing details are filled."""
    db.execute(update(EmailMessage).where(EmailMessage.opportunity_id == source.id).values(opportunity_id=target.id))
    db.execute(
        update(OpportunityDecision).where(OpportunityDecision.opportunity_id == source.id).values(opportunity_id=target.id)
    )
    for field in (
        "company_id", "recruiter_id", "job_reference", "employment_type", "work_arrangement", "location",
        "salary_min", "salary_max", "salary_currency", "salary_period", "application_deadline",
        "deadline_text", "gmail_thread_id", "gmail_thread_url", "decision", "custom_decision",
        "next_follow_up_at", "recommendation",
    ):
        if getattr(target, field) in (None, "") and getattr(source, field) not in (None, ""):
            setattr(target, field, getattr(source, field))
    target.job_description = target.job_description or source.job_description
    target.benefits = target.benefits or source.benefits
    target.notes = "\n\n".join(filter(None, (target.notes, source.notes)))
    target.date_received = min(target.date_received, source.date_received)
    target.last_contact_at = max(filter(None, (target.last_contact_at, source.last_contact_at)), default=None)
    if target.status not in CLOSED_STATUSES and (
        source.status in CLOSED_STATUSES or STATUS_RANK.get(source.status, 0) > STATUS_RANK.get(target.status, 0)
    ):
        target.status = source.status
    _forget_duplicate_pairs(db, source.id)
    db.delete(source)


def _fill_company(company: Company, data: CompanyData) -> None:
    for field in ("domain", "website", "industry", "country", "location"):
        value = getattr(data, field)
        if value and not getattr(company, field):
            setattr(company, field, value.strip())
    if company.company_type in (None, CompanyType.UNKNOWN) and data.company_type != CompanyType.UNKNOWN:
        company.company_type = data.company_type


def _flag_similar_companies(db: Session, company: Company) -> None:
    numbers = re.findall(r"\d+", company.normalized_name)
    others = db.scalars(select(Company).where(Company.user_id == company.user_id, Company.id != company.id))
    for other in others:
        if re.findall(r"\d+", other.normalized_name) != numbers:
            continue
        score = SequenceMatcher(None, company.normalized_name, other.normalized_name).ratio()
        if score >= COMPANY_SIMILARITY:
            db.add(
                DuplicateCandidate(
                    user_id=company.user_id,
                    entity_type="company",
                    record_id=company.id,
                    candidate_id=other.id,
                    score=round(score, 2),
                    reason=f'The name is similar to "{other.name}".',
                )
            )


def _flag_similar_opportunities(db: Session, opportunity: Opportunity) -> None:
    if opportunity.company_id is None:
        return
    others = db.scalars(
        select(Opportunity).where(
            Opportunity.user_id == opportunity.user_id,
            Opportunity.id != opportunity.id,
            Opportunity.company_id == opportunity.company_id,
            Opportunity.normalized_title == opportunity.normalized_title,
            Opportunity.status.not_in(CLOSED_STATUSES),
        )
    )
    for other in others:
        db.add(
            DuplicateCandidate(
                user_id=opportunity.user_id,
                entity_type="opportunity",
                record_id=opportunity.id,
                candidate_id=other.id,
                score=1.0,
                reason="Same company and job title. It may be the same role or a separate opening.",
            )
        )


def _forget_duplicate_pairs(db: Session, record_id: uuid.UUID) -> None:
    db.execute(
        delete(DuplicateCandidate).where(
            or_(DuplicateCandidate.record_id == record_id, DuplicateCandidate.candidate_id == record_id),
            DuplicateCandidate.status == "pending",
        )
    )
