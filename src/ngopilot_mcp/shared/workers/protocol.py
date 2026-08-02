"""Versioned private worker protocol models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = "1.0"


@dataclass(frozen=True, slots=True)
class WorkerRequest:
    tool_name: str
    operation: str
    job_id: str
    payload: dict[str, Any]
    job_root: str
    app_data_root: str
    resources_root: str
    application_source: str
    protocol_version: str = PROTOCOL_VERSION

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "job_id": self.job_id,
            "payload": self.payload,
            "job_root": self.job_root,
            "app_data_root": self.app_data_root,
            "resources_root": self.resources_root,
            "application_source": self.application_source,
        }
