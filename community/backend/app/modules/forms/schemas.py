import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["synchrohq.form/v1"]
    data_schema: dict[str, Any]
    ui_schema: dict[str, Any]
    translations: dict[str, dict[str, str]]


class FormCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    territory_id: uuid.UUID
    required_clearance: int = Field(default=0, ge=0)
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)


class FormRead(FormCreate):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    tenant_id: uuid.UUID
    active: bool
    archived: bool
    actions: dict[str, bool] = Field(default_factory=dict)


class VersionRead(Envelope):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    form_id: uuid.UUID
    version: int
    status: Literal["DRAFT", "PUBLISHED", "RETIRED"]
    created_at: datetime
    published_at: datetime | None
    published_by: uuid.UUID | None
    retired_at: datetime | None


class Answers(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: dict[str, Any]


class ValidationIssue(BaseModel):
    path: str
    code: str
    message_key: str


class ValidationResult(BaseModel):
    valid: bool
    errors: list[ValidationIssue]
