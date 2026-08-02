from __future__ import annotations

import ast
import asyncio
import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest

from ngopilot_mcp.shared.errors import InvalidRequestError
from ngopilot_mcp.shared.tool_api import (
    ArtifactRef,
    OperationHandle,
    ToolCall,
    ToolExecution,
)
from ngopilot_mcp.tools.careflow_paper_forms_to_excel import CONTROLLER, MANIFEST
from ngopilot_mcp.tools.careflow_paper_forms_to_excel.schemas import FIELD_KEYS


@dataclass
class FakeJob:
    job_id: str = "job-paper-1"
    tool_name: str = MANIFEST.name
    state: str = "accepted"
    native_status: str | None = None
    input_payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    native_refs: dict[str, Any] = field(default_factory=dict)
    warnings: list[Any] = field(default_factory=list)
    next_operations: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None


class FakeRuntime:
    def __init__(self, root: Path, worker_responses: dict[str, dict[str, Any]]):
        self.root = root
        self.worker_responses = worker_responses
        self.job = FakeJob()
        self.staged: list[dict[str, Any]] = []
        self.worker_calls: list[dict[str, Any]] = []
        self.promoted: list[dict[str, Any]] = []

    def create_job(self, **kwargs: Any) -> FakeJob:
        self.job.input_payload = kwargs["input_payload"]
        return self.job

    def get_job(self, **kwargs: Any) -> FakeJob:
        assert kwargs == {"tool_name": MANIFEST.name, "job_id": self.job.job_id}
        return self.job

    def stage_file(self, **kwargs: Any) -> Path:
        self.staged.append(kwargs)
        target = (
            self.root
            / "inputs"
            / f"{kwargs['role']}{Path(kwargs['source_path']).suffix}"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kwargs["source_path"], target)
        return target.resolve()

    def begin_operation(self, **kwargs: Any) -> OperationHandle:
        return OperationHandle(
            operation_id=f"op-{kwargs['operation']}",
            job_id=self.job.job_id,
            operation=kwargs["operation"],
            request_id=kwargs["request_id"] or "generated",
            request_hash="hash",
        )

    async def call_worker(self, **kwargs: Any) -> dict[str, Any]:
        self.worker_calls.append(kwargs)
        return self.worker_responses[kwargs["operation"]]

    def promote_artifact(self, **kwargs: Any) -> ArtifactRef:
        self.promoted.append(kwargs)
        target = self.root / "outputs" / "volunteer-forms.xlsx"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(kwargs["source_path"], target)
        content = target.read_bytes()
        return ArtifactRef(
            artifact_id="artifact-1",
            kind=kwargs["kind"],
            path=str(target.resolve()),
            media_type=kwargs["media_type"],
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            native_path=str(kwargs["source_path"]),
        )

    def complete_operation(self, **kwargs: Any) -> ToolExecution:
        self.job.state = kwargs["state"]
        self.job.native_status = kwargs["native_status"]
        self.job.result = kwargs["result"]
        self.job.native_refs = kwargs["native_refs"]
        return ToolExecution(
            tool=MANIFEST.name,
            operation=kwargs["handle"].operation,
            job_id=self.job.job_id,
            state=kwargs["state"],
            native_status=kwargs["native_status"],
            result=kwargs["result"],
            native_refs=kwargs["native_refs"],
            artifacts=kwargs["artifacts"],
            warnings=kwargs["warnings"],
            next_operations=kwargs["next_operations"],
        )

    def fail_operation(self, **kwargs: Any) -> ToolExecution:
        raise kwargs["error"]

    def job_execution(self, **kwargs: Any) -> ToolExecution:
        return ToolExecution(
            tool=MANIFEST.name,
            operation=kwargs["operation"],
            job_id=self.job.job_id,
            state=self.job.state,
        )


def _final_fields() -> dict[str, object]:
    return {key: None for key in FIELD_KEYS}


def _worker_snapshot(status: str = "pending_review") -> dict[str, Any]:
    return {
        "native_status": status,
        "native_refs": {"batch_id": 41, "record_ids": [101]},
        "result": {
            "batch": {"id": 41, "status": status, "total_photos": 1},
            "records": [
                {"id": 101, "batch_id": 41, "is_reviewed": status != "pending_review"}
            ],
            "reviewed_count": 0 if status == "pending_review" else 1,
            "unreviewed_count": 1 if status == "pending_review" else 0,
        },
        "warnings": [],
    }


def _write_jpeg(path: Path) -> None:
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"form image" + b"\xff\xd9")


def _write_workbook(path: Path) -> None:
    with ZipFile(path, "w") as workbook:
        workbook.writestr("[Content_Types].xml", "<Types/>")
        workbook.writestr("xl/workbook.xml", "<workbook/>")
        workbook.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")


