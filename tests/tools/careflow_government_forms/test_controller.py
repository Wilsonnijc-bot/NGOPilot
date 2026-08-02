from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from ngopilot_mcp.shared.errors import InvalidJobStateError, InvalidRequestError
from ngopilot_mcp.shared.jobs.store import JobRecord
from ngopilot_mcp.shared.tool_api import (
    ArtifactRef,
    OperationHandle,
    ToolCall,
    ToolExecution,
)
from ngopilot_mcp.tools.careflow_government_forms import CONTROLLER
from ngopilot_mcp.tools.careflow_government_forms.artifacts import (
    ARTIFACT_KIND,
    PDF_MEDIA_TYPE,
)

DISCOVERY = {
    "version": "v0.4.0-alpha",
    "count": 1,
    "templates": [
        {
            "id": "oala",
            "display_name": "OALA",
            "fill_strategy": "coord_anchor",
            "field_count": 2,
            "pdf_pages": 1,
            "status": "ready",
        }
    ],
    "source_capabilities": {
        "text": True,
        "elder_profile": True,
        "image_extensions": [".jpg", ".jpeg", ".png"],
    },
    "warnings": [],
}


def _start_response() -> dict[str, Any]:
    return {
        "native_status": "pending_review",
        "native_refs": {
            "template_id": "oala",
            "fill_strategy": "coord_anchor",
            "pdf_pages": 1,
        },
        "result": {
            "template_id": "oala",
            "template": deepcopy(DISCOVERY["templates"][0]),
            "elder_profile": {"elder_id": "E-1", "name": "draft"},
            "preview": {
                "mappings": [
                    {"key": "name", "value": "draft", "source": "direct"},
                    {"key": "phone", "value": "", "source": "missing"},
                ],
                "summary": {"total": 2, "direct": 1, "missing": 1},
                "used_llm": False,
            },
            "reviewed_values": None,
            "review": None,
        },
        "warnings": [],
    }


class FakeRuntime:
    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self.responses = list(responses or [])
        self.discovery_calls: list[dict[str, Any]] = []
        self.worker_calls: list[dict[str, Any]] = []
        self.stage_calls: list[dict[str, Any]] = []
        self.promote_calls: list[dict[str, Any]] = []
        self.begin_calls: list[dict[str, Any]] = []
        self.create_count = 0
        self.artifacts: list[ArtifactRef] = []
        self.job = JobRecord(
            job_id="job-government",
            tool_name="careflow_government_forms",
            state="accepted",
            native_status=None,
            input_payload={},
        )

    async def call_worker_discovery(self, **kwargs: Any) -> dict[str, Any]:
        self.discovery_calls.append(kwargs)
        return deepcopy(DISCOVERY)

    def create_job(self, **kwargs: Any) -> JobRecord:
        self.create_count += 1
        self.job.input_payload = deepcopy(kwargs["input_payload"])
        return self.job

    def get_job(self, **kwargs: Any) -> JobRecord:
        assert kwargs == {
            "tool_name": "careflow_government_forms",
            "job_id": self.job.job_id,
        }
        return self.job

    def stage_file(self, **kwargs: Any) -> Path:
        self.stage_calls.append(kwargs)
        return Path(kwargs["source_path"]).resolve()

    def begin_operation(self, **kwargs: Any) -> OperationHandle:
        self.begin_calls.append(kwargs)
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
            sha256="hash",
        )
        self.artifacts.append(artifact)
        return artifact

    def complete_operation(self, **kwargs: Any) -> ToolExecution:
        self.job.state = kwargs["state"]
        self.job.native_status = kwargs["native_status"]
        self.job.result = deepcopy(kwargs["result"])
        self.job.native_refs = deepcopy(kwargs.get("native_refs") or {})
        self.job.warnings = deepcopy(kwargs.get("warnings") or [])
        self.job.next_operations = list(kwargs.get("next_operations") or [])
        return self.job_execution(job=self.job, operation=kwargs["handle"].operation)

    def fail_operation(self, **kwargs: Any) -> ToolExecution:
        self.job.state = kwargs.get("state", "failed")
        return ToolExecution(
            tool=self.job.tool_name,
            operation=kwargs["handle"].operation,
            job_id=self.job.job_id,
            state=self.job.state,
            error={"message": str(kwargs["error"])},
        )

    def job_execution(self, **kwargs: Any) -> ToolExecution:
        return ToolExecution(
            tool=self.job.tool_name,
            operation=kwargs["operation"],
            job_id=self.job.job_id,
            state=self.job.state,
            native_status=self.job.native_status,
            result=deepcopy(self.job.result),
            native_refs=deepcopy(self.job.native_refs),
            artifacts=list(self.artifacts),
            warnings=deepcopy(self.job.warnings),
            next_operations=list(self.job.next_operations),
        )


