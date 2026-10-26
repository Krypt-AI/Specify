"""The spec's worksheets: their columns, how records become rows, and which cells may be imported
back from Sheets. Every row is keyed by a stable record ID in its first column, never by row number."""
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog,
    Company,
    EmailMessage,
    EmailMessageGroup,
    Opportunity,
    OpportunityDecision,
    OpportunityStatus,
    RecruiterContact,
    User,
)
from app.schemas.preferences import UserPreferences
from app.services.recruitment.decisions import CONSEQUENTIAL_STATUSES
from app.services.recruitment.records import normalize_company_name, normalize_title

ENTITY_ORDER = ("companies", "opportunities", "applications", "activity", "emails")
MAX_ACTIVITY_ROWS = 2000

STATUS_LABELS = {status: status.replace("_", " ").capitalize() for status in OpportunityStatus}
DECISION_LABELS = {
    "interested": "Interested",
    "interested_need_info": "Interested, need more information",
    "request_salary": "Request salary details",
    "request_job_description": "Request job description",
    "request_interview_details": "Request interview details",
    "request_more_time": "Request more time",
    "decline": "Decline",
    "already_applied": "Already applied",
    "save_for_later": "Save for later",
    "irrelevant": "Irrelevant",
    "custom": "Custom",
}


class ImportRejected(ValueError):
    """A value edited in Sheets cannot be applied in Specify."""


@dataclass(frozen=True)
class FieldSpec:
    key: str
    header: str
    importable: bool = False


@dataclass(frozen=True)
class EntitySpec:
    key: str
    title: str
    fields: tuple[FieldSpec, ...]
    two_way: bool = True  # activity and email tracker are export-only

    @property
    def id_field(self) -> str:
        return self.fields[0].key

    def field(self, key: str) -> FieldSpec:
        return next(f for f in self.fields if f.key == key)


SPECS: dict[str, EntitySpec] = {
    "companies": EntitySpec(
        "companies",
        "Companies",
        (
            FieldSpec("company_id", "Company ID"),
            FieldSpec("name", "Company Name", True),
            FieldSpec("website", "Website", True),
            FieldSpec("domain", "Domain"),
            FieldSpec("industry", "Industry", True),
            FieldSpec("country", "Country", True),
            FieldSpec("recruiter_name", "Recruiter Name"),
            FieldSpec("recruiter_email", "Recruiter Email"),
            FieldSpec("notes", "Notes", True),
        ),
    ),
    "opportunities": EntitySpec(
        "opportunities",
        "Opportunities",
        (
            FieldSpec("opportunity_id", "Opportunity ID"),
            FieldSpec("company_id", "Company ID"),
            FieldSpec("job_title", "Job Title", True),
            FieldSpec("job_description", "Job Description", True),
            FieldSpec("salary", "Salary", True),
            FieldSpec("currency", "Currency", True),
            FieldSpec("work_arrangement", "Work Arrangement", True),
            FieldSpec("date_received", "Date Received"),
            FieldSpec("deadline", "Deadline", True),
            FieldSpec("gmail_thread_url", "Gmail Thread URL"),
            FieldSpec("status", "Opportunity Status", True),
        ),
    ),
    "applications": EntitySpec(
        "applications",
        "Applications",
        (
            FieldSpec("application_id", "Application ID"),
            FieldSpec("opportunity_id", "Opportunity ID"),
            FieldSpec("decision", "Decision"),
            FieldSpec("application_status", "Application Status"),
            FieldSpec("date_applied", "Date Applied"),
            FieldSpec("last_contact", "Last Contact"),
            FieldSpec("next_follow_up", "Next Follow-up", True),
            FieldSpec("priority", "Priority", True),
            FieldSpec("notes", "Notes", True),
        ),
    ),
    "activity": EntitySpec(
        "activity",
        "Activity Log",
        (
            FieldSpec("activity_id", "Activity ID"),
            FieldSpec("timestamp", "Timestamp"),
            FieldSpec("company_id", "Company ID"),
            FieldSpec("opportunity_id", "Opportunity ID"),
            FieldSpec("activity_type", "Activity Type"),
            FieldSpec("summary", "Summary"),
            FieldSpec("related_email", "Related Email"),
            FieldSpec("workflow_status", "Workflow Status"),
        ),
        two_way=False,
    ),
    "emails": EntitySpec(
        "emails",
        "Email Tracker",
        (
            FieldSpec("email_id", "Email ID"),
            FieldSpec("category", "Category"),
            FieldSpec("sender", "Sender"),
            FieldSpec("subject", "Subject"),
            FieldSpec("received_date", "Received Date"),
            FieldSpec("institution", "Institution or Provider"),
            FieldSpec("deadline", "Extracted Deadline"),
            FieldSpec("processing_status", "Processing Status"),
            FieldSpec("gmail_thread_url", "Gmail Thread URL"),
            FieldSpec("notes", "Notes"),
        ),
        two_way=False,
    ),
}


