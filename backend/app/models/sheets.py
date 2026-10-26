import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonType, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class SyncJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SheetsConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The spreadsheet a user syncs with, and how each worksheet is mapped.

    worksheets: {entity: {"enabled", "title", "direction", "source_of_truth", "columns": {field: header}}}
    """

    __tablename__ = "sheets_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(128))
    spreadsheet_url: Mapped[str] = mapped_column(String(512))
    title: Mapped[str] = mapped_column(String(300), default="")
    worksheets: Mapped[dict] = mapped_column(JsonType, default=dict)
    email_tracker_groups: Mapped[list] = mapped_column(JsonType, default=list)
    auto_sync: Mapped[bool] = mapped_column(default=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class SheetRowState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """What Specify last wrote for one record, so manual edits in Sheets can be told apart."""

    __tablename__ = "sheet_row_states"
    __table_args__ = (UniqueConstraint("connection_id", "entity", "record_id", name="uq_sheet_row"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sheets_connections.id", ondelete="CASCADE"), index=True)
    entity: Mapped[str] = mapped_column(String(32))
    record_id: Mapped[str] = mapped_column(String(64))
    values: Mapped[dict] = mapped_column(JsonType, default=dict)
    excluded: Mapped[bool] = mapped_column(default=False)  # the user chose to stop syncing this record


class SyncJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One synchronization attempt; the sync history the user sees (spec table sync_jobs)."""

    __tablename__ = "sync_jobs"
    __table_args__ = (Index("ix_sync_job_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16), default="sheets")
    entity_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # None = all worksheets
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operation: Mapped[str] = mapped_column(String(16), default="sync")
    status: Mapped[str] = mapped_column(String(16), default=SyncJobStatus.QUEUED)
    trigger: Mapped[str] = mapped_column(String(16), default="manual")  # manual | auto | schedule | retry
    attempt_count: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    summary: Mapped[dict] = mapped_column(JsonType, default=dict)


class SheetConflict(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A cell (or row) that changed in Sheets and that Specify will not overwrite without the user."""

    __tablename__ = "sheet_conflicts"
    __table_args__ = (Index("ix_sheet_conflict_open", "connection_id", "status"),)

    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sheets_connections.id", ondelete="CASCADE"))
    entity: Mapped[str] = mapped_column(String(32))
    record_id: Mapped[str] = mapped_column(String(64))
    field: Mapped[str] = mapped_column(String(64))  # "__row__" when the whole row was deleted in Sheets
    specify_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    sheet_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved
    resolution: Mapped[str | None] = mapped_column(String(16), nullable=True)
