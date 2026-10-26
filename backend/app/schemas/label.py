import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LabelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    created_by: str
    enabled: bool
    system_key: str | None
    last_used_at: datetime | None
    email_count: int = 0


class LabelCreate(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    description: str = Field("", max_length=300)


class LabelUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=60)
    description: str | None = Field(None, max_length=300)
    enabled: bool | None = None
