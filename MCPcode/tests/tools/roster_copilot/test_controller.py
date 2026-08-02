from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from ngopilot_mcp.shared.jobs.store import JobRecord
from ngopilot_mcp.shared.tool_api import (
    ArtifactRef,
    OperationHandle,
    ToolCall,
    ToolExecution,
)
from ngopilot_mcp.tools.roster_copilot import CONTROLLER, MANIFEST
from ngopilot_mcp.tools.roster_copilot.artifacts import (
    FINAL_ARTIFACT_KIND,
    FINAL_FILENAME,
    REVIEW_ARTIFACT_KIND,
    REVIEW_FILENAME,
    XLSX_MEDIA_TYPE,
)

from .test_artifacts import write_xlsx


def worker_result(
    *,
    state: str = "draft",
    pending: bool = True,
    publication: dict[str, Any] | None = None,
    artifact: Path | None = None,
    publication_id: str | None = None,
    artifact_sha256: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "run_id": "native-run-1",
        "publication_state": state if state != "published" else "ready",
        "review_export_allowed": True,
        "version": {"id": "version-1"},
        "reconciliation": {"content_hash": "content-hash-1"},
        "audit_items": [{"id": "audit-1", "status": "pending"}] if pending else [],
        "publications": [publication] if publication else [],
        "publication": publication,
    }
    response: dict[str, Any] = {
        "native_status": state,
        "native_refs": {
            "run_id": "native-run-1",
            "current_version_id": "version-1",
            "content_hash": "content-hash-1",
        },
        "result": result,
        "warnings": [],
    }
    if artifact is not None:
        response["artifact_path"] = str(artifact)
    if publication_id is not None:
        response["publication_id"] = publication_id
    if artifact_sha256 is not None:
        response["artifact_sha256"] = artifact_sha256
    return response


class FakeRuntime:
    def __init__(self, root: Path, responses: list[dict[str, Any]]):
        self.root = root
        self.responses = list(responses)
        self.stage_calls: list[dict[str, Any]] = []
        self.worker_calls: list[dict[str, Any]] = []
        self.promote_calls: list[dict[str, Any]] = []
        self.artifacts: list[ArtifactRef] = []
        self.job = JobRecord(
            job_id="job-roster-1",
            tool_name=MANIFEST.name,
            state="accepted",
            native_status=None,
            input_payload={},
        )

    def create_job(self, **kwargs: Any) -> JobRecord:
        self.job.input_payload = dict(kwargs["input_payload"])
        return self.job

    def get_job(self, **kwargs: Any) -> JobRecord:
        assert kwargs == {"tool_name": MANIFEST.name, "job_id": self.job.job_id}
        return self.job

    def stage_file(self, **kwargs: Any) -> Path:
        self.stage_calls.append(kwargs)
        source = Path(kwargs["source_path"])
        target = self.root / "inputs" / f"{kwargs['role']}{source.suffix.lower()}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target.resolve()

    def begin_operation(self, **kwargs: Any) -> OperationHandle:
        return OperationHandle(
            operation_id=f"op-{uuid4().hex}",
            job_id=self.job.job_id,
            operation=kwargs["operation"],
            request_id=kwargs.get("request_id") or f"auto-{uuid4().hex}",
            request_hash="hash",
        )

    async def call_worker(self, **kwargs: Any) -> dict[str, Any]:
        self.worker_calls.append(kwargs)
        return self.responses.pop(0)

    def promote_artifact(self, **kwargs: Any) -> ArtifactRef:
        self.promote_calls.append(kwargs)
        source = Path(kwargs["source_path"])
        target = self.root / "outputs" / f"{uuid4().hex[:8]}_{source.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        artifact = ArtifactRef(
            artifact_id=f"artifact-{len(self.artifacts) + 1}",
            kind=kwargs["kind"],
            path=str(target.resolve()),
            native_path=str(source),
            media_type=kwargs["media_type"],
            size_bytes=target.stat().st_size,
            sha256=digest,
        )
        self.artifacts.append(artifact)
        return artifact

    def complete_operation(self, **kwargs: Any) -> ToolExecution:
        self.job.state = kwargs["state"]
        self.job.native_status = kwargs["native_status"]
        self.job.result = kwargs["result"]
        self.job.native_refs = kwargs["native_refs"]
        self.job.warnings = kwargs["warnings"]
        self.job.next_operations = kwargs["next_operations"]
        return ToolExecution(
            tool=MANIFEST.name,
            operation=kwargs["handle"].operation,
            job_id=self.job.job_id,
            state=self.job.state,
            native_status=self.job.native_status,
            result=dict(self.job.result),
            native_refs=dict(self.job.native_refs),
            artifacts=list(self.artifacts),
            warnings=list(self.job.warnings),
            next_operations=list(self.job.next_operations),
        )

    def fail_operation(self, **kwargs: Any) -> ToolExecution:
        error = kwargs["error"]
        return ToolExecution(
            tool=MANIFEST.name,
            operation=kwargs["handle"].operation,
            job_id=self.job.job_id,
            state="failed",
            error={
                "code": getattr(error, "code", type(error).__name__),
                "message": str(error),
            },
        )

    def job_execution(self, **kwargs: Any) -> ToolExecution:
        return ToolExecution(
            tool=MANIFEST.name,
            operation=kwargs["operation"],
            job_id=self.job.job_id,
            state=self.job.state,
            native_status=self.job.native_status,
            result=dict(self.job.result),
            native_refs=dict(self.job.native_refs),
            artifacts=list(self.artifacts),
        )


