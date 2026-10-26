import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JsonType, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class CompanyType(StrEnum):
    EMPLOYER = "employer"
    AGENCY = "agency"
    UNKNOWN = "unknown"


class OpportunityStatus(StrEnum):
    NEW = "new"
    AWAITING_DECISION = "awaiting_decision"
    INTERESTED = "interested"
    MORE_INFO_REQUIRED = "more_info_required"
    PREPARING_APPLICATION = "preparing_application"
    APPLIED = "applied"
    INTERVIEW_SCHEDULED = "interview_scheduled"
    INTERVIEW_COMPLETED = "interview_completed"
    OFFER_RECEIVED = "offer_received"
    OFFER_ACCEPTED = "offer_accepted"
    OFFER_DECLINED = "offer_declined"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    ARCHIVED = "archived"


class Decision(StrEnum):
    INTERESTED = "interested"
    INTERESTED_NEED_INFO = "interested_need_info"
    REQUEST_SALARY = "request_salary"
    REQUEST_JOB_DESCRIPTION = "request_job_description"
    REQUEST_INTERVIEW_DETAILS = "request_interview_details"
    REQUEST_MORE_TIME = "request_more_time"
    DECLINE = "decline"
    ALREADY_APPLIED = "already_applied"
    SAVE_FOR_LATER = "save_for_later"
    IRRELEVANT = "irrelevant"
    CUSTOM = "custom"


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A direct employer or a recruitment agency."""

    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("user_id", "normalized_name", name="uq_company_user_name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    normalized_name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    country: Mapped[str | None] = mapped_column(String(80), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    company_type: Mapped[str] = mapped_column(String(16), default=CompanyType.UNKNOWN)
    notes: Mapped[str] = mapped_column(Text, default="")
    first_contact_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    contacts: Mapped[list["RecruiterContact"]] = relationship(back_populates="company")
    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="company")


class RecruiterContact(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "recruiter_contacts"
    __table_args__ = (UniqueConstraint("user_id", "email", name="uq_contact_user_email"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")

    company: Mapped[Company | None] = relationship(back_populates="contacts", lazy="joined")


class Opportunity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One job opportunity. Status and the user's decision live here; decision history in user_decisions."""

    __tablename__ = "opportunities"
    __table_args__ = (Index("ix_opportunity_user_status", "user_id", "status"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recruiter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("recruiter_contacts.id", ondelete="SET NULL"), nullable=True
    )
    job_title: Mapped[str] = mapped_column(String(200))
    normalized_title: Mapped[str] = mapped_column(String(200))
    job_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    job_description: Mapped[str] = mapped_column(Text, default="")
    employment_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    work_arrangement: Mapped[str | None] = mapped_column(String(16), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    salary_period: Mapped[str | None] = mapped_column(String(8), nullable=True)
    benefits: Mapped[list] = mapped_column(JsonType, default=list)
    application_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    deadline_text: Mapped[str | None] = mapped_column(String(200), nullable=True)
    date_received: Mapped[datetime] = mapped_column(UTCDateTime)
    application_source: Mapped[str] = mapped_column(String(16), default="email")  # email | manual
    gmail_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    gmail_thread_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    priority: Mapped[str] = mapped_column(String(8), default="normal")  # low | normal | high
    status: Mapped[str] = mapped_column(String(32), default=OpportunityStatus.NEW)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    custom_decision: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    last_contact_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    next_follow_up_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    # Advisory AI recommendation: {"decision": ..., "explanation": ...}
    recommendation: Mapped[dict | None] = mapped_column(JsonType, nullable=True)

    company: Mapped[Company | None] = relationship(back_populates="opportunities", lazy="joined")
    recruiter: Mapped[RecruiterContact | None] = relationship(lazy="joined")

    @property
    def company_name(self) -> str | None:
        return self.company.name if self.company else None


class OpportunityDecision(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """History of the user's decisions (spec table user_decisions)."""

    __tablename__ = "user_decisions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    opportunity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("opportunities.id", ondelete="CASCADE"), index=True
    )
    email_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_messages.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(32))
    custom_decision: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")


class DuplicateCandidate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A possible duplicate awaiting the user's decision; records are never merged automatically."""

    __tablename__ = "duplicate_candidates"
    __table_args__ = (UniqueConstraint("entity_type", "record_id", "candidate_id", name="uq_duplicate_pair"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(16))  # company | opportunity
    record_id: Mapped[uuid.UUID]  # the newer record
    candidate_id: Mapped[uuid.UUID]  # the existing record it may duplicate
    score: Mapped[float]
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | merged | dismissed
