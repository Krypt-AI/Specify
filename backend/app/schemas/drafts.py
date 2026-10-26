import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DraftEmailRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subject: str
    sender_email: str
    gmail_thread_url: str
    primary_group: str | None


class DraftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: DraftEmailRef
    opportunity_id: uuid.UUID | None
    scenario: str
    decision: str | None
    tone: str
    instructions: str
    recipient: str
    subject: str
    body: str
    generated_by: str | None
    warnings: list[str]
    status: str
    edited_by_user: bool
    error: str | None
    gmail_draft_id: str | None
    gmail_message_id: str | None
    gmail_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DraftUpdate(BaseModel):
    subject: str | None = Field(None, min_length=1, max_length=500)
    body: str | None = Field(None, min_length=1, max_length=20_000)


class DraftRequest(BaseModel):
    scenario: str | None = None
    tone: str | None = Field(None, max_length=40)
    instructions: str = Field("", max_length=1000)


class TemplateOut(BaseModel):
    scenario: str
    label: str
    instructions: str
    body: str
    use_ai: bool
    customized: bool


class TemplateUpdate(BaseModel):
    instructions: str = Field("", max_length=2000)
    body: str = Field("", max_length=5000)
    use_ai: bool = True
