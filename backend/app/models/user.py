import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JsonType, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.email import GmailSyncState


class ConnectionStatus(StrEnum):
    CONNECTED = "connected"
    NEEDS_RECONNECT = "needs_reconnect"


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    google_sub: Mapped[str] = mapped_column(String(64), unique=True)
    preferences: Mapped[dict] = mapped_column(JsonType, default=dict)
    setup_completed: Mapped[bool] = mapped_column(default=False)

    integrations: Mapped[list["Integration"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Integration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A connected external account (Gmail, Google Sheets). Tokens are encrypted at rest."""

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_integration_user_provider"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # "gmail" | "sheets"
    connection_status: Mapped[str] = mapped_column(String(32), default=ConnectionStatus.CONNECTED)
    scopes: Mapped[list] = mapped_column(JsonType, default=list)
    access_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="integrations")
    sync_state: Mapped["GmailSyncState | None"] = relationship(
        back_populates="integration", cascade="all, delete-orphan", uselist=False
    )