def make_started(runtime: FakeRuntime) -> None:
    runtime.job.state = "draft"
    runtime.job.native_status = "draft"
    runtime.job.native_refs = {
        "run_id": "native-run-1",
        "current_version_id": "version-1",
        "content_hash": "content-hash-1",
        "input_workbooks": {"hc": {}, "escort": {}},
    }


@pytest.mark.asyncio
async def test_start_stages_named_roles_and_records_hashes(tmp_path: Path) -> None:
    hc = write_xlsx(tmp_path / "hc.xlsx")
    escort = write_xlsx(tmp_path / "escort.xlsm")
    runtime = FakeRuntime(tmp_path, [worker_result()])

    execution = await CONTROLLER.execute(
        ToolCall(
            operation="start",
            request_id="start-1",
            input={
                "hc_workbook_path": str(hc),
                "escort_workbook_path": str(escort),
                "week_start": "2026-08-03",
                "changes": [{"type": "leave", "worker_id": "worker-1"}],
            },
        ),
        runtime,
    )

    assert [call["role"] for call in runtime.stage_calls] == [
        "hc_workbook",
        "escort_workbook",
    ]
    assert all(call["content_kind"] == "office_zip" for call in runtime.stage_calls)
    assert runtime.worker_calls[0]["worker"] == "rostercopiilot"
    assert runtime.worker_calls[0]["payload"]["hc_original_filename"] == "hc.xlsx"
    assert (
        runtime.worker_calls[0]["payload"]["escort_original_filename"] == "escort.xlsm"
    )
    assert execution.native_refs["run_id"] == "native-run-1"
    assert len(execution.native_refs["input_workbooks"]["hc"]["sha256"]) == 64
    assert execution.state == "draft"
    assert {"status", "review", "revalidate", "export"}.issubset(
        execution.next_operations
    )


