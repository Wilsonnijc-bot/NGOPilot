from __future__ import annotations

import hashlib
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

from ngopilot_mcp.config import Settings
from ngopilot_mcp.shared.errors import IdempotencyKeyReusedError, ToolError
from ngopilot_mcp.shared.runtime import Runtime


@pytest.fixture
def runtime(tmp_path: Path) -> Runtime:
    input_root = tmp_path / "incoming"
    input_root.mkdir()
    settings = Settings(
        state_root=tmp_path / "state",
        careflow_source=tmp_path,
        roster_source=tmp_path,
        careflow_python=Path(sys.executable),
        roster_python=Path(sys.executable),
        allowed_input_roots=(input_root,),
        worker_timeout_seconds=5,
    )
    settings.initialize_directories()
    return Runtime(settings)


def _office_file(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")


def test_job_lifecycle_and_idempotent_replay(runtime: Runtime) -> None:
    job = runtime.create_job(
        tool_name="example",
        request_id="start-1",
        input_payload={"value": 1},
    )
    same = runtime.create_job(
        tool_name="example",
        request_id="start-1",
        input_payload={"value": 1},
    )
    assert same.job_id == job.job_id

    handle = runtime.begin_operation(
        job=job,
        operation="start",
        request_id="operation-1",
        payload={"value": 1},
    )
    execution = runtime.complete_operation(
        job=job,
        handle=handle,
        state="pending_review",
        native_status="pending_review",
        result={"draft": True},
        native_refs={"native_id": 7},
        next_operations=["review"],
    )
    replay = runtime.begin_operation(
        job=job,
        operation="start",
        request_id="operation-1",
        payload={"value": 1},
    )

    assert execution.state == "pending_review"
    assert replay.replay == execution.as_dict()
    assert (
        runtime.settings.jobs_root / "example" / job.job_id / "manifest.json"
    ).is_file()


def test_request_id_reuse_with_changed_payload_fails(runtime: Runtime) -> None:
    runtime.create_job(
        tool_name="example",
        request_id="same",
        input_payload={"value": 1},
    )
    with pytest.raises(IdempotencyKeyReusedError):
        runtime.create_job(
            tool_name="example",
            request_id="same",
            input_payload={"value": 2},
        )


def test_failed_followup_preserves_last_successful_stage(runtime: Runtime) -> None:
    job = runtime.create_job(
        tool_name="example",
        request_id=None,
        input_payload={},
    )
    start = runtime.begin_operation(
        job=job,
        operation="start",
        request_id=None,
        payload={},
    )
    runtime.complete_operation(
        job=job,
        handle=start,
        state="pending_review",
        native_status="pending_review",
        result={"draft": True},
        next_operations=["status", "review"],
    )
    stable = runtime.get_job(tool_name="example", job_id=job.job_id)
    review = runtime.begin_operation(
        job=stable,
        operation="review",
        request_id=None,
        payload={"value": "invalid"},
    )

    failed = runtime.fail_operation(
        job=stable,
        handle=review,
        error=ToolError("NATIVE_REVIEW_FAILED", "review failed"),
    )

    assert failed.state == "pending_review"
    assert failed.result == {"draft": True}
    assert failed.next_operations == ["status", "review"]
    assert failed.error is not None
    assert failed.error["code"] == "NATIVE_REVIEW_FAILED"


@pytest.mark.asyncio
async def test_discovery_worker_call_creates_no_job(
    runtime: Runtime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    async def fake_call(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        assert Path(str(kwargs["job_root"])).is_dir()
        return {"templates": []}

    monkeypatch.setattr(runtime.workers, "call", fake_call)

    result = await runtime.call_worker_discovery(
        worker="careflow",
        tool_name="careflow_government_forms",
        operation="list_templates",
        payload={},
    )

    assert result == {"templates": []}
    assert observed["job_id"] == "discovery"
    assert not Path(str(observed["job_root"])).exists()
    with sqlite3.connect(runtime.settings.database_path) as database:
        assert database.execute("SELECT COUNT(*) FROM jobs").fetchone() == (0,)


def test_stage_and_promote_are_namespaced(runtime: Runtime) -> None:
    source = runtime.settings.allowed_input_roots[0] / "input.xlsx"
    _office_file(source)
    job = runtime.create_job(
        tool_name="example",
        request_id=None,
        input_payload={},
    )
    staged = runtime.stage_file(
        job=job,
        role="workbook",
        source_path=source,
        allowed_extensions=(".xlsx",),
        content_kind="office_zip",
    )
    artifact = runtime.promote_artifact(
        job=job,
        source_path=staged,
        kind="workbook",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        expected_extensions=(".xlsx",),
    )

    assert staged.is_relative_to(
        runtime.settings.jobs_root / "example" / job.job_id / "inputs"
    )
    artifact_path = Path(artifact.path)
    assert artifact_path.is_relative_to(
        runtime.settings.jobs_root / "example" / job.job_id / "outputs"
    )
    assert artifact.sha256 == hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    artifact_path.write_bytes(b"tampered")
    with pytest.raises(ToolError) as integrity:
        runtime.job_execution(job=job, operation="status")
    assert integrity.value.code == "ARTIFACT_INTEGRITY_ERROR"


def test_stage_rejects_relative_and_private_job_paths(runtime: Runtime) -> None:
    job = runtime.create_job(
        tool_name="example",
        request_id=None,
        input_payload={},
    )
    with pytest.raises(ToolError) as relative:
        runtime.stage_file(
            job=job,
            role="workbook",
            source_path="relative.xlsx",
            allowed_extensions=(".xlsx",),
        )
    assert relative.value.code == "PATH_NOT_ABSOLUTE"

    private = runtime.settings.jobs_root / "other" / "job_private" / "secret.xlsx"
    private.parent.mkdir(parents=True)
    _office_file(private)
    with pytest.raises(ToolError) as protected:
        runtime.stage_file(
            job=job,
            role="workbook",
            source_path=private,
            allowed_extensions=(".xlsx",),
        )
    assert protected.value.code == "PATH_NOT_ALLOWED"
