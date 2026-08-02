"""Stable MCP-boundary errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ToolError(Exception):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    native_code: str | None = None
    native_message: str | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "native_code": self.native_code,
            "native_message": self.native_message,
            "details": self.details,
        }


class InvalidRequestError(ToolError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__("INVALID_REQUEST", message, details=details or {})


class UnknownJobError(ToolError):
    def __init__(self, job_id: str):
        super().__init__(
            "UNKNOWN_JOB",
            f"No job exists for job_id '{job_id}'.",
            details={"job_id": job_id},
        )


class InvalidJobStateError(ToolError):
    def __init__(self, state: str, operation: str):
        super().__init__(
            "INVALID_JOB_STATE",
            f"Operation '{operation}' is not valid while the job is '{state}'.",
            details={"state": state, "operation": operation},
        )


class IdempotencyKeyReusedError(ToolError):
    def __init__(self, request_id: str):
        super().__init__(
            "IDEMPOTENCY_KEY_REUSED",
            "The request_id was already used with a different payload.",
            details={"request_id": request_id},
        )
