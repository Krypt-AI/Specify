import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class FollowUpOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    notes: str
    due_at: datetime
    snoozed_until: datetime | None
    status: str
    source: str
    completed_at: datetime | None
    opportunity_id: uuid.UUID | None
    email_message_id: uuid.UUID | None
    overdue: bool = False
    context: str | None = None  # the opportunity or email this is about


class FollowUpCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_at: AwareDatetime
    notes: str = Field("", max_length=2000)
    opportunity_id: uuid.UUID | None = None
    email_id: uuid.UUID | None = None


class FollowUpUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=300)
    due_at: AwareDatetime | None = None
    notes: str | None = Field(None, max_length=2000)


class SnoozeRequest(BaseModel):
    until: AwareDatetime


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationList(BaseModel):
    items: list[NotificationOut]
    unread: int
