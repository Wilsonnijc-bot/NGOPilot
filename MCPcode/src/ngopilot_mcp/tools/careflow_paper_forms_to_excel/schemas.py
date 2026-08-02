"""Strict public request schemas for the paper-forms MCP tool."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
)

FIELD_KEYS = (
    "elder_name",
    "elder_age",
    "elder_gender",
    "elder_phone",
    "elder_address",
    "living_alone",
    "visit_date",
    "volunteer_name",
    "duration_minutes",
    "mood",
    "health_concerns",
    "follow_up_needed",
    "follow_up_note",
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


class StartInput(StrictModel):
    title: StrictStr
    image_paths: Annotated[list[StrictStr], Field(min_length=1)]
    volunteer_team: StrictStr | None = None
    visit_date: StrictStr | None = None
    note: StrictStr | None = None
    auto_complete: StrictBool = False

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _non_blank(value, "title")

    @field_validator("image_paths")
    @classmethod
    def validate_image_path_strings(cls, values: list[str]) -> list[str]:
        for value in values:
            _non_blank(value, "image path")
        return values

    @field_validator("visit_date")
    @classmethod
    def validate_visit_date(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "visit_date must be an ISO date in YYYY-MM-DD form"
            ) from exc
        if parsed.isoformat() != value:
            raise ValueError("visit_date must be an ISO date in YYYY-MM-DD form")
        return value


class EmptyInput(StrictModel):
    pass


class FinalFields(StrictModel):
    # CareFlow accepts JSON values here and owns field-level domain handling.
    # Requiring every key preserves its complete-review correction behavior.
    elder_name: Any
    elder_age: Any
    elder_gender: Any
    elder_phone: Any
    elder_address: Any
    living_alone: Any
    visit_date: Any
    volunteer_name: Any
    duration_minutes: Any
    mood: Any
    health_concerns: Any
    follow_up_needed: Any
    follow_up_note: Any


class RecordReview(StrictModel):
    record_id: Annotated[StrictInt, Field(gt=0)]
    final_fields: FinalFields
    reviewer: StrictStr | None = None


class ReviewInput(StrictModel):
    reviews: Annotated[list[RecordReview], Field(min_length=1)]

    @field_validator("reviews")
    @classmethod
    def validate_unique_records(cls, values: list[RecordReview]) -> list[RecordReview]:
        record_ids = [item.record_id for item in values]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("each record_id may appear only once per review operation")
        return values


class StartCall(StrictModel):
    operation: Literal["start"]
    job_id: None = None
    request_id: StrictStr | None = None
    input: StartInput


class StatusCall(StrictModel):
    operation: Literal["status"]
    job_id: StrictStr
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


class ReviewCall(StrictModel):
    operation: Literal["review"]
    job_id: StrictStr
    request_id: StrictStr | None = None
    input: ReviewInput


class ExportCall(StrictModel):
    operation: Literal["export"]
    job_id: StrictStr
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


ToolRequest: TypeAlias = Annotated[
    StartCall | StatusCall | ReviewCall | ExportCall,
    Field(discriminator="operation"),
]

REQUEST_ADAPTER = TypeAdapter(ToolRequest)


def validate_request(data: dict[str, Any]) -> ToolRequest:
    """Validate a JSON-compatible MCP call as an operation-specific request."""

    return REQUEST_ADAPTER.validate_python(data, strict=True)
