import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import MailGroup
from app.schemas.preferences import clean_entries


class RuleConditions(BaseModel):
    """All non-empty condition lists must match; within a list, any entry may match."""

    model_config = ConfigDict(extra="forbid")

    sender_emails: list[str] = []
    sender_domains: list[str] = []
    subject_contains: list[str] = []
    body_contains: list[str] = []

    @field_validator("*")
    @classmethod
    def normalize_entries(cls, values: list[str]) -> list[str]:
        return clean_entries(values)

    @model_validator(mode="after")
    def _not_empty(self) -> "RuleConditions":
        if not any((self.sender_emails, self.sender_domains, self.subject_contains, self.body_contains)):
            raise ValueError("A rule needs at least one condition.")
        return self


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    conditions: RuleConditions
    target_group: MailGroup
    target_label_id: uuid.UUID | None = None
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    conditions: RuleConditions | None = None
    target_group: MailGroup | None = None
    target_label_id: uuid.UUID | None = None
    enabled: bool | None = None


class RuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    conditions: RuleConditions
    target_group: MailGroup
    target_label_id: uuid.UUID | None
    enabled: bool
    created_at: datetime


class RuleSuggestion(BaseModel):
    """A rule proposed from repeated corrections; it is only created if the user accepts it."""

    reason: str
    rule: RuleCreate
