"""Strict public request schemas for ``roster_copilot``."""

from __future__ import annotations

import math
from datetime import date
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _required(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be blank")
    return stripped


def _validate_json(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_json(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string object key")
            _validate_json(item, f"{path}.{key}")
        return
    raise ValueError(f"{path} contains a non-JSON value")


class EmptyInput(StrictModel):
    """An operation input that accepts no fields."""


class StartInput(StrictModel):
    hc_workbook_path: StrictStr = Field(min_length=1)
    escort_workbook_path: StrictStr = Field(min_length=1)
    week_start: StrictStr
    changes: list[dict[StrictStr, Any]] = Field(default_factory=list)

    @field_validator("hc_workbook_path", "escort_workbook_path")
    @classmethod
    def validate_path_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("workbook paths must not be blank")
        return value

    @field_validator("week_start")
    @classmethod
    def validate_week_start(cls, value: str) -> str:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                "week_start must be an ISO date in YYYY-MM-DD form"
            ) from exc
        if parsed.isoformat() != value:
            raise ValueError("week_start must be an ISO date in YYYY-MM-DD form")
        return value

    @field_validator("changes")
    @classmethod
    def validate_changes_json(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _validate_json(value, "changes")
        return value


EDITABLE_ENTRY_FIELDS = frozenset(
    {
        "entry_id",
        "worker_id",
        "schedule_date",
        "period",
        "session_index",
        "start_time",
        "end_time",
        "notes",
    }
)


class ReviewInput(StrictModel):
    source_version_id: StrictStr
    content_hash: StrictStr
    idempotency_key: StrictStr
    actor: StrictStr
    action: Literal["approve", "reject", "edit"]
    audit_id: StrictStr
    audit_ids: list[StrictStr] = Field(default_factory=list)
    note: StrictStr | None = None
    override_note: StrictStr | None = None
    edited_entry: dict[StrictStr, Any] | None = None

    @field_validator(
        "source_version_id",
        "content_hash",
        "idempotency_key",
        "actor",
        "audit_id",
    )
    @classmethod
    def validate_required_identifiers(cls, value: str, info: Any) -> str:
        return _required(value, info.field_name)

    @field_validator("note", "override_note")
    @classmethod
    def normalize_optional_note(cls, value: str | None) -> str | None:
        return None if value is None or not value.strip() else value.strip()

    @field_validator("audit_ids")
    @classmethod
    def canonical_audit_ids(cls, values: list[str]) -> list[str]:
        return sorted({_required(value, "audit_ids item") for value in values})

    @field_validator("edited_entry")
    @classmethod
    def validate_edited_entry(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        unknown = sorted(set(value) - EDITABLE_ENTRY_FIELDS)
        if unknown:
            raise ValueError(f"edited_entry contains non-editable fields: {unknown}")
        entry_id = value.get("entry_id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            raise ValueError("edited_entry.entry_id is required")
        projected = dict(value)
        projected["entry_id"] = entry_id.strip()
        _validate_json(projected, "edited_entry")
        return projected

    @model_validator(mode="after")
    def validate_action_requirements(self) -> "ReviewInput":
        if self.action in {"reject", "edit"} and not self.note:
            raise ValueError(f"{self.action} requires note")
        if self.action == "edit" and not self.edited_entry:
            raise ValueError("edit requires edited_entry")
        if self.action != "edit" and self.edited_entry is not None:
            raise ValueError("only edit may provide edited_entry")
        if self.action != "edit" and self.override_note is not None:
            raise ValueError("only edit may provide override_note")
        return self


class RevalidateInput(StrictModel):
    source_version_id: StrictStr
    content_hash: StrictStr

    @field_validator("source_version_id", "content_hash")
    @classmethod
    def validate_identifiers(cls, value: str, info: Any) -> str:
        return _required(value, info.field_name)


class PublishInput(RevalidateInput):
    actor: StrictStr

    @field_validator("actor")
    @classmethod
    def validate_actor(cls, value: str) -> str:
        return _required(value, "actor")


class GetPublishedInput(StrictModel):
    publication_id: StrictStr

    @field_validator("publication_id")
    @classmethod
    def validate_publication_id(cls, value: str) -> str:
        return _required(value, "publication_id")


class StartCall(StrictModel):
    operation: Literal["start"]
    job_id: None = None
    request_id: StrictStr | None = None
    input: StartInput


class StatusCall(StrictModel):
    operation: Literal["status"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


class ReviewCall(StrictModel):
    operation: Literal["review"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: ReviewInput


class RevalidateCall(StrictModel):
    operation: Literal["revalidate"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: RevalidateInput


class ExportCall(StrictModel):
    operation: Literal["export"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


class PublishCall(StrictModel):
    operation: Literal["publish"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: PublishInput


class GetPublishedCall(StrictModel):
    operation: Literal["get_published"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: GetPublishedInput


ToolRequest: TypeAlias = Annotated[
    StartCall
    | StatusCall
    | ReviewCall
    | RevalidateCall
    | ExportCall
    | PublishCall
    | GetPublishedCall,
    Field(discriminator="operation"),
]
REQUEST_ADAPTER = TypeAdapter(ToolRequest)


def validate_request(value: object) -> ToolRequest:
    return REQUEST_ADAPTER.validate_python(value, strict=True)
