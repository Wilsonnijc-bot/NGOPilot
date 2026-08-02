"""SQLite-backed MCP job, operation, and artifact registry."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ..errors import (
    IdempotencyKeyReusedError,
    ToolError,
    UnknownJobError,
)
from ..jsonutil import canonical_json, payload_hash
from ..tool_api import ArtifactRef, OperationHandle


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default


@dataclass(slots=True)
class JobRecord:
    job_id: str
    tool_name: str
    state: str
    native_status: str | None
    input_payload: dict[str, Any]
    result: dict[str, Any] = field(default_factory=dict)
    native_refs: dict[str, Any] = field(default_factory=dict)
    warnings: list[str | dict[str, Any]] = field(default_factory=list)
    next_operations: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    created_at: str = ""
    updated_at: str = ""


class JobStore:
    def __init__(self, database_path: Path):
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    state TEXT NOT NULL,
                    native_status TEXT,
                    input_json TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    native_refs_json TEXT NOT NULL DEFAULT '{}',
                    warnings_json TEXT NOT NULL DEFAULT '[]',
                    next_operations_json TEXT NOT NULL DEFAULT '[]',
                    error_json TEXT,
                    start_request_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tool_name, start_request_id)
                );

                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    operation TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    response_json TEXT,
                    error_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id, request_id)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(job_id),
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    native_path TEXT,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(job_id, path)
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_tool
                    ON jobs(tool_name, updated_at);
                CREATE INDEX IF NOT EXISTS idx_operations_job
                    ON operations(job_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_artifacts_job
                    ON artifacts(job_id, created_at);
                """
            )

    def create_job(
        self,
        *,
        tool_name: str,
        input_payload: dict[str, Any],
        request_id: str | None = None,
    ) -> JobRecord:
        input_json = canonical_json(input_payload)
        input_digest = payload_hash(input_payload)
        now = _now()
        with self._lock, self._connect() as db:
            if request_id:
                row = db.execute(
                    "SELECT * FROM jobs WHERE tool_name = ? AND start_request_id = ?",
                    (tool_name, request_id),
                ).fetchone()
                if row:
                    if row["input_hash"] != input_digest:
                        raise IdempotencyKeyReusedError(request_id)
                    return self._row_to_job(row)

            job_id = f"job_{uuid4().hex}"
            db.execute(
                """
                INSERT INTO jobs (
                    job_id, tool_name, state, input_json, input_hash,
                    start_request_id, created_at, updated_at
                ) VALUES (?, ?, 'accepted', ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    tool_name,
                    input_json,
                    input_digest,
                    request_id,
                    now,
                    now,
                ),
            )
            row = db.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            assert row is not None
            return self._row_to_job(row)

    def get_job(self, *, tool_name: str, job_id: str) -> JobRecord:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM jobs WHERE job_id = ? AND tool_name = ?",
                (job_id, tool_name),
            ).fetchone()
        if row is None:
            raise UnknownJobError(job_id)
        return self._row_to_job(row)

    def update_job(
        self,
        *,
        job_id: str,
        state: str,
        native_status: str | None,
        result: dict[str, Any],
        native_refs: dict[str, Any],
        warnings: list[str | dict[str, Any]],
        next_operations: list[str],
        error: dict[str, Any] | None,
    ) -> JobRecord:
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE jobs
                SET state = ?, native_status = ?, result_json = ?,
                    native_refs_json = ?, warnings_json = ?,
                    next_operations_json = ?, error_json = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    state,
                    native_status,
                    canonical_json(result),
                    canonical_json(native_refs),
                    canonical_json(warnings),
                    canonical_json(next_operations),
                    canonical_json(error) if error is not None else None,
                    _now(),
                    job_id,
                ),
            )
            row = db.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise UnknownJobError(job_id)
            return self._row_to_job(row)

    def begin_operation(
        self,
        *,
        job: JobRecord,
        operation: str,
        request_id: str | None,
        payload: dict[str, Any],
    ) -> OperationHandle:
        digest = payload_hash({"operation": operation, "input": payload})
        effective_id = request_id or f"auto_{uuid4().hex}"
        now = _now()
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT * FROM operations WHERE job_id = ? AND request_id = ?",
                (job.job_id, effective_id),
            ).fetchone()
            if row:
                if row["request_hash"] != digest:
                    raise IdempotencyKeyReusedError(effective_id)
                replay = (
                    _loads(row["response_json"], None)
                    if row["status"] == "succeeded"
                    else None
                )
                if row["status"] == "running":
                    raise ToolError(
                        "OPERATION_IN_PROGRESS",
                        "An operation with this request_id is already running.",
                        retryable=True,
                        details={"request_id": effective_id},
                    )
                if row["status"] == "failed":
                    replay = _loads(row["response_json"], None)
                return OperationHandle(
                    operation_id=row["operation_id"],
                    job_id=job.job_id,
                    operation=operation,
                    request_id=effective_id,
                    request_hash=digest,
                    replay=replay,
                )

            operation_id = f"op_{uuid4().hex}"
            db.execute(
                """
                INSERT INTO operations (
                    operation_id, job_id, operation, request_id, request_hash,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?)
                """,
                (
                    operation_id,
                    job.job_id,
                    operation,
                    effective_id,
                    digest,
                    now,
                    now,
                ),
            )
            return OperationHandle(
                operation_id=operation_id,
                job_id=job.job_id,
                operation=operation,
                request_id=effective_id,
                request_hash=digest,
            )

    def complete_operation(
        self, handle: OperationHandle, response: dict[str, Any]
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE operations
                SET status = 'succeeded', response_json = ?, error_json = NULL,
                    updated_at = ?
                WHERE operation_id = ?
                """,
                (canonical_json(response), _now(), handle.operation_id),
            )

    def fail_operation(
        self,
        handle: OperationHandle,
        *,
        error: dict[str, Any],
        response: dict[str, Any],
    ) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                """
                UPDATE operations
                SET status = 'failed', response_json = ?, error_json = ?,
                    updated_at = ?
                WHERE operation_id = ?
                """,
                (
                    canonical_json(response),
                    canonical_json(error),
                    _now(),
                    handle.operation_id,
                ),
            )

    def register_artifact(
        self,
        *,
        job_id: str,
        kind: str,
        path: Path,
        native_path: str | None,
        media_type: str,
        size_bytes: int,
        sha256: str,
    ) -> ArtifactRef:
        artifact_id = f"artifact_{uuid4().hex}"
        with self._lock, self._connect() as db:
            existing = db.execute(
                "SELECT * FROM artifacts WHERE job_id = ? AND path = ?",
                (job_id, str(path)),
            ).fetchone()
            if existing:
                return self._row_to_artifact(existing)
            db.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, job_id, kind, path, native_path, media_type,
                    size_bytes, sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    job_id,
                    kind,
                    str(path),
                    native_path,
                    media_type,
                    size_bytes,
                    sha256,
                    _now(),
                ),
            )
            row = db.execute(
                "SELECT * FROM artifacts WHERE artifact_id = ?", (artifact_id,)
            ).fetchone()
            assert row is not None
            return self._row_to_artifact(row)

    def list_artifacts(self, *, job_id: str) -> list[ArtifactRef]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM artifacts WHERE job_id = ? ORDER BY created_at",
                (job_id,),
            ).fetchall()
        return [self._row_to_artifact(row) for row in rows]

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            job_id=row["job_id"],
            tool_name=row["tool_name"],
            state=row["state"],
            native_status=row["native_status"],
            input_payload=_loads(row["input_json"], {}),
            result=_loads(row["result_json"], {}),
            native_refs=_loads(row["native_refs_json"], {}),
            warnings=_loads(row["warnings_json"], []),
            next_operations=_loads(row["next_operations_json"], []),
            error=_loads(row["error_json"], None),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_artifact(row: sqlite3.Row) -> ArtifactRef:
        return ArtifactRef(
            artifact_id=row["artifact_id"],
            kind=row["kind"],
            path=row["path"],
            native_path=row["native_path"],
            media_type=row["media_type"],
            size_bytes=row["size_bytes"],
            sha256=row["sha256"],
        )
