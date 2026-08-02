from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

import pytest

from ngopilot_mcp.shared.jobs.store import JobRecord
from ngopilot_mcp.shared.tool_api import (
    ArtifactRef,
    OperationHandle,
    ToolCall,
    ToolExecution,
)
from ngopilot_mcp.tools.careflow_meeting_notes import CONTROLLER
from ngopilot_mcp.tools.careflow_meeting_notes.artifacts import (
    ARTIFACT_KIND,
    DOCX_MEDIA_TYPE,
)


def _docx(path: Path) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return path.resolve()


def _session(
    *,
    status: str = "pending_review",
    burned: bool = False,
    generated_file: str | None = None,
) -> dict[str, Any]:
    return {
        "id": 71,
        "title": "Weekly meeting",
        "status": status,
        "audio_filename": "meeting.m4a",
        "template_filename": "template.docx",
        "template_contract": {
            "dynamic_slots": [
                {"slot_id": "summary", "source_block_id": "p_001"},
                {"slot_id": "follow_up", "source_block_id": "p_002"},
            ]
        },
        "slot_content": {"summary": "draft", "follow_up": "draft"},
        "slot_content_final": {"summary": "draft", "follow_up": "draft"},
        "generated_file": generated_file,
        "transcript_snippet": None if burned else "permitted native snippet",
        "transcript_burned": burned,
        "reviewer": None,
    }


def _native(
    *,
    status: str = "pending_review",
    burned: bool = False,
    artifact_path: Path | None = None,
    include_secret: bool = False,
) -> dict[str, Any]:
    session = _session(
        status=status,
        burned=burned,
        generated_file=artifact_path.name if artifact_path else None,
    )
    if include_secret:
        session["transcript"] = "FULL RAW TRANSCRIPT SECRET"
        session["transcript_vault_path"] = "transcripts/session_71.enc"
    payload: dict[str, Any] = {"native_session_id": 71, "session": session}
    if artifact_path:
        payload["native_artifact_path"] = str(artifact_path)
    return payload


class FakeRuntime:
    def __init__(self, tmp_path: Path, responses: list[dict[str, Any]] | None = None):
        self.tmp_path = tmp_path
        self.responses = list(responses or [])
        self.worker_calls: list[dict[str, Any]] = []
        self.stage_calls: list[dict[str, Any]] = []
        self.promote_calls: list[dict[str, Any]] = []
        self.artifacts: list[ArtifactRef] = []
        self.job = JobRecord(
            job_id="job-meeting",
            tool_name="careflow_meeting_notes",
            state="accepted",
            native_status=None,
            input_payload={},
        )

    def create_job(self, **kwargs: Any) -> JobRecord:
        self.job.input_payload = dict(kwargs["input_payload"])
        return self.job

    def get_job(self, **kwargs: Any) -> JobRecord:
        assert kwargs == {
            "tool_name": "careflow_meeting_notes",
            "job_id": self.job.job_id,
        }
        return self.job

    def stage_file(self, **kwargs: Any) -> Path:
        self.stage_calls.append(kwargs)
        return Path(kwargs["source_path"])

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
        artifact = ArtifactRef(
            artifact_id=f"artifact-{len(self.artifacts) + 1}",
            kind=kwargs["kind"],
            path=str(source),
            native_path=str(source),
            media_type=kwargs["media_type"],
            size_bytes=source.stat().st_size,
            sha256=f"hash-{len(self.artifacts) + 1}",
        )
        self.artifacts.append(artifact)
        return artifact

    def complete_operation(self, **kwargs: Any) -> ToolExecution:
        self.job.state = kwargs["state"]
        self.job.native_status = kwargs["native_status"]
        self.job.result = kwargs["result"]
        self.job.native_refs = kwargs.get("native_refs") or self.job.native_refs
        self.job.next_operations = kwargs.get("next_operations") or []
        return ToolExecution(
            tool=self.job.tool_name,
            operation=kwargs["handle"].operation,
            job_id=self.job.job_id,
            state=self.job.state,
            native_status=self.job.native_status,
            native_refs=dict(self.job.native_refs),
            result=dict(self.job.result),
            artifacts=list(self.artifacts),
            next_operations=list(self.job.next_operations),
        )

    def fail_operation(self, **kwargs: Any) -> ToolExecution:
        error = kwargs["error"]
        self.job.state = kwargs.get("state", "failed")
        return ToolExecution(
            tool=self.job.tool_name,
            operation=kwargs["handle"].operation,
            job_id=self.job.job_id,
            state=self.job.state,
            error={"message": str(error)},
        )

    def job_execution(self, **kwargs: Any) -> ToolExecution:
        return ToolExecution(
            tool=self.job.tool_name,
            operation=kwargs["operation"],
            job_id=self.job.job_id,
            state=self.job.state,
            native_status=self.job.native_status,
            result=dict(self.job.result),
            native_refs=dict(self.job.native_refs),
            artifacts=list(self.artifacts),
        )


