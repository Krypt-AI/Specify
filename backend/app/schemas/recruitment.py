import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import CompanyType, Decision, OpportunityStatus
from app.schemas.preferences import SalaryPeriod, WorkArrangement

Priority = Literal["low", "normal", "high"]


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CompanyRef(_ORM):
    id: uuid.UUID
    name: str


class ContactRef(_ORM):
    id: uuid.UUID
    name: str
    email: str


class OpportunityRef(_ORM):
    id: uuid.UUID
    job_title: str
    company_name: str | None
    status: OpportunityStatus
    decision: Decision | None


class ContactOut(_ORM):
    id: uuid.UUID
    company_id: uuid.UUID | None
    name: str
    email: str
    phone: str | None
    role: str | None
    notes: str


class ContactUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=64)
    role: str | None = Field(None, max_length=120)
    notes: str | None = None
    company_id: uuid.UUID | None = None


class CompanyFields(BaseModel):
    domain: str | None = Field(None, max_length=255)
    website: str | None = Field(None, max_length=500)
    industry: str | None = Field(None, max_length=120)
    country: str | None = Field(None, max_length=80)
    location: str | None = Field(None, max_length=200)
    company_type: CompanyType | None = None
    notes: str | None = None


class CompanyCreate(CompanyFields):
    name: str = Field(min_length=1, max_length=200)


class CompanyUpdate(CompanyFields):
    name: str | None = Field(None, min_length=1, max_length=200)


class CompanyOut(_ORM):
    id: uuid.UUID
    name: str
    domain: str | None
    website: str | None
    industry: str | None
    country: str | None
    location: str | None
    company_type: CompanyType
    notes: str
    first_contact_at: datetime | None
    last_contact_at: datetime | None
    opportunity_count: int = 0
    contact_count: int = 0


class OpportunitySummary(_ORM):
    id: uuid.UUID
    job_title: str
    company: CompanyRef | None
    recruiter: ContactRef | None
    status: OpportunityStatus
    decision: Decision | None
    custom_decision: str | None
    priority: Priority
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    salary_period: str | None
    work_arrangement: str | None
    location: str | None
    application_deadline: date | None
    date_received: datetime
    last_contact_at: datetime | None
    next_follow_up_at: datetime | None


class CompanyDetail(CompanyOut):
    contacts: list[ContactOut]
    opportunities: list[OpportunitySummary]


class CompanyPage(BaseModel):
    items: list[CompanyOut]
    total: int


class EmailRef(_ORM):
    id: uuid.UUID
    subject: str
    sender_name: str
    sender_email: str
    snippet: str
    received_at: datetime
    gmail_thread_url: str


class DecisionOut(_ORM):
    id: uuid.UUID
    decision: Decision
    custom_decision: str | None
    notes: str
    created_at: datetime


class DuplicateOut(_ORM):
    id: uuid.UUID
    entity_type: Literal["company", "opportunity"]
    record_id: uuid.UUID
    candidate_id: uuid.UUID
    record_name: str = ""
    candidate_name: str = ""
    score: float
    reason: str
    created_at: datetime


class Recommendation(BaseModel):
    decision: str
    explanation: str
    source: Literal["ai", "rules"]


class OpportunityDetail(OpportunitySummary):
    job_reference: str | None
    job_description: str
    employment_type: str | None
    benefits: list[str]
    deadline_text: str | None
    application_source: str
    gmail_thread_url: str | None
    notes: str
    advice: Recommendation | None = None  # AI recommendation, or a rules-based one when none exists
    missing_information: list[str] = []
    preference_flags: list[str] = []
    emails: list[EmailRef] = []
    decisions: list[DecisionOut] = []
    duplicates: list[DuplicateOut] = []


class OpportunityPage(BaseModel):
    items: list[OpportunitySummary]
    total: int
    page: int
    page_size: int


class OpportunityFields(BaseModel):
    job_reference: str | None = Field(None, max_length=100)
    job_description: str | None = Field(None, max_length=4000)
    employment_type: str | None = Field(None, max_length=40)
    work_arrangement: WorkArrangement | None = None
    location: str | None = Field(None, max_length=200)
    salary_min: float | None = Field(None, ge=0)
    salary_max: float | None = Field(None, ge=0)
    salary_currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    salary_period: SalaryPeriod | None = None
    benefits: list[str] | None = None
    application_deadline: date | None = None
    priority: Priority | None = None
    notes: str | None = None
    next_follow_up_at: datetime | None = None


class OpportunityCreate(OpportunityFields):
    """Created by the user, optionally from an email (the sender becomes the recruiter)."""

    job_title: str = Field(min_length=1, max_length=200)
    company_id: uuid.UUID | None = None
    company_name: str | None = Field(None, max_length=200)
    from_email_id: uuid.UUID | None = None


class OpportunityUpdate(OpportunityFields):
    job_title: str | None = Field(None, min_length=1, max_length=200)
    company_id: uuid.UUID | None = None
    status: OpportunityStatus | None = None
    confirm: bool = False


class DecisionCreate(BaseModel):
    decision: Decision
    custom_decision: str | None = Field(None, max_length=200)
    notes: str = Field("", max_length=2000)
    email_id: uuid.UUID | None = None
    confirm: bool = False


class OpportunityStats(BaseModel):
    decision_queue: int
    active: int
    interviews_scheduled: int
    offers_received: int
    pending_duplicates: int
    by_status: dict[str, int]
