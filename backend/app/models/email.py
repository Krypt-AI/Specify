import uuid
from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JsonType, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.label import Label
    from app.models.recruitment import Opportunity
    from app.models.user import Integration


class MailGroup(StrEnum):
    """Fixed groups that drive the folders and workflows. Gmail labels are created dynamically."""

    RECRUITMENT = "recruitment"
    UNIVERSITY = "university"
    CERTIFICATIONS = "certifications"
    OTHER = "other"


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    CLASSIFIED = "classified"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


class ClassificationSource(StrEnum):
    RULE = "rule"
    AI = "ai"
    USER = "user"
    FALLBACK = "fallback"


class SyncStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"


class EmailMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint("user_id", "gmail_message_id", name="uq_email_user_message"),
        Index("ix_email_user_received", "user_id", "received_at"),
        Index("ix_email_user_status", "user_id", "processing_status"),
        Index("ix_email_user_sender", "user_id", "sender_email"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(64))
    gmail_thread_id: Mapped[str] = mapped_column(String(64), index=True)
    gmail_thread_url: Mapped[str] = mapped_column(String(512))
    sender_name: Mapped[str] = mapped_column(String(320), default="")
    sender_email: Mapped[str] = mapped_column(String(320))
    reply_to: Mapped[str | None] = mapped_column(String(320), nullable=True)
    recipients: Mapped[list] = mapped_column(JsonType, default=list)
    subject: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    body_truncated: Mapped[bool] = mapped_column(default=False)
    # Set when the body was removed under the user's retention setting (the email stays in Gmail).
    body_purged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    gmail_label_ids: Mapped[list] = mapped_column(JsonType, default=list)
    is_unread: Mapped[bool] = mapped_column(default=True)
    attachments: Mapped[list] = mapped_column(JsonType, default=list)
    headers: Mapped[dict] = mapped_column(JsonType, default=dict)
    link_domains: Mapped[list] = mapped_column(JsonType, default=list)

    label_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("labels.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # A label proposed for a message awaiting review: {"label_id": str | None, "name", "description"}.
    label_suggestion: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    classification_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    classification_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classification_rules.id", ondelete="SET NULL"), nullable=True
    )
    extracted_data: Mapped[dict] = mapped_column(JsonType, default=dict)
    recommended_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reply_required: Mapped[bool] = mapped_column(default=False)
    is_suspicious: Mapped[bool] = mapped_column(default=False)
    suspicious_reasons: Mapped[list] = mapped_column(JsonType, default=list)

    processing_status: Mapped[str] = mapped_column(String(32), default=ProcessingStatus.PENDING)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_attempts: Mapped[int] = mapped_column(default=0)
    classified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    labels_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    # Recruitment extraction runs only for emails whose primary group is recruitment.
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("opportunities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    recruitment_processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    recruitment_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    groups: Mapped[list["EmailMessageGroup"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    label: Mapped["Label | None"] = relationship(lazy="joined")
    opportunity: Mapped["Opportunity | None"] = relationship(lazy="joined")

    @property
    def primary_group(self) -> str | None:
        return next((g.group_name for g in self.groups if g.is_primary), None)

    @property
    def secondary_groups(self) -> list[str]:
        return sorted(g.group_name for g in self.groups if not g.is_primary)

    @property
    def awaits_recruitment_step(self) -> bool:
        return (
            self.processing_status == ProcessingStatus.CLASSIFIED
            and self.primary_group == MailGroup.RECRUITMENT
            and self.recruitment_processed_at is None
        )

    def set_groups(self, primary: str | None, secondary: Iterable[str] = ()) -> None:
        wanted = {group: False for group in secondary if group != primary}
        if primary:
            wanted[primary] = True
        for link in list(self.groups):
            if link.group_name in wanted:
                link.is_primary = wanted.pop(link.group_name)
            else:
                self.groups.remove(link)
        self.groups.extend(
            EmailMessageGroup(group_name=group, is_primary=is_primary) for group, is_primary in wanted.items()
        )


class EmailMessageGroup(Base):
    """Group membership; an email can sit in several folders (e.g. a university internship)."""

    __tablename__ = "email_message_groups"

    email_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_messages.id", ondelete="CASCADE"), primary_key=True
    )
    group_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(default=False)


class GmailSyncState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-mailbox sync cursor and lease; survives restarts so sync resumes where it stopped."""

    __tablename__ = "gmail_sync_states"

    integration_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), unique=True
    )
    history_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=SyncStatus.IDLE)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    initial_sync_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(default=0)
    # When the Gmail push watch ends (push notifications only); renewed during syncs.
    watch_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    integration: Mapped["Integration"] = relationship(back_populates="sync_state")
