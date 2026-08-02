"""Strict public request schemas for ``careflow_government_forms``."""

from __future__ import annotations

import math
import re
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    TypeAdapter,
    field_validator,
)

_TEMPLATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _require_non_blank(value: str, name: str) -> str:
    if not value.strip():
        raise ValueError(f"{name} must not be blank")
    return value


class EmptyInput(StrictModel):
    """An operation payload that intentionally accepts no fields."""


class TextSource(StrictModel):
    kind: Literal["text"]
    text: StrictStr

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _require_non_blank(value, "source text")


class ImageSource(StrictModel):
    kind: Literal["image"]
    image_path: StrictStr

    @field_validator("image_path")
    @classmethod
    def validate_image_path(cls, value: str) -> str:
        return _require_non_blank(value, "image_path")


class ElderProfileSource(StrictModel):
    kind: Literal["elder_profile"]
    elder_profile: dict[StrictStr, Any]

    @field_validator("elder_profile")
    @classmethod
    def validate_profile_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_value(value, "elder_profile")
        return value


ProfileSource: TypeAlias = Annotated[
    TextSource | ImageSource | ElderProfileSource,
    Field(discriminator="kind"),
]


class StartInput(StrictModel):
    template_id: StrictStr
    use_llm: StrictBool
    source_hint: StrictStr | None = None
    source: ProfileSource

    @field_validator("template_id")
    @classmethod
    def validate_template_id(cls, value: str) -> str:
        if not _TEMPLATE_ID.fullmatch(value):
            raise ValueError(
                "template_id must contain only letters, numbers, underscores, or hyphens"
            )
        return value

    @field_validator("source_hint")
    @classmethod
    def validate_source_hint(cls, value: str | None) -> str | None:
        return None if value is None else _require_non_blank(value, "source_hint")


class ReviewInput(StrictModel):
    field_values: dict[StrictStr, StrictStr]
    reviewer: StrictStr | None = None

    @field_validator("reviewer")
    @classmethod
    def validate_reviewer(cls, value: str | None) -> str | None:
        return None if value is None else _require_non_blank(value, "reviewer")


class ListTemplatesCall(StrictModel):
    operation: Literal["list_templates"]
    job_id: None = None
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


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


class ExportCall(StrictModel):
    operation: Literal["export"]
    job_id: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = None
    input: EmptyInput = Field(default_factory=EmptyInput)


ToolRequest: TypeAlias = Annotated[
    ListTemplatesCall | StartCall | StatusCall | ReviewCall | ExportCall,
    Field(discriminator="operation"),
]

REQUEST_ADAPTER = TypeAdapter(ToolRequest)


def validate_request(value: object) -> ToolRequest:
    """Validate an untrusted MCP call without coercing scalar types."""

    return REQUEST_ADAPTER.validate_python(value, strict=True)


def _validate_json_value(value: Any, path: str) -> None:
    if value is None or isinstance(value, (str, int, bool)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} contains a non-finite number")
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
    raise ValueError(f"{path} contains a non-JSON value")
