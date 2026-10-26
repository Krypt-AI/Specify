import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JsonType, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin
from app.models.email import EmailMessage


class DraftStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"
    DISCARDED = "discarded"


class EmailDraft(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reply draft. Specify only ever saves drafts; sending is always done by the user in Gmail."""

    __tablename__ = "email_drafts"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_draft_idempotency"),
        Index("ix_draft_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email_message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("email_messages.id", ondelete="CASCADE"))
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user_decisions.id", ondelete="SET NULL"), nullable=True)
    # One draft per decision (or per manual request), so retried work never creates a second draft.
    idempotency_key: Mapped[str] = mapped_column(String(100))
    scenario: Mapped[str] = mapped_column(String(40))
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tone: Mapped[str] = mapped_column(String(40))
    instructions: Mapped[str] = mapped_column(Text, default="")  # the user's extra guidance
    recipient: Mapped[str] = mapped_column(String(320))
    subject: Mapped[str] = mapped_column(String(500), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    generated_by: Mapped[str | None] = mapped_column(String(16), nullable=True)  # ai | template
    warnings: Mapped[list] = mapped_column(JsonType, default=list)
    status: Mapped[str] = mapped_column(String(16), default=DraftStatus.GENERATING)
    edited_by_user: Mapped[bool] = mapped_column(default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_draft_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gmail_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gmail_thread_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gmail_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    email: Mapped[EmailMessage] = relationship(lazy="joined")


class DraftTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The user's version of a drafting scenario; built-in defaults apply when none exists."""

    __tablename__ = "draft_templates"
    __table_args__ = (UniqueConstraint("user_id", "scenario", name="uq_template_scenario"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scenario: Mapped[str] = mapped_column(String(40))
    instructions: Mapped[str] = mapped_column(Text, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    use_ai: Mapped[bool] = mapped_column(default=True)
