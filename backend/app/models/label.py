import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin

GMAIL_LABEL_ROOT = "Specify"
# Roots used under earlier app names; labels found there are renamed to GMAIL_LABEL_ROOT.
LEGACY_LABEL_ROOTS = ("MailUp",)


class LabelOrigin(StrEnum):
    AI = "ai"
    USER = "user"
    SYSTEM = "system"


class Label(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A context label named by the AI (or the user), mirrored in Gmail under Specify/.

    System labels (system_key set) mark message status, such as Needs Review, and are never
    offered to the classifier.
    """

    __tablename__ = "labels"
    __table_args__ = (
        UniqueConstraint("user_id", "normalized_name", name="uq_label_user_name"),
        UniqueConstraint("user_id", "system_key", name="uq_label_user_system_key"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    normalized_name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300), default="")
    system_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[str] = mapped_column(String(8), default=LabelOrigin.AI)
    enabled: Mapped[bool] = mapped_column(default=True)
    gmail_label_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    @property
    def gmail_name(self) -> str:
        return f"{GMAIL_LABEL_ROOT}/{self.name}"
