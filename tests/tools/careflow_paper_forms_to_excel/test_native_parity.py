from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ngopilot_mcp.tools.careflow_paper_forms_to_excel import native_adapter


class FakeVolunteerForm:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def create_batch(self, session: Any, **kwargs: Any) -> Any:
        self.calls.append(("create_batch", kwargs))
        return SimpleNamespace(id=71)

    def add_photos(
        self, session: Any, batch_id: int, files: list[tuple[str, bytes]]
    ) -> None:
        self.calls.append(("add_photos", {"batch_id": batch_id, "files": files}))

    def run_extraction(self, session: Any, batch_id: int, **kwargs: Any) -> None:
        self.calls.append(("run_extraction", {"batch_id": batch_id, **kwargs}))

    def review_record(self, session: Any, record_id: int, **kwargs: Any) -> None:
        self.calls.append(("review_record", {"record_id": record_id, **kwargs}))


def test_start_uses_exact_native_service_chain_and_file_bytes(
    tmp_path: Path, monkeypatch: Any
) -> None:
    first = tmp_path / "one.jpg"
    second = tmp_path / "two.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    service = FakeVolunteerForm()
    native = SimpleNamespace(volunteer_form=service)
    expected = {"native_status": "pending_review", "result": {}}
    monkeypatch.setattr(native_adapter, "_snapshot", lambda *args, **kwargs: expected)

    result = native_adapter._handle_start(
        native,
        object(),
        {
            "title": "Visit forms",
            "image_paths": [str(first.resolve()), str(second.resolve())],
            "original_filenames": ["one.jpg", "two.png"],
            "volunteer_team": "Team A",
            "visit_date": "2026-08-02",
            "note": "note",
            "auto_complete": True,
        },
    )

    assert result is expected
    assert service.calls == [
        (
            "create_batch",
            {
                "title": "Visit forms",
                "volunteer_team": "Team A",
                "visit_date": "2026-08-02",
                "note": "note",
            },
        ),
        (
            "add_photos",
            {"batch_id": 71, "files": [("one.jpg", b"first"), ("two.png", b"second")]},
        ),
        ("run_extraction", {"batch_id": 71, "auto_complete": True}),
    ]


def test_review_calls_native_review_once_per_complete_record(monkeypatch: Any) -> None:
    service = FakeVolunteerForm()
    native = SimpleNamespace(volunteer_form=service, VolunteerRecord=object())
    records = {
        3: SimpleNamespace(id=3, batch_id=71),
        4: SimpleNamespace(id=4, batch_id=71),
    }

    class Session:
        def get(self, model: Any, record_id: int) -> Any:
            return records.get(record_id)

    monkeypatch.setattr(native_adapter, "_get_batch", lambda *args: object())
    monkeypatch.setattr(
        native_adapter,
        "_snapshot",
        lambda *args, **kwargs: {
            "native_status": "confirmed",
            "result": kwargs["extra"],
        },
    )
    reviews = [
        {"record_id": 3, "final_fields": {"elder_name": "A"}, "reviewer": "R"},
        {"record_id": 4, "final_fields": {"elder_name": "B"}, "reviewer": None},
    ]

    result = native_adapter._handle_review(
        native,
        Session(),
        {"native_batch_id": 71, "reviews": reviews},
    )

    assert [call for call in service.calls if call[0] == "review_record"] == [
        (
            "review_record",
            {"record_id": 3, "final_fields": {"elder_name": "A"}, "reviewer": "R"},
        ),
        (
            "review_record",
            {"record_id": 4, "final_fields": {"elder_name": "B"}, "reviewer": None},
        ),
    ]
    assert result["result"]["reviewed_record_ids"] == [3, 4]


def test_export_passes_reviewed_rows_only_to_native_writer(
    tmp_path: Path, monkeypatch: Any
) -> None:
    output = (tmp_path / "exports/batch_71.xlsx").resolve()
    output.parent.mkdir(parents=True)
    batch = SimpleNamespace(
        id=71,
        title="Visit forms",
        volunteer_team="Team A",
        status="confirmed",
        exported_file=None,
        exported_at=None,
    )
    records = [
        SimpleNamespace(
            id=3,
            is_reviewed=True,
            final_fields={"elder_name": "Reviewed"},
            reviewer="R",
            reviewed_at=None,
        ),
        SimpleNamespace(
            id=4,
            is_reviewed=False,
            final_fields={"elder_name": "Not reviewed"},
            reviewer=None,
            reviewed_at=None,
        ),
    ]
    writer_calls: list[dict[str, Any]] = []

    class ExcelExport:
        @staticmethod
        def make_export_path(batch_id: int) -> Path:
            assert batch_id == 71
            return output

        @staticmethod
        def export_batch(**kwargs: Any) -> None:
            writer_calls.append(kwargs)
            output.write_bytes(b"native workbook")

    class Session:
        def add(self, value: Any) -> None:
            assert value is batch

        def commit(self) -> None:
            pass

    native = SimpleNamespace(
        excel_export=ExcelExport,
        settings=SimpleNamespace(data_path=tmp_path.resolve()),
        BatchStatus=SimpleNamespace(EXPORTED="exported"),
    )
    monkeypatch.setattr(native_adapter, "_get_batch", lambda *args: batch)
    monkeypatch.setattr(native_adapter, "_list_records", lambda *args: records)
    monkeypatch.setattr(
        native_adapter,
        "_snapshot",
        lambda *args, **kwargs: {
            "native_status": "exported",
            "native_refs": {"batch_id": 71, "record_ids": [3, 4]},
            "result": kwargs["extra"],
            "warnings": [],
        },
    )

    result = native_adapter._handle_export(native, Session(), {"native_batch_id": 71})

    assert writer_calls == [
        {
            "batch_title": "Visit forms",
            "volunteer_team": "Team A",
            "rows": [
                {
                    "final_fields": {"elder_name": "Reviewed"},
                    "reviewer": "R",
                    "reviewed_at": None,
                }
            ],
            "out_path": output,
        }
    ]
    assert result["result"]["exported_row_count"] == 1
    assert result["result"]["export"]["row_count"] == 1
    assert result["artifact_path"] == str(output)
    assert "Partial export" in result["warnings"][0]