def _reviewable(runtime: FakeRuntime, *, state: str = "pending_review") -> None:
    native = _start_response()
    runtime.job = replace(
        runtime.job,
        state=state,
        native_status="pending_review",
        input_payload={"template_id": "oala"},
        result=deepcopy(native["result"]),
        native_refs=deepcopy(native["native_refs"]),
        next_operations=["status", "review"],
    )


@pytest.mark.asyncio
async def test_list_templates_uses_stateless_worker_without_creating_a_job() -> None:
    runtime = FakeRuntime()
    execution = await CONTROLLER.execute(ToolCall(operation="list_templates"), runtime)

    assert runtime.create_count == 0
    assert runtime.worker_calls == []
    assert runtime.discovery_calls[0]["operation"] == "list_templates"
    assert execution.job_id is None
    assert execution.result["templates"][0]["id"] == "oala"


@pytest.mark.asyncio
async def test_structured_start_persists_exact_native_profile_and_preview() -> None:
    runtime = FakeRuntime([_start_response()])
    profile = {"elder_id": "E-1", "name": "input"}
    execution = await CONTROLLER.execute(
        ToolCall(
            operation="start",
            request_id="start-1",
            input={
                "template_id": "oala",
                "use_llm": False,
                "source_hint": "case record",
                "source": {"kind": "elder_profile", "elder_profile": profile},
            },
        ),
        runtime,
    )

    assert runtime.create_count == 1
    assert runtime.stage_calls == []
    worker = runtime.worker_calls[0]
    assert (worker["worker"], worker["tool_name"], worker["operation"]) == (
        "careflow",
        "careflow_government_forms",
        "start",
    )
    assert worker["payload"]["source"] == {
        "kind": "elder_profile",
        "elder_profile": profile,
    }
    assert execution.state == "pending_review"
    assert (
        execution.result["elder_profile"]
        == _start_response()["result"]["elder_profile"]
    )
    assert execution.result["preview"] == _start_response()["result"]["preview"]


@pytest.mark.asyncio
async def test_image_start_stages_explicit_role_and_records_owned_snapshot(
    tmp_path: Path,
) -> None:
    image = tmp_path / "elder.jpg"
    image.write_bytes(b"\xff\xd8\xffelder\xff\xd9")
    runtime = FakeRuntime([_start_response()])

    execution = await CONTROLLER.execute(
        ToolCall(
            operation="start",
            input={
                "template_id": "oala",
                "use_llm": False,
                "source": {"kind": "image", "image_path": str(image.resolve())},
            },
        ),
        runtime,
    )

    assert runtime.stage_calls[0]["role"] == "elder_profile_image"
    assert runtime.stage_calls[0]["content_kind"] == "image"
    assert runtime.worker_calls[0]["payload"]["source"] == {
        "kind": "image",
        "image_path": str(image.resolve()),
    }
    assert execution.result["source"]["staged_path"] == str(image.resolve())
    assert len(execution.result["source"]["sha256"]) == 64


@pytest.mark.asyncio
async def test_status_is_mcp_owned_and_never_calls_careflow() -> None:
    runtime = FakeRuntime()
    _reviewable(runtime)

    execution = await CONTROLLER.execute(
        ToolCall(operation="status", job_id=runtime.job.job_id),
        runtime,
    )

    assert runtime.discovery_calls == []
    assert runtime.worker_calls == []
    assert execution.result == runtime.job.result