def default_worksheets() -> dict:
    return {
        key: {
            "enabled": key != "emails",  # the Email Tracker is optional
            "title": spec.title,
            "direction": "export",
            "source_of_truth": "database",
            "columns": {f.key: f.header for f in spec.fields},
        }
        for key, spec in SPECS.items()
    }


def cell_text(value: object) -> str:
    """Normalize a cell or record value for comparison: 8000.0 and "8000" are equal."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (float, Decimal)) and value == int(value):
        return str(int(value))
    return str(value).strip()


def build_rows(db: Session, user: User, entity: str, tracker_groups: list[str]) -> dict[str, dict[str, str]]:
    zone = ZoneInfo(UserPreferences.of(user.preferences).timezone or "UTC")
    builder = {
        "companies": _company_rows,
        "opportunities": _opportunity_rows,
        "applications": _application_rows,
        "activity": _activity_rows,
        "emails": _email_rows,
    }[entity]
    rows = builder(db, user.id, zone, tracker_groups)
    return {record_id: {key: cell_text(value) for key, value in values.items()} for record_id, values in rows.items()}


def import_value(db: Session, user: User, entity: str, record_id: str, field: str, raw: str) -> None:
    """Apply one cell edited in Sheets. Raises ImportRejected when the value cannot be accepted."""
    spec = SPECS[entity]
    if not spec.two_way or not spec.field(field).importable:
        raise ImportRejected("This column cannot be edited from Sheets.")
    value = raw.strip()
    try:
        record_uuid = uuid.UUID(record_id)
    except ValueError as exc:
        raise ImportRejected("Unknown record ID.") from exc
    if entity == "companies":
        _import_company(db, user, record_uuid, field, value)
    else:
        opportunity = db.get(Opportunity, record_uuid)
        if opportunity is None or opportunity.user_id != user.id:
            raise ImportRejected("The record no longer exists.")
        _import_opportunity(opportunity, field, value, ZoneInfo(UserPreferences.of(user.preferences).timezone or "UTC"))


def _company_rows(db: Session, user_id: uuid.UUID, zone: ZoneInfo, _groups) -> dict:
    first_contact = {}
    for contact in db.scalars(
        select(RecruiterContact).where(RecruiterContact.user_id == user_id).order_by(RecruiterContact.created_at)
    ).unique():
        first_contact.setdefault(contact.company_id, contact)
    rows = {}
    for company in db.scalars(select(Company).where(Company.user_id == user_id)):
        contact = first_contact.get(company.id)
        rows[str(company.id)] = {
            "company_id": company.id,
            "name": company.name,
            "website": company.website,
            "domain": company.domain,
            "industry": company.industry,
            "country": company.country,
            "recruiter_name": contact.name if contact else "",
            "recruiter_email": contact.email if contact else "",
            "notes": company.notes,
        }
    return rows


def _opportunities(db: Session, user_id: uuid.UUID) -> list[Opportunity]:
    return list(db.scalars(select(Opportunity).where(Opportunity.user_id == user_id)).unique())


def _opportunity_rows(db: Session, user_id: uuid.UUID, zone: ZoneInfo, _groups) -> dict:
    return {
        str(o.id): {
            "opportunity_id": o.id,
            "company_id": o.company_id,
            "job_title": o.job_title,
            "job_description": o.job_description,
            "salary": format_salary(o.salary_min, o.salary_max),
            "currency": o.salary_currency,
            "work_arrangement": o.work_arrangement,
            "date_received": _local_date(o.date_received, zone),
            "deadline": o.application_deadline.isoformat() if o.application_deadline else o.deadline_text,
            "gmail_thread_url": o.gmail_thread_url,
            "status": STATUS_LABELS[OpportunityStatus(o.status)],
        }
        for o in _opportunities(db, user_id)
    }


def _application_rows(db: Session, user_id: uuid.UUID, zone: ZoneInfo, _groups) -> dict:
    applied = dict(
        db.execute(
            select(OpportunityDecision.opportunity_id, func.min(OpportunityDecision.created_at))
            .where(OpportunityDecision.user_id == user_id, OpportunityDecision.decision == "already_applied")
            .group_by(OpportunityDecision.opportunity_id)
        ).all()
    )
    return {
        str(o.id): {
            "application_id": o.id,  # one application per opportunity
            "opportunity_id": o.id,
            "decision": o.custom_decision or DECISION_LABELS.get(o.decision or "", ""),
            "application_status": STATUS_LABELS[OpportunityStatus(o.status)],
            "date_applied": _local_date(applied.get(o.id), zone),
            "last_contact": _local_date(o.last_contact_at, zone),
            "next_follow_up": _local_date(o.next_follow_up_at, zone),
            "priority": o.priority,
            "notes": o.notes,
        }
        for o in _opportunities(db, user_id)
    }


def _activity_rows(db: Session, user_id: uuid.UUID, zone: ZoneInfo, _groups) -> dict:
    events = db.scalars(
        select(AuditLog)
        .where(AuditLog.user_id == user_id, AuditLog.action.like("opportunity.%") | AuditLog.action.like("company.%"))
        .order_by(AuditLog.created_at.desc())
        .limit(MAX_ACTIVITY_ROWS)
    )
    return {
        str(event.id): {
            "activity_id": event.id,
            "timestamp": event.created_at.astimezone(zone).strftime("%Y-%m-%d %H:%M"),
            "company_id": event.details.get("company_id"),
            "opportunity_id": event.details.get("opportunity_id") or (event.entity_id if event.entity_type == "opportunity" else None),
            "activity_type": event.action,
            "summary": event.details.get("summary", ""),
            "related_email": event.details.get("gmail_thread_url"),
            "workflow_status": event.details.get("workflow_status"),
        }
        for event in events
    }


def _email_rows(db: Session, user_id: uuid.UUID, zone: ZoneInfo, groups: list[str]) -> dict:
    if not groups:
        return {}
    emails = db.scalars(
        select(EmailMessage).where(
            EmailMessage.user_id == user_id,
            EmailMessage.groups.any(EmailMessageGroup.group_name.in_(groups)),
        )
    ).unique()
    return {
        str(e.id): {
            "email_id": e.id,
            "category": ", ".join(([e.primary_group] if e.primary_group else []) + e.secondary_groups),
            "sender": f"{e.sender_name} <{e.sender_email}>" if e.sender_name else e.sender_email,
            "subject": e.subject,
            "received_date": _local_date(e.received_at, zone),
            "institution": e.extracted_data.get("organization"),
            "deadline": e.extracted_data.get("deadline"),
            "processing_status": e.processing_status.replace("_", " "),
            "gmail_thread_url": e.gmail_thread_url,
            "notes": e.label.name if e.label else "",
        }
        for e in emails
    }


def format_salary(minimum: Decimal | None, maximum: Decimal | None) -> str:
    values = [cell_text(v) for v in (minimum, maximum) if v is not None]
    return "-".join(dict.fromkeys(values))


def parse_salary(value: str) -> tuple[Decimal | None, Decimal | None]:
    if not value:
        return None, None
    numbers = [Decimal(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", value)]
    if not numbers or len(numbers) > 2:
        raise ImportRejected("Write the salary as a number or a range, such as 8000 or 8000-10000.")
    return numbers[0], numbers[-1] if len(numbers) == 2 else None


def _local_date(value: datetime | None, zone: ZoneInfo) -> str:
    return value.astimezone(zone).date().isoformat() if value else ""


def _parse_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as exc:
        raise ImportRejected("Write dates as YYYY-MM-DD.") from exc


def _import_company(db: Session, user: User, company_id: uuid.UUID, field: str, value: str) -> None:
    company = db.get(Company, company_id)
    if company is None or company.user_id != user.id:
        raise ImportRejected("The company no longer exists.")
    if field == "name":
        if not value:
            raise ImportRejected("A company needs a name.")
        key = normalize_company_name(value)
        clash = db.scalar(select(Company).where(Company.user_id == user.id, Company.normalized_name == key, Company.id != company.id))
        if clash:
            raise ImportRejected(f'Another company is already called "{clash.name}".')
        company.name, company.normalized_name = value[:200], key
    elif field == "notes":
        company.notes = value
    else:
        setattr(company, field, value[:500] or None)


def _import_opportunity(opportunity: Opportunity, field: str, value: str, zone: ZoneInfo) -> None:
    if field == "job_title":
        if not value:
            raise ImportRejected("An opportunity needs a job title.")
        opportunity.job_title, opportunity.normalized_title = value[:200], normalize_title(value)
    elif field == "job_description":
        opportunity.job_description = value[:4000]
    elif field == "salary":
        opportunity.salary_min, opportunity.salary_max = parse_salary(value)
    elif field == "currency":
        if value and not re.fullmatch(r"[A-Za-z]{3}", value):
            raise ImportRejected("Use a three-letter currency code, such as MYR.")
        opportunity.salary_currency = value.upper() or None
    elif field == "work_arrangement":
        arrangement = value.lower().replace("-", "").replace(" ", "") or None
        if arrangement not in (None, "remote", "hybrid", "onsite"):
            raise ImportRejected("Use remote, hybrid or onsite.")
        opportunity.work_arrangement = arrangement
    elif field == "deadline":
        opportunity.application_deadline = _parse_date(value)
    elif field == "status":
        status = next((s for s, label in STATUS_LABELS.items() if value.lower() in (label.lower(), s.value)), None)
        if status is None:
            raise ImportRejected("Unknown status.")
        if status in CONSEQUENTIAL_STATUSES:
            raise ImportRejected(f"Set “{STATUS_LABELS[status]}” in Specify, where it asks for confirmation.")
        opportunity.status = status
    elif field == "next_follow_up":
        day = _parse_date(value)
        opportunity.next_follow_up_at = datetime.combine(day, time(9), zone) if day else None
    elif field == "priority":
        if value.lower() not in ("low", "normal", "high"):
            raise ImportRejected("Use low, normal or high.")
        opportunity.priority = value.lower()
    elif field == "notes":
        opportunity.notes = value
