"""Concrete shared runtime used by independent tool controllers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..config import Settings
from .errors import ToolError
from .files import ArtifactService, FileService
from .jobs import JobRecord, JobStore
from .jsonutil import jsonable
from .tool_api import (
    ArtifactRef,
    OperationHandle,
    ToolExecution,
    WorkerName,
)
from .workers import WorkerClient


class Runtime:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.jobs = JobStore(settings.database_path)
        self.files = FileService(settings)
        self.artifacts = ArtifactService(self.files, self.jobs)
        self.workers = WorkerClient(settings)

    def create_job(
        self,
        *,
        tool_name: str,
        request_id: str | None,
        input_payload: dict[str, Any],
    ) -> JobRecord:
        job = self.jobs.create_job(
            tool_name=tool_name,
            request_id=request_id,
            input_payload=input_payload,
        )
        self.files.ensure_job_directories(job)
        self._write_manifest(job)
        return job

    def get_job(self, *, tool_name: str, job_id: str) -> JobRecord:
        return self.jobs.get_job(tool_name=tool_name, job_id=job_id)

    def stage_file(
        self,
        *,
        job: JobRecord,
        role: str,
        source_path: str | Path,
        allowed_extensions: tuple[str, ...],
        max_bytes: int | None = None,
        content_kind: str | None = None,
    ) -> Path:
        return self.files.stage_file(
            job=job,
            role=role,
            source_path=source_path,
            allowed_extensions=allowed_extensions,
            max_bytes=max_bytes,
            content_kind=content_kind,
        )

    def begin_operation(
        self,
        *,
        job: JobRecord,
        operation: str,
        request_id: str | None,
        payload: dict[str, Any],
    ) -> OperationHandle:
        handle = self.jobs.begin_operation(
            job=job,
            operation=operation,
            request_id=request_id,
            payload=payload,
        )
        if handle.replay is None:
            job = self.jobs.update_job(
                job_id=job.job_id,
                state="running",
                native_status=job.native_status,
                result=job.result,
                native_refs=job.native_refs,
                warnings=job.warnings,
                next_operations=[],
                error=None,
            )
            self._write_manifest(job)
        return handle

    async def call_worker(
        self,
        *,
        worker: WorkerName,
        tool_name: str,
        operation: str,
        job: JobRecord,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.workers.call(
            worker=worker,
            tool_name=tool_name,
            operation=operation,
            job_id=job.job_id,
            payload=payload,
            job_root=self.files.ensure_job_directories(job),
        )

    async def call_worker_discovery(
        self,
        *,
        worker: WorkerName,
        tool_name: str,
        operation: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        discovery_root = self.settings.state_root / "discovery"
        discovery_root.mkdir(parents=True, exist_ok=True)
        try:
            discovery_root.chmod(0o700)
        except OSError:
            pass
        with tempfile.TemporaryDirectory(
            prefix=f"{tool_name}-",
            dir=discovery_root,
        ) as temporary:
            return await self.workers.call(
                worker=worker,
                tool_name=tool_name,
                operation=operation,
                job_id="discovery",
                payload=payload,
                job_root=Path(temporary),
            )

    def promote_artifact(
        self,
        *,
        job: JobRecord,
        source_path: str | Path,
        kind: str,
        media_type: str,
        expected_extensions: tuple[str, ...],
    ) -> ArtifactRef:
        return self.artifacts.promote(
            job=job,
            source_path=source_path,
            kind=kind,
            media_type=media_type,
            expected_extensions=expected_extensions,
        )

    def complete_operation(
        self,
        *,
        job: JobRecord,
        handle: OperationHandle,
        state: str,
        native_status: str | None,
        result: dict[str, Any],
        native_refs: dict[str, Any] | None = None,
        artifacts: list[ArtifactRef | dict[str, Any]] | None = None,
        warnings: list[str | dict[str, Any]] | None = None,
        next_operations: list[str] | None = None,
    ) -> ToolExecution:
        stored = self.jobs.update_job(
            job_id=job.job_id,
            state=state,
            native_status=native_status,
            result=jsonable(result),
            native_refs=jsonable(native_refs or job.native_refs),
            warnings=jsonable(warnings or []),
            next_operations=next_operations or [],
            error=None,
        )
        execution = self._execution(
            stored,
            operation=handle.operation,
            extra_artifacts=artifacts,
        )
        self.jobs.complete_operation(handle, execution.as_dict())
        self._write_manifest(stored)
        return execution

    def fail_operation(
        self,
        *,
        job: JobRecord,
        handle: OperationHandle,
        error: Exception,
        state: str | None = None,
    ) -> ToolExecution:
        tool_error = (
            error
            if isinstance(error, ToolError)
            else ToolError(
                "NATIVE_OPERATION_FAILED",
                str(error) or type(error).__name__,
                native_message=str(error),
            )
        )
        failed_state = state or ("failed" if handle.operation == "start" else job.state)
        stored = self.jobs.update_job(
            job_id=job.job_id,
            state=failed_state,
            native_status=job.native_status,
            result=job.result,
            native_refs=job.native_refs,
            warnings=job.warnings,
            next_operations=[] if handle.operation == "start" else job.next_operations,
            error=tool_error.as_dict(),
        )
        execution = self._execution(stored, operation=handle.operation)
        self.jobs.fail_operation(
            handle,
            error=tool_error.as_dict(),
            response=execution.as_dict(),
        )
        self._write_manifest(stored)
        return execution

    def job_execution(
        self,
        *,
        job: JobRecord,
        operation: str,
    ) -> ToolExecution:
        current = self.jobs.get_job(tool_name=job.tool_name, job_id=job.job_id)
        return self._execution(current, operation=operation)

    def replay_execution(self, handle: OperationHandle) -> ToolExecution | None:
        if handle.replay is None:
            return None
        payload = dict(handle.replay)
        payload.pop("schema_version", None)
        artifacts = payload.get("artifacts") or []
        payload["artifacts"] = artifacts
        return ToolExecution(**payload)

    def _execution(
        self,
        job: JobRecord,
        *,
        operation: str,
        extra_artifacts: list[ArtifactRef | dict[str, Any]] | None = None,
    ) -> ToolExecution:
        artifacts: list[ArtifactRef | dict[str, Any]] = [
            self.artifacts.verify_registered(job=job, artifact=artifact)
            for artifact in self.jobs.list_artifacts(job_id=job.job_id)
        ]
        if extra_artifacts:
            known = {
                item.path if isinstance(item, ArtifactRef) else item.get("path")
                for item in artifacts
            }
            artifacts.extend(
                item
                for item in extra_artifacts
                if (item.path if isinstance(item, ArtifactRef) else item.get("path"))
                not in known
            )
        return ToolExecution(
            tool=job.tool_name,
            operation=operation,
            job_id=job.job_id,
            state=job.state,
            native_status=job.native_status,
            native_refs=job.native_refs,
            result=job.result,
            artifacts=artifacts,
            next_operations=job.next_operations,
            warnings=job.warnings,
            error=job.error,
        )

    def _write_manifest(self, job: JobRecord) -> None:
        root = self.files.ensure_job_directories(job)
        artifacts = [
            artifact.as_dict()
            for artifact in self.jobs.list_artifacts(job_id=job.job_id)
        ]
        payload = {
            "schema_version": "1.0",
            "job_id": job.job_id,
            "tool": job.tool_name,
            "state": job.state,
            "native_status": job.native_status,
            "native_refs": job.native_refs,
            "artifacts": artifacts,
            "warnings": job.warnings,
            "error": job.error,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }
        target = root / "manifest.json"
        temporary = root / ".manifest.json.tmp"
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
