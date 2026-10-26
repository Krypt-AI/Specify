import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JsonType, TimestampMixin, UTCDateTime, UUIDPrimaryKeyMixin


class RunStatus(StrEnum):
    RUNNING = "running"
    WAITING = "waiting"  # for a decision, an approval, a delay, or the global pause
    RETRYING = "retrying"
    PAUSED = "paused"  # paused by the user
    COMPLETED = "completed"
    FAILED = "failed"  # retries exhausted: kept for inspection and manual retry (dead letter)
    CANCELLED = "cancelled"


ACTIVE_RUN_STATUSES = (RunStatus.RUNNING, RunStatus.WAITING, RunStatus.RETRYING, RunStatus.PAUSED)


class WorkflowDefinition(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A workflow graph: {"nodes": [{id, type, config, position}], "edges": [{id, source, target, handle}]}."""

    __tablename__ = "workflow_definitions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    definition_json: Mapped[dict] = mapped_column(JsonType, default=dict)
    trigger_type: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(default=False)
    is_default: Mapped[bool] = mapped_column(default=False)
    is_template: Mapped[bool] = mapped_column(default=False)  # saved templates never run
    version: Mapped[int] = mapped_column(default=1)


class WorkflowRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        # The idempotency key: one run per workflow per triggering event (such as one email).
        UniqueConstraint("workflow_definition_id", "trigger_event_id", name="uq_run_trigger"),
        Index("ix_run_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    workflow_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workflow_definitions.id", ondelete="CASCADE"), index=True
    )
    # The graph as it was when the run started, so later edits never break a paused run.
    definition_snapshot: Mapped[dict] = mapped_column(JsonType, default=dict)
    workflow_version: Mapped[int] = mapped_column(default=1)
    trigger_event_id: Mapped[str] = mapped_column(String(100))
    is_test: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.RUNNING)
    current_node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    waiting_for: Mapped[dict | None] = mapped_column(JsonType, nullable=True)
    resume_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    execution_context: Mapped[dict] = mapped_column(JsonType, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class WorkflowNodeRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "workflow_node_runs"

    workflow_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    node_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))  # completed | skipped | waiting | failed | retrying | simulated
    attempt: Mapped[int] = mapped_column(default=1)
    input_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    output_summary: Mapped[dict] = mapped_column(JsonType, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)


class FollowUpStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class FollowUpTask(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reminder: recruiter follow-ups, interviews, deadlines, exam dates and renewals."""

    __tablename__ = "follow_up_tasks"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_follow_up_key"),
        Index("ix_follow_up_user_due", "user_id", "status", "due_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=True)
    email_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("email_messages.id", ondelete="SET NULL"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="follow_up")
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str] = mapped_column(Text, default="")
    due_at: Mapped[datetime] = mapped_column(UTCDateTime)
    snoozed_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default=FollowUpStatus.OPEN)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | workflow | decision | email
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_notification_key"),
        Index("ix_notification_user_read", "user_id", "read_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
