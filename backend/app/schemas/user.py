import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.schemas.preferences import UserPreferences


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    setup_completed: bool
    preferences: UserPreferences


class IntegrationStatus(BaseModel):
    """Connection state plus the human-readable reason for the requested scopes."""

    provider: str
    connected: bool
    connection_status: str
    explanation: str
    scopes: list[str]
    last_sync_at: datetime | None = None
    error_message: str | None = None


class PreferencesUpdate(BaseModel):
    """A partial preferences object, deep-merged into the stored preferences and validated."""

    preferences: dict[str, Any] = {}
    setup_completed: bool | None = None
