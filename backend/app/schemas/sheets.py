import re
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import MailGroup
from app.services.sheets.mapping import SPECS

EntityKey = Literal["companies", "opportunities", "applications", "activity", "emails"]
_INVALID_TITLE = re.compile(r"[\[\]*?/\\:]")


class WorksheetConfig(BaseModel):
    enabled: bool
    title: str = Field(min_length=1, max_length=100)
    direction: Literal["export", "two_way"] = "export"
    source_of_truth: Literal["database", "sheets"] = "database"
    columns: dict[str, str]

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        value = value.strip()
        if _INVALID_TITLE.search(value):
            raise ValueError("Worksheet names cannot contain [ ] * ? / \\ or :")
        return value


class SheetsSettings(BaseModel):
    worksheets: dict[EntityKey, WorksheetConfig]
    email_tracker_groups: list[MailGroup] = []
    auto_sync: bool = True

    @model_validator(mode="after")
    def valid_mapping(self) -> "SheetsSettings":
        titles = [w.title.lower() for w in self.worksheets.values() if w.enabled]
        if len(titles) != len(set(titles)):
            raise ValueError("Each enabled worksheet needs its own name.")
        for entity, worksheet in self.worksheets.items():
            spec = SPECS[entity]
            known = {f.key for f in spec.fields}
            worksheet.columns = {k: v.strip() for k, v in worksheet.columns.items() if k in known and v.strip()}
            if spec.id_field not in worksheet.columns:
                raise ValueError(f"{spec.title}: the {spec.fields[0].header} column must be mapped.")
            headers = [h.lower() for h in worksheet.columns.values()]
            if len(headers) != len(set(headers)):
                raise ValueError(f"{spec.title}: two fields are mapped to the same column.")
            if not spec.two_way:
                worksheet.direction, worksheet.source_of_truth = "export", "database"
        return self


class FieldInfo(BaseModel):
    key: str
    header: str
    importable: bool


class SpreadsheetInfo(BaseModel):
    id: str
    url: str
    title: str


class SyncJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    trigger: str
    attempt_count: int
    last_error: str | None
    summary: dict
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class SheetsStatus(BaseModel):
    connected: bool
    spreadsheet: SpreadsheetInfo | None
    settings: SheetsSettings | None
    fields: dict[str, list[FieldInfo]]
    two_way_capable: dict[str, bool]
    open_conflicts: int
    last_job: SyncJobOut | None


class SpreadsheetSelect(BaseModel):
    spreadsheet: str = Field(min_length=10, max_length=500, description="Spreadsheet URL or ID")


class SpreadsheetCreate(BaseModel):
    title: str = Field("Specify Recruitment Tracker", min_length=1, max_length=200)


class ConflictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity: str
    record_id: str
    field: str
    field_label: str = ""
    specify_value: str | None
    sheet_value: str | None
    reason: str
    created_at: datetime


class ConflictResolve(BaseModel):
    resolution: Literal["keep_specify", "keep_sheet", "restore", "stop_syncing"]
