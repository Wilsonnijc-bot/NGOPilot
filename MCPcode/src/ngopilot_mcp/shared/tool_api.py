"""Stable interface between the host, shared runtime, and independent tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

WorkerName = Literal["careflow", "rostercopiilot"]


@dataclass(frozen=True, slots=True)
class ToolManifest:
    name: str
    description: str
    worker: WorkerName
    operations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ToolCall:
    operation: str
    job_id: str | None = None
    request_id: str | None = None
    input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    kind: str
    path: str
    media_type: str
    size_bytes: int
    sha256: str
    artifact_id: str | None = None
    native_path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "path": self.path,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "native_path": self.native_path,
        }


@dataclass(frozen=True, slots=True)
class OperationHandle:
    operation_id: str
    job_id: str
    operation: str
    request_id: str
    request_hash: str
    replay: dict[str, Any] | None = None


@dataclass(slots=True)
class ToolExecution:
    operation: str
    job_id: str | None
    state: str
    result: dict[str, Any] = field(default_factory=dict)
    tool: str = ""
    native_status: str | None = None
    native_refs: dict[str, Any] = field(default_factory=dict)
    artifacts: list[ArtifactRef | dict[str, Any]] = field(default_factory=list)
    next_operations: list[str] = field(default_factory=list)
    warnings: list[str | dict[str, Any]] = field(default_factory=list)
    error: dict[str, Any] | None = None
    schema_version: str = "1.0"

    def as_dict(self) -> dict[str, Any]:
        artifacts = [
            item.as_dict() if isinstance(item, ArtifactRef) else item
            for item in self.artifacts
        ]
        return {
            "schema_version": self.schema_version,
            "tool": self.tool,
            "operation": self.operation,
            "job_id": self.job_id,
            "state": self.state,
            "native_status": self.native_status,
            "native_refs": self.native_refs,
            "result": self.result,
            "artifacts": artifacts,
            "next_operations": self.next_operations,
            "warnings": self.warnings,
            "error": self.error,
        }


@runtime_checkable
class ToolRuntime(Protocol):
    def create_job(
        self,
        *,
        tool_name: str,
        request_id: str | None,
        input_payload: dict[str, Any],
    ) -> Any: ...

    def get_job(self, *, tool_name: str, job_id: str) -> Any: ...

    def stage_file(
        self,
        *,
        job: Any,
        role: str,
        source_path: str | Path,
        allowed_extensions: tuple[str, ...],
        max_bytes: int | None = None,
        content_kind: str | None = None,
    ) -> Path: ...

    def begin_operation(
        self,
        *,
        job: Any,
        operation: str,
        request_id: str | None,
        payload: dict[str, Any],
    ) -> OperationHandle: ...

    async def call_worker(
        self,
        *,
        worker: WorkerName,
        tool_name: str,
        operation: str,
        job: Any,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def call_worker_discovery(
        self,
        *,
        worker: WorkerName,
        tool_name: str,
        operation: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def promote_artifact(
        self,
        *,
        job: Any,
        source_path: str | Path,
        kind: str,
        media_type: str,
        expected_extensions: tuple[str, ...],
    ) -> ArtifactRef: ...

    def complete_operation(
        self,
        *,
        job: Any,
        handle: OperationHandle,
        state: str,
        native_status: str | None,
        result: dict[str, Any],
        native_refs: dict[str, Any] | None = None,
        artifacts: list[ArtifactRef | dict[str, Any]] | None = None,
        warnings: list[str | dict[str, Any]] | None = None,
        next_operations: list[str] | None = None,
    ) -> ToolExecution: ...

    def fail_operation(
        self,
        *,
        job: Any,
        handle: OperationHandle,
        error: Exception,
        state: str | None = None,
    ) -> ToolExecution: ...

    def job_execution(
        self,
        *,
        job: Any,
        operation: str,
    ) -> ToolExecution: ...