@pytest.mark.asyncio
async def test_review_requires_and_stores_complete_replacement_without_native_call() -> (
    None
):
    runtime = FakeRuntime()
    _reviewable(runtime)
    reviewed = {"name": "人工確認", "phone": "61234567"}

    execution = await CONTROLLER.execute(
        ToolCall(
            operation="review",
            job_id=runtime.job.job_id,
            request_id="review-1",
            input={"field_values": reviewed, "reviewer": "SW-1"},
        ),
        runtime,
    )

    assert runtime.worker_calls == []
    assert execution.state == "reviewed"
    assert execution.result["reviewed_values"] == reviewed
    assert execution.result["review"]["field_values"] == reviewed
    assert execution.result["review"]["reviewer"] == "SW-1"

    _reviewable(runtime)
    with pytest.raises(InvalidRequestError):
        await CONTROLLER.execute(
            ToolCall(
                operation="review",
                job_id=runtime.job.job_id,
                input={"field_values": {"name": "incomplete"}},
            ),
            runtime,
        )


@pytest.mark.asyncio
async def test_export_uses_only_persisted_review_and_promotes_native_pdf(
    tmp_path: Path,
) -> None:
    output = tmp_path / "filled.pdf"
    output.write_bytes(b"%PDF-1.7\n%%EOF\n")
    native_export = {
        "native_status": "filled",
        "native_refs": {
            "template_id": "oala",
            "fill_strategy": "coord_anchor",
            "native_output_path": str(output.resolve()),
            "fill_stats": {"strategy": "coord_anchor", "filled": 2},
        },
        "result": {
            "ok": True,
            "template_id": "oala",
            "output_file": output.name,
            "stats": {"strategy": "coord_anchor", "filled": 2},
        },
        "artifact_path": str(output.resolve()),
        "artifact_page_count": 1,
        "warnings": [],
    }
    runtime = FakeRuntime([native_export])
    _reviewable(runtime, state="reviewed")
    reviewed = {"name": "reviewed name", "phone": "reviewed phone"}
    runtime.job.result["reviewed_values"] = reviewed
    runtime.job.result["review"] = {"field_values": reviewed}

    execution = await CONTROLLER.execute(
        ToolCall(operation="export", job_id=runtime.job.job_id),
        runtime,
    )

    assert runtime.worker_calls[0]["payload"] == {
        "template_id": "oala",
        "elder_profile": runtime.job.result["elder_profile"],
        "field_values": reviewed,
    }
    assert runtime.promote_calls[0]["kind"] == ARTIFACT_KIND
    assert runtime.promote_calls[0]["media_type"] == PDF_MEDIA_TYPE
    assert execution.state == "exported"
    assert execution.result["output_path"] == str(output.resolve())
    assert execution.result["preview"]["mappings"][0]["value"] == "draft"


@pytest.mark.asyncio
async def test_export_before_review_is_rejected_without_native_effect() -> None:
    runtime = FakeRuntime()
    _reviewable(runtime)
    with pytest.raises(InvalidJobStateError):
        await CONTROLLER.execute(
            ToolCall(operation="export", job_id=runtime.job.job_id),
            runtime,
        )
    assert runtime.worker_calls == []


@pytest.mark.asyncio
async def test_export_failure_preserves_reviewed_state(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"
    runtime = FakeRuntime(
        [
            {
                "result": {"ok": True},
                "native_refs": {},
                "artifact_path": str(missing.resolve()),
                "artifact_page_count": 1,
                "warnings": [],
            }
        ]
    )
    _reviewable(runtime, state="reviewed")
    runtime.job.result["reviewed_values"] = {"name": "A", "phone": "B"}

    execution = await CONTROLLER.execute(
        ToolCall(operation="export", job_id=runtime.job.job_id),
        runtime,
    )

    assert execution.state == "reviewed"
    assert execution.error is not None
