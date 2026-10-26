import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JsonType, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.label import Label


class ClassificationRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A user-defined rule; it decides an email's group (and optionally its label) before the AI."""

    __tablename__ = "classification_rules"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    conditions: Mapped[dict] = mapped_column(JsonType, default=dict)  # schemas.rule.RuleConditions
    target_group: Mapped[str] = mapped_column(String(32))
    target_label_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("labels.id", ondelete="SET NULL"), nullable=True
    )
    enabled: Mapped[bool] = mapped_column(default=True)

    target_label: Mapped[Label | None] = relationship(lazy="joined")


class ClassificationFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A correction the user made; used to suggest rules, never to silently change behaviour."""

    __tablename__ = "classification_feedback"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("email_messages.id", ondelete="CASCADE"), index=True
    )
    sender_email: Mapped[str] = mapped_column(String(320))
    sender_domain: Mapped[str] = mapped_column(String(255), index=True)
    previous_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    corrected_group: Mapped[str] = mapped_column(String(32))
    previous_label_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("labels.id", ondelete="SET NULL"), nullable=True
    )
    corrected_label_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("labels.id", ondelete="SET NULL"), nullable=True
    )
