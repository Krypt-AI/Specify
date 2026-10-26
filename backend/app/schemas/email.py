import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import MailGroup
from app.schemas.recruitment import OpportunityRef


class LabelRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class EmailSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    gmail_thread_url: str
    sender_name: str
    sender_email: str
    subject: str
    snippet: str
    received_at: datetime
    is_unread: bool
    primary_group: MailGroup | None
    secondary_groups: list[MailGroup]
    label: LabelRef | None
    label_suggestion: dict | None
    confidence: float | None
    processing_status: str
    is_suspicious: bool
    reply_required: bool
    opportunity: OpportunityRef | None


class EmailDetail(EmailSummary):
    reply_to: str | None
    recipients: list[dict]
    body_text: str
    body_truncated: bool
    body_purged_at: datetime | None = None
    attachments: list[dict]
    classification_source: str | None
    classification_explanation: str | None
    recommended_action: str | None
    suspicious_reasons: list[str]
    extracted_data: dict
    processing_error: str | None
    classified_at: datetime | None
    recruitment_note: str | None


class EmailPage(BaseModel):
    items: list[EmailSummary]
    total: int
    page: int
    page_size: int


class ClassificationUpdate(BaseModel):
    """The user's confirmation or correction. Use label_id or new_label_name, or neither for no label."""

    primary_group: MailGroup
    secondary_groups: list[MailGroup] = []
    label_id: uuid.UUID | None = None
    new_label_name: str | None = Field(None, min_length=2, max_length=60)
    is_suspicious: bool | None = None

    @model_validator(mode="after")
    def _one_label_source(self) -> "ClassificationUpdate":
        if self.label_id and self.new_label_name:
            raise ValueError("Choose an existing label or a new label name, not both.")
        return self


class EmailStats(BaseModel):
    total: int
    unread: int
    pending: int
    needs_review: int
    failed: int
    suspicious: int
    by_group: dict[str, int]
    last_gmail_sync_at: datetime | None


class SyncStatusOut(BaseModel):
    connected: bool
    status: str
    last_synced_at: datetime | None
    initial_sync_completed_at: datetime | None
    last_error: str | None
    queued_emails: int