def test_start_stages_named_image_role_and_routes_only_staged_path(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-form.jpg"
    _write_jpeg(source)
    runtime = FakeRuntime(tmp_path / "runtime", {"start": _worker_snapshot()})

    execution = asyncio.run(
        CONTROLLER.execute(
            ToolCall(
                operation="start",
                request_id="start-1",
                input={
                    "title": "Volunteer visits",
                    "image_paths": [str(source.resolve())],
                    "visit_date": "2026-08-02",
                    "auto_complete": False,
                },
            ),
            runtime,
        )
    )

    assert execution.state == "pending_review"
    assert runtime.staged[0]["role"] == "completed_form_image_001"
    assert runtime.staged[0]["content_kind"] == "image"
    worker_payload = runtime.worker_calls[0]["payload"]
    assert worker_payload["image_paths"] == [
        str((tmp_path / "runtime/inputs/completed_form_image_001.jpg").resolve())
    ]
    assert worker_payload["original_filenames"] == ["source-form.jpg"]
    assert (
        execution.result["records"][0]["source_path"]
        == worker_payload["image_paths"][0]
    )
    assert execution.native_refs["batch_id"] == 41


def test_review_routes_complete_fields_and_preserves_native_result(
    tmp_path: Path,
) -> None:
    response = _worker_snapshot("confirmed")
    response["result"]["reviewed_record_ids"] = [101]
    runtime = FakeRuntime(tmp_path, {"review": response})
    runtime.job.native_refs = {
        "batch_id": 41,
        "record_ids": [101],
        "record_source_paths": {"101": "/staged/form.jpg"},
    }

    execution = asyncio.run(
        CONTROLLER.execute(
            ToolCall(
                operation="review",
                job_id=runtime.job.job_id,
                request_id="review-1",
                input={
                    "reviews": [
                        {
                            "record_id": 101,
                            "final_fields": _final_fields(),
                            "reviewer": "Reviewer",
                        }
                    ]
                },
            ),
            runtime,
        )
    )

    assert execution.state == "reviewed"
    payload = runtime.worker_calls[0]["payload"]
    assert payload["native_batch_id"] == 41
    assert tuple(payload["reviews"][0]["final_fields"]) == FIELD_KEYS
    assert execution.result["records"][0]["source_path"] == "/staged/form.jpg"


def test_review_rejects_a_record_from_another_job_before_native_call(
    tmp_path: Path,
) -> None:
    runtime = FakeRuntime(tmp_path, {})
    runtime.job.native_refs = {"batch_id": 41, "record_ids": [101]}

    with pytest.raises(InvalidRequestError):
        asyncio.run(
            CONTROLLER.execute(
                ToolCall(
                    operation="review",
                    job_id=runtime.job.job_id,
                    input={
                        "reviews": [{"record_id": 999, "final_fields": _final_fields()}]
                    },
                ),
                runtime,
            )
        )
    assert runtime.worker_calls == []


def test_partial_export_promotes_native_workbook_and_returns_owned_path(
    tmp_path: Path,
) -> None:
    native_path = (tmp_path / "careflow-data" / "batch_41.xlsx").resolve()
    native_path.parent.mkdir(parents=True)
    _write_workbook(native_path)
    response = _worker_snapshot("exported")
    response.update(
        {
            "artifact_path": str(native_path),
            "warnings": ["Partial export: one unreviewed record was omitted."],
        }
    )
    response["result"].update(
        {
            "reviewed_count": 1,
            "unreviewed_count": 1,
            "exported_row_count": 1,
            "export": {"batch_id": 41, "row_count": 1},
        }
    )
    runtime = FakeRuntime(tmp_path / "mcp", {"export": response})
    runtime.job.native_refs = {"batch_id": 41, "record_ids": [101]}

    execution = asyncio.run(
        CONTROLLER.execute(
            ToolCall(
                operation="export", job_id=runtime.job.job_id, request_id="export-1"
            ),
            runtime,
        )
    )

    assert execution.state == "exported"
    assert execution.result["reviewed_count"] == 1
    assert execution.result["unreviewed_count"] == 1
    assert execution.result["exported_row_count"] == 1
    assert execution.result["output_path"].endswith("/outputs/volunteer-forms.xlsx")
    assert execution.result["export"]["output_path"] == execution.result["output_path"]
    assert execution.artifacts[0].native_path == str(native_path)
    assert Path(execution.artifacts[0].path).exists()


def test_tool_package_has_no_cross_tool_imports() -> None:
    package_dir = (
        Path(__file__).parents[3]
        / "src/ngopilot_mcp/tools/careflow_paper_forms_to_excel"
    )
    for source_path in package_dir.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not (
                    node.module.startswith("ngopilot_mcp.tools.")
                    and "careflow_paper_forms_to_excel" not in node.module
                ), f"cross-tool import in {source_path.name}: {node.module}"


def test_only_native_adapter_mentions_careflow_app_import() -> None:
    package_dir = (
        Path(__file__).parents[3]
        / "src/ngopilot_mcp/tools/careflow_paper_forms_to_excel"
    )
    offenders = []
    for source_path in package_dir.glob("*.py"):
        if source_path.name == "native_adapter.py":
            continue
        if "from app" in source_path.read_text(encoding="utf-8"):
            offenders.append(source_path.name)
    assert offenders == []
