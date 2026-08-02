from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ngopilot_mcp.shared.errors import ToolError
from ngopilot_mcp.tools.roster_copilot import native_adapter
from ngopilot_mcp.tools.roster_copilot.artifacts import REVIEW_FILENAME


class FakeUploadFile:
    def __init__(self, *, file: Any, filename: str):
        self.file = file
        self.filename = filename


def test_start_calls_native_upload_facade_with_original_names_and_changes(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    hc = tmp_path / "staged-hc.xlsx"
    escort = tmp_path / "staged-escort.xlsm"
    hc.write_bytes(b"hc bytes")
    escort.write_bytes(b"escort bytes")
    calls: list[dict[str, Any]] = []

    class Demo:
        @staticmethod
        async def build_weekly_roster(**kwargs: Any) -> dict[str, Any]:
            calls.append(
                {
                    "hc_name": kwargs["hc_workbook"].filename,
                    "hc_bytes": kwargs["hc_workbook"].file.read(),
                    "escort_name": kwargs["escort_workbook"].filename,
                    "escort_bytes": kwargs["escort_workbook"].file.read(),
                    "week_start": kwargs["week_start"].isoformat(),
                    "changes": json.loads(kwargs["changes_json"]),
                }
            )
            return {"run_id": "native-run-1"}

    bindings = SimpleNamespace(demo=Demo, UploadFile=FakeUploadFile)
    monkeypatch.setattr(
        native_adapter,
        "_envelope",
        lambda _bindings, result, **kwargs: {"result": result},
    )

    result = native_adapter._start(
        bindings,
        {
            "hc_workbook_path": str(hc.resolve()),
            "escort_workbook_path": str(escort.resolve()),
            "hc_original_filename": "HC timetable.xlsx",
            "escort_original_filename": "escort master.xlsm",
            "week_start": "2026-08-03",
            "changes": [{"type": "leave", "worker_id": "worker-1"}],
        },
    )

    assert result == {"result": {"run_id": "native-run-1"}}
    assert calls == [
        {
            "hc_name": "HC timetable.xlsx",
            "hc_bytes": b"hc bytes",
            "escort_name": "escort master.xlsm",
            "escort_bytes": b"escort bytes",
            "week_start": "2026-08-03",
            "changes": [{"type": "leave", "worker_id": "worker-1"}],
        }
    ]


def test_review_and_revalidate_construct_exact_native_commands(
    monkeypatch: Any,
) -> None:
    calls: list[tuple[str, str, Any]] = []

    class Command:
        @classmethod
        def model_validate(cls, value: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            return cls.__name__, value

    class ReviewCommand(Command):
        pass

    class RevalidateCommand(Command):
        pass

    class Demo:
        @staticmethod
        def decide_weekly_roster_audit(run_id: str, command: Any) -> dict[str, Any]:
            calls.append(("review", run_id, command))
            return {"run_id": run_id}

        @staticmethod
        def revalidate_weekly_roster(run_id: str, command: Any) -> dict[str, Any]:
            calls.append(("revalidate", run_id, command))
            return {"run_id": run_id}

    bindings = SimpleNamespace(
        demo=Demo,
        WeeklyReviewCommand=ReviewCommand,
        WeeklyRevalidateCommand=RevalidateCommand,
    )
    monkeypatch.setattr(
        native_adapter,
        "_envelope",
        lambda _bindings, result, **kwargs: {"result": result},
    )
    review = {"source_version_id": "v1", "content_hash": "h1"}
    revalidate = {"source_version_id": "v2", "content_hash": "h2"}

    native_adapter._review(
        bindings,
        {"native_run_id": "run-1", "command": review},
    )
    native_adapter._revalidate(
        bindings,
        {"native_run_id": "run-1", "command": revalidate},
    )

    assert calls == [
        ("review", "run-1", ("ReviewCommand", review)),
        ("revalidate", "run-1", ("RevalidateCommand", revalidate)),
    ]


def test_export_calls_native_writer_then_snapshots_friendly_delivery_name(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    native = tmp_path / "照顧員工作分工表_審核草稿_version_timestamp.xlsx"
    native.write_bytes(b"native workbook bytes")
    calls: list[tuple[str, str]] = []

    class Demo:
        @staticmethod
        def export_weekly_roster(run_id: str) -> Any:
            calls.append(("export", run_id))
            return SimpleNamespace(path=str(native))

        @staticmethod
        def get_weekly_roster(run_id: str) -> dict[str, Any]:
            calls.append(("status", run_id))
            return {"run_id": run_id}

    monkeypatch.setattr(
        native_adapter,
        "_envelope",
        lambda _bindings, result, **kwargs: {"result": result},
    )
    response = native_adapter._export(
        SimpleNamespace(demo=Demo),
        {"native_run_id": "run-1"},
    )

    delivery = Path(response["artifact_path"])
    assert calls == [("export", "run-1"), ("status", "run-1")]
    assert delivery.name == REVIEW_FILENAME
    assert delivery.read_bytes() == native.read_bytes()
    assert response["native_source_path"] == str(native.resolve())


def test_native_http_detail_preserves_roster_conflict_code() -> None:
    class NativeHttpError(Exception):
        detail = {
            "code": "STALE_CONTENT_HASH",
            "message": "content hash is stale",
            "current_content_hash": "new-hash",
        }

    with pytest.raises(ToolError) as error:
        native_adapter._native_call(lambda: (_ for _ in ()).throw(NativeHttpError()))

    assert error.value.code == "STALE_CONTENT_HASH"
    assert error.value.native_code == "STALE_CONTENT_HASH"
    assert error.value.details == {"current_content_hash": "new-hash"}