def _reviewable(runtime: FakeRuntime, *, state: str = "pending_review") -> None:
    runtime.job = replace(
        runtime.job,
        state=state,
        native_status="confirmed"
        if state in {"confirmed", "exported"}
        else "pending_review",
        input_payload={"mode": "internal_meeting"},
        result={
            **_session(
                status="confirmed"
                if state in {"confirmed", "exported"}
                else "pending_review"
            ),
            "mode": "internal_meeting",
        },
        native_refs={"visit_session_id": 71, "mode": "internal_meeting"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["home_visit", "internal_meeting"])
async def test_start_stages_explicit_roles_and_routes_native_phase_one(
    tmp_path: Path,
    mode: str,
) -> None:
    audio = tmp_path / "meeting.m4a"
    audio.write_bytes(b"\0\0\0\x18ftypM4A audio")
    template = _docx(tmp_path / "template.docx")
    runtime = FakeRuntime(tmp_path, [_native(include_secret=True)])

    execution = await CONTROLLER.execute(
        ToolCall(
            operation="start",
            request_id="start-1",
            input={
                "title": "Weekly meeting",
                "mode": mode,
                "audio_path": str(audio),
                "template_path": str(template),
                "note": "private case meeting",
            },
        ),
        runtime,
    )

    assert [call["role"] for call in runtime.stage_calls] == [
        "audio",
        "report_template",
    ]
    assert runtime.stage_calls[0]["content_kind"] == "audio"
    assert runtime.stage_calls[1]["content_kind"] == "office_zip"
    worker = runtime.worker_calls[0]
    assert (worker["worker"], worker["tool_name"], worker["operation"]) == (
        "careflow",
        "careflow_meeting_notes",
        "start",
    )
    assert worker["payload"]["mode"] == mode
    assert execution.state == "pending_review"
    assert execution.native_refs == {"visit_session_id": 71, "mode": mode}
    assert "FULL RAW TRANSCRIPT SECRET" not in str(execution.as_dict())
    assert "transcript_vault_path" not in execution.result


@pytest.mark.asyncio
async def test_status_routes_native_reference_and_preserves_exported_state(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime(tmp_path, [_native(status="confirmed")])
    _reviewable(runtime, state="exported")

    execution = await CONTROLLER.execute(
        ToolCall(operation="status", job_id=runtime.job.job_id),
        runtime,
    )

    assert runtime.worker_calls[0]["payload"] == {"native_session_id": 71}
    assert execution.state == "exported"
    assert execution.result["mode"] == "internal_meeting"


@pytest.mark.asyncio
async def test_review_requires_complete_slots_and_promotes_each_native_render(
    tmp_path: Path,
) -> None:
    first = _docx(tmp_path / "visit_note_71_first.docx")
    second = _docx(tmp_path / "visit_note_71_second.docx")
    runtime = FakeRuntime(
        tmp_path,
        [
            _native(status="confirmed", artifact_path=first),
            _native(status="confirmed", artifact_path=second),
        ],
    )
    _reviewable(runtime)
    review_input = {
        "slot_content_final": {"summary": "approved", "follow_up": ["call"]},
        "reviewer": "social-worker",
    }

    first_execution = await CONTROLLER.execute(
        ToolCall(operation="review", job_id=runtime.job.job_id, input=review_input),
        runtime,
    )
    second_execution = await CONTROLLER.execute(
        ToolCall(operation="review", job_id=runtime.job.job_id, input=review_input),
        runtime,
    )

    assert runtime.worker_calls[0]["payload"] == {
        "native_session_id": 71,
        **review_input,
    }
    assert len(runtime.promote_calls) == 2
    assert all(call["kind"] == ARTIFACT_KIND for call in runtime.promote_calls)
    assert all(call["media_type"] == DOCX_MEDIA_TYPE for call in runtime.promote_calls)
    assert len(first_execution.artifacts) == 1
    assert [artifact.path for artifact in second_execution.artifacts] == [
        str(first),
        str(second),
    ]


@pytest.mark.asyncio
async def test_export_returns_latest_registered_docx_without_worker_call(
    tmp_path: Path,
) -> None:
    first = _docx(tmp_path / "first.docx")
    latest = _docx(tmp_path / "latest.docx")
    runtime = FakeRuntime(tmp_path)
    _reviewable(runtime, state="confirmed")
    for index, path in enumerate((first, latest), start=1):
        runtime.artifacts.append(
            ArtifactRef(
                artifact_id=f"artifact-{index}",
                kind=ARTIFACT_KIND,
                path=str(path),
                native_path=f"/native/{path.name}",
                media_type=DOCX_MEDIA_TYPE,
                size_bytes=path.stat().st_size,
                sha256=f"hash-{index}",
            )
        )

    execution = await CONTROLLER.execute(
        ToolCall(operation="export", job_id=runtime.job.job_id),
        runtime,
    )

    assert runtime.worker_calls == []
    assert execution.state == "exported"
    assert execution.artifacts[-1].path == str(latest)


@pytest.mark.asyncio
async def test_burn_calls_native_vault_boundary_and_removes_burn_next_action(
    tmp_path: Path,
) -> None:
    response = _native(status="pending_review", burned=True, include_secret=True)
    response["burned"] = True
    runtime = FakeRuntime(tmp_path, [response])
    _reviewable(runtime)

    execution = await CONTROLLER.execute(
        ToolCall(
            operation="burn",
            job_id=runtime.job.job_id,
            request_id="burn-once",
        ),
        runtime,
    )

    assert runtime.worker_calls[0]["operation"] == "burn"
    assert runtime.worker_calls[0]["payload"] == {"native_session_id": 71}
    assert execution.result["transcript_burned"] is True
    assert execution.result["burned"] is True
    assert "burn" not in execution.next_operations
    assert "FULL RAW TRANSCRIPT SECRET" not in str(execution.as_dict())
