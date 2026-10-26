"""The recruitment step of email processing: extract details, then create or update records.

Runs only for emails whose primary group is recruitment, so university and certification emails
never create recruitment records.
"""
import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import CompanyType, EmailMessage, Opportunity, OpportunityStatus
from app.schemas.preferences import UserPreferences
from app.services.audit import record_event
from app.services.email_domains import business_domain
from app.services.llm import AIOutputError, AIUnavailable
from app.services.recruitment import records
from app.services.recruitment.extraction import ExtractionRequest, RecruitmentExtraction, RecruitmentExtractor
from app.services.recruitment.grounding import grounded_deadline, grounded_salary, grounded_website, mentions
from app.services.reminders import close_recruiter_follow_ups

logger = logging.getLogger(__name__)


def process_recruitment(
    db: Session,
    email: EmailMessage,
    prefs: UserPreferences,
    extractor: RecruitmentExtractor | None,
    final_attempt: bool = True,
) -> None:
    if extractor is None:
        _finish(db, email, "AI extraction is not configured. You can create the opportunity yourself.")
        return
    request = ExtractionRequest(
        sender=f"{email.sender_name} <{email.sender_email}>" if email.sender_name else email.sender_email,
        received_at=email.received_at,
        subject=email.subject,
        body=email.body_text,
        body_truncated=email.body_truncated,
        attachment_names=[a["filename"] for a in email.attachments],
        preferences=prefs.recruitment,
    )
    try:
        extraction = extractor.extract(request)
    except AIUnavailable:
        if not final_attempt:
            raise
        _finish(db, email, "AI extraction is temporarily unavailable. You can create the opportunity yourself.")
        return
    except AIOutputError as exc:
        _finish(db, email, f"{exc} You can create the opportunity yourself.")
        return

    # Two emails about a new company can race; on a unique-constraint clash the retry finds the record.
    for attempt in (1, 2):
        try:
            note = apply_extraction(db, email, extraction)
            _finish(db, email, note)
            return
        except IntegrityError:
            db.rollback()
            if attempt == 2:
                raise


def apply_extraction(db: Session, email: EmailMessage, extraction: RecruitmentExtraction) -> str:
    """Create or update company, contact and opportunity records. Returns a note for the user."""
    if not extraction.is_specific_opportunity:
        return "No specific job opportunity in this email, so no records were created."

    text = f"{email.subject}\n{email.body_text}"
    seen_at = email.received_at
    sender_domain = business_domain(email.sender_email)
    recruiter = extraction.recruiter
    via_agency = recruiter.organization_is_agency and bool(recruiter.organization)

    employer = None
    if extraction.employer.name:
        website, website_domain = grounded_website(text, extraction.employer.website, email.link_domains)
        employer = records.upsert_company(
            db,
            email.user_id,
            records.CompanyData(
                name=extraction.employer.name,
                domain=website_domain or (None if via_agency else sender_domain),
                website=website,
                industry=extraction.employer.industry,
                country=extraction.employer.country,
                location=extraction.employer.location,
                company_type=CompanyType.EMPLOYER,
            ),
            seen_at,
        )
    agency = None
    if via_agency:
        agency = records.upsert_company(
            db,
            email.user_id,
            records.CompanyData(name=recruiter.organization, domain=sender_domain, company_type=CompanyType.AGENCY),
            seen_at,
        )
    elif employer is None and (recruiter.organization or sender_domain):
        employer = records.upsert_company(
            db,
            email.user_id,
            records.CompanyData(
                name=recruiter.organization or sender_domain,
                domain=sender_domain,
                company_type=CompanyType.EMPLOYER if recruiter.organization else CompanyType.UNKNOWN,
            ),
            seen_at,
        )

    contact_email = recruiter.email if mentions(text, recruiter.email) else email.sender_email
    contact = records.upsert_contact(
        db,
        email.user_id,
        contact_email,
        name=recruiter.name or email.sender_name,
        phone=recruiter.phone if mentions(text, recruiter.phone) else None,
        role=recruiter.role,
        company=agency or employer,
    )

    company = employer or agency
    job = extraction.job
    opportunity = records.find_opportunity(db, email.user_id, email.gmail_thread_id, company, job.reference)
    if opportunity is None:
        if not job.title:
            return "The email does not name a role, so no opportunity was created. The company and contact were saved."
        opportunity = records.add_opportunity(
            db,
            Opportunity(
                user_id=email.user_id,
                company=company,
                recruiter=contact,
                job_title=job.title.strip()[:200],
                date_received=seen_at,
                gmail_thread_id=email.gmail_thread_id,
                gmail_thread_url=email.gmail_thread_url,
                status=records.STATUS_FOR_EMAIL_TYPE.get(extraction.email_type, OpportunityStatus.NEW),
                recommendation={
                    "decision": extraction.recommended_decision,
                    "explanation": extraction.recommendation_explanation.strip()[:500],
                },
            ),
        )
        verb = "Created"
    else:
        records.advance_status(opportunity, extraction.email_type)
        close_recruiter_follow_ups(db, opportunity.id)
        verb = "Updated"
    _fill_job_details(opportunity, extraction, text, seen_at)
    db.flush()  # assigns ids used by the activity event
    opportunity.company = opportunity.company or company
    opportunity.recruiter = opportunity.recruiter or contact
    opportunity.last_contact_at = max(filter(None, (opportunity.last_contact_at, seen_at)))
    email.opportunity_id = opportunity.id
    where = f" at {company.name}" if company else ""
    note = f"{verb} the opportunity {opportunity.job_title}{where}."
    record_event(
        db,
        email.user_id,
        f"opportunity.{verb.lower()}",
        entity_type="opportunity",
        entity_id=opportunity.id,
        opportunity_id=str(opportunity.id),
        company_id=str(opportunity.company_id) if opportunity.company_id else None,
        summary=f"{note} Email: {email.subject}"[:300],
        gmail_thread_url=email.gmail_thread_url,
    )
    return note


def _fill_job_details(opportunity: Opportunity, extraction: RecruitmentExtraction, text: str, received_at) -> None:
    """Fill fields the record does not have yet with values grounded in this email."""
    job = extraction.job
    if opportunity.salary_min is None and opportunity.salary_max is None:
        minimum, maximum, currency, period = grounded_salary(
            text, job.salary_min, job.salary_max, job.salary_currency, job.salary_period
        )
        opportunity.salary_min, opportunity.salary_max = minimum, maximum
        opportunity.salary_currency, opportunity.salary_period = currency, period
    if opportunity.application_deadline is None:
        deadline, wording = grounded_deadline(text, job.application_deadline, job.deadline_text, received_at)
        opportunity.application_deadline = deadline
        opportunity.deadline_text = opportunity.deadline_text or wording
    simple_fields = {
        "job_reference": (job.reference, 100),
        "employment_type": (job.employment_type, 40),
        "location": (job.location, 200),
    }
    for field, (value, limit) in simple_fields.items():
        if value and not getattr(opportunity, field):
            setattr(opportunity, field, value.strip()[:limit])
    opportunity.work_arrangement = opportunity.work_arrangement or job.work_arrangement
    if job.description and not opportunity.job_description:
        opportunity.job_description = job.description.strip()[:4000]
    if job.benefits and not opportunity.benefits:
        opportunity.benefits = [b.strip()[:200] for b in job.benefits if b.strip()][:20]


def _finish(db: Session, email: EmailMessage, note: str) -> None:
    email.recruitment_note = note
    email.recruitment_processed_at = utcnow()
    db.commit()
