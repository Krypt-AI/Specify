import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ConfigFieldOut(BaseModel):
    key: str
    label: str
    kind: str
    default: object = None
    options: list[str] = []
    minimum: float | None = None
    maximum: float | None = None
    help: str = ""


class NodeTypeOut(BaseModel):
    key: str
    label: str
    category: str
    description: str
    handles: list[str]
    fields: list[ConfigFieldOut]
    trigger: bool
    requires_email: bool
    retryable: bool
    defaults: dict


class RunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_definition_id: uuid.UUID
    workflow_name: str = ""
    trigger_event_id: str
    is_test: bool
    status: str
    current_node_id: str | None
    waiting_for: dict | None
    resume_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class NodeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    node_id: str
    node_type: str
    status: str
    attempt: int
    input_summary: dict
    output_summary: dict
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    error_category: str | None


class RunDetail(RunSummary):
    definition_snapshot: dict
    node_runs: list[NodeRunOut] = []
    last_error: dict | None = None


class WorkflowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    definition_json: dict
    trigger_type: str
    enabled: bool
    is_default: bool
    is_template: bool
    version: int
    created_at: datetime
    updated_at: datetime
    problems: list[str] = []
    last_run: RunSummary | None = None
    waiting_runs: int = 0
    failed_runs: int = 0


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=1000)
    template: str | None = None  # a built-in template key or a saved template's id
    definition_json: dict | None = None


class WorkflowSave(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=1000)
    definition_json: dict


class TemplateOut(BaseModel):
    key: str
    name: str
    description: str
    built_in: bool


class TestRunRequest(BaseModel):
    email_id: uuid.UUID | None = None


class EnableRequest(BaseModel):
    enabled: bool
