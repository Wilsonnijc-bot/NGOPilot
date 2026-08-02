"""Strict public request schemas for ``careflow_meeting_notes``."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    field_validator,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EmptyInput(_StrictModel):
    """An operation payload that intentionally accepts no fields."""


class StartInput(_StrictModel):
    title: StrictStr = Field(min_length=1)
    mode: Literal["home_visit", "internal_meeting"]
    audio_path: StrictStr = Field(min_length=1)
    template_path: StrictStr = Field(min_length=1)
    note: StrictStr | None = None

    @field_validator("title")
    @classmethod
    def require_non_blank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must not be blank")
        return value


class ReviewInput(_StrictModel):
    slot_content_final: dict[StrictStr, Any]
    reviewer: StrictStr | None = None

    @field_validator("slot_content_final")
    @classmethod
    def require_json_compatible_values(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_value(value)
        return value


class StartRequest(_StrictModel):
    operation: Literal["start"]
    job_id: None = None
    request_id: StrictStr | None = None
    input: StartInput


class StatusRequest(_StrictModel):
    operation: Literal["status"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


class ReviewRequest(_StrictModel):
    operation: Literal["review"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: ReviewInput


class ExportRequest(_StrictModel):
    operation: Literal["export"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


class BurnRequest(_StrictModel):
    operation: Literal["burn"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


MeetingNotesRequest: TypeAlias = Annotated[
    StartRequest | StatusRequest | ReviewRequest | ExportRequest | BurnRequest,
    Field(discriminator="operation"),
]
REQUEST_ADAPTER = TypeAdapter(MeetingNotesRequest)


def parse_request(value: object) -> MeetingNotesRequest:
    """Validate an untrusted MCP request without coercing scalar types."""

    return REQUEST_ADAPTER.validate_python(value, strict=True)


def _validate_json_value(value: Any, path: str = "slot_content_final") -> None:
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number at {path}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            _validate_json_value(item, f"{path}.{key}")
        return
    raise ValueError(f"{path} contains a non-JSON value at {path}")