@pytest.mark.asyncio
async def test_status_review_and_revalidate_route_exact_native_identity(
    tmp_path: Path,
) -> None:
    review_response = worker_result(state="ready", pending=False)
    review_response["result"]["decision"] = {"decision_id": "decision-1"}
    revalidate_response = worker_result(state="ready", pending=False)
    revalidate_response["result"].update(
        {"revalidated": True, "version_unchanged": True}
    )
    runtime = FakeRuntime(
        tmp_path,
        [worker_result(), review_response, revalidate_response],
    )
    make_started(runtime)

    await CONTROLLER.execute(
        ToolCall(operation="status", job_id=runtime.job.job_id),
        runtime,
    )
    review = await CONTROLLER.execute(
        ToolCall(
            operation="review",
            job_id=runtime.job.job_id,
            input={
                "source_version_id": "version-1",
                "content_hash": "content-hash-1",
                "idempotency_key": "decision-once",
                "actor": "supervisor",
                "action": "approve",
                "audit_id": "audit-1",
            },
        ),
        runtime,
    )
    revalidated = await CONTROLLER.execute(
        ToolCall(
            operation="revalidate",
            job_id=runtime.job.job_id,
            input={
                "source_version_id": "version-1",
                "content_hash": "content-hash-1",
            },
        ),
        runtime,
    )

    assert runtime.worker_calls[0]["payload"] == {"native_run_id": "native-run-1"}
    assert (
        runtime.worker_calls[1]["payload"]["command"]["idempotency_key"]
        == "decision-once"
    )
    assert runtime.worker_calls[2]["payload"]["command"] == {
        "source_version_id": "version-1",
        "content_hash": "content-hash-1",
    }
    assert review.state == "ready"
    assert revalidated.result["version_unchanged"] is True


@pytest.mark.asyncio
async def test_export_promotes_distinct_review_workbook(tmp_path: Path) -> None:
    review = write_xlsx(tmp_path / REVIEW_FILENAME)
    response = worker_result(artifact=review)
    response["native_source_path"] = str(tmp_path / "native_timestamped.xlsx")
    response["result"]["review_export"] = {"filename": REVIEW_FILENAME}
    runtime = FakeRuntime(tmp_path, [response])
    make_started(runtime)

    execution = await CONTROLLER.execute(
        ToolCall(operation="export", job_id=runtime.job.job_id),
        runtime,
    )

    assert runtime.promote_calls[0]["kind"] == REVIEW_ARTIFACT_KIND
    assert runtime.promote_calls[0]["media_type"] == XLSX_MEDIA_TYPE
    assert Path(execution.result["output_path"]).name.endswith(REVIEW_FILENAME)
    assert execution.native_refs["last_native_review_export_path"].endswith(
        "native_timestamped.xlsx"
    )


@pytest.mark.asyncio
async def test_publish_then_get_reuses_one_promoted_final_artifact(
    tmp_path: Path,
) -> None:
    final = write_xlsx(tmp_path / FINAL_FILENAME)
    digest = hashlib.sha256(final.read_bytes()).hexdigest()
    publication = {
        "publication_id": "publication-1",
        "source_version_id": "version-1",
        "content_hash": "content-hash-1",
        "artifact_sha256": digest,
        "filename": FINAL_FILENAME,
    }
    publish_response = worker_result(
        state="published",
        pending=False,
        publication=publication,
        artifact=final,
        publication_id="publication-1",
        artifact_sha256=digest,
    )
    get_response = worker_result(
        state="published",
        pending=False,
        publication=publication,
        artifact=final,
        publication_id="publication-1",
        artifact_sha256=digest,
    )
    get_response["result"]["requested_publication"] = dict(publication)
    runtime = FakeRuntime(tmp_path, [publish_response, get_response])
    make_started(runtime)

    published = await CONTROLLER.execute(
        ToolCall(
            operation="publish",
            job_id=runtime.job.job_id,
            request_id="publish-once",
            input={
                "actor": "supervisor",
                "source_version_id": "version-1",
                "content_hash": "content-hash-1",
            },
        ),
        runtime,
    )
    retrieved = await CONTROLLER.execute(
        ToolCall(
            operation="get_published",
            job_id=runtime.job.job_id,
            input={"publication_id": "publication-1"},
        ),
        runtime,
    )

    assert len(runtime.promote_calls) == 1
    assert runtime.promote_calls[0]["kind"] == FINAL_ARTIFACT_KIND
    assert published.state == retrieved.state == "published"
    assert retrieved.result["output_path"] == published.result["output_path"]
    assert runtime.worker_calls[1]["payload"]["command"] == {
        "publication_id": "publication-1"
    }
