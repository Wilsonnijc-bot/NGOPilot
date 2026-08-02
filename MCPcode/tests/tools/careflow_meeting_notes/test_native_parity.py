from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ngopilot_mcp.tools.careflow_meeting_notes import native_adapter


class FakeDatabase:
    def __init__(self) -> None:
        self.rows: dict[int, Any] = {}

    def get(self, model: Any, native_session_id: int) -> Any:
        return self.rows.get(native_session_id)


def _session() -> SimpleNamespace:
    now = datetime(2026, 8, 2, 12, 0)
    return SimpleNamespace(
        id=17,
        title="Internal meeting",
        note="weekly",
        status="uploaded",
        audio_filename="meeting.mp3",
        template_filename="template.docx",
        template_contract=None,
        slot_content=None,
        slot_content_final=None,
        generated_file=None,
        transcript_burned=False,
        ai_provider=None,
        ai_model=None,
        ai_latency_ms=None,
        ai_error=None,
        reviewer=None,
        reviewed_at=None,
        created_at=now,
        updated_at=now,
    )


def test_adapter_preserves_native_phase_review_export_and_burn_boundaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_root = tmp_path / "careflow-data"
    data_root.mkdir()
    db = FakeDatabase()
    calls: list[tuple[Any, ...]] = []

    def create_session(
        database: FakeDatabase,
        *,
        title: str,
        note: str | None,
        audio: tuple[str, bytes],
        template: tuple[str, bytes],
    ) -> Any:
        calls.append(("create_session", title, note, audio, template))
        row = _session()
        database.rows[row.id] = row
        return row

    def run_phase1(
        database: FakeDatabase,
        native_session_id: int,
        *,
        mode: str,
    ) -> None:
        calls.append(("run_phase1", native_session_id, mode))
        row = database.rows[native_session_id]
        row.status = "pending_review"
        row.template_contract = {
            "dynamic_slots": [{"slot_id": "summary", "source_block_id": "p1"}]
        }
        row.slot_content = {"summary": "draft"}
        row.slot_content_final = {"summary": "draft"}

    def run_phase2(
        database: FakeDatabase,
        native_session_id: int,
        *,
        slot_content_final: dict[str, Any],
        reviewer: str | None,
    ) -> Any:
        calls.append(("run_phase2", native_session_id, slot_content_final, reviewer))
        row = database.rows[native_session_id]
        row.slot_content_final = slot_content_final
        row.reviewer = reviewer
        row.status = "confirmed"
        row.generated_file = "exports/visit_notes/visit_note_17_20260802.docx"
        generated = data_root / row.generated_file
        generated.parent.mkdir(parents=True)
        generated.write_bytes(b"native renderer owns these bytes")
        return row

    def read_transcript_snippet(row: Any) -> str | None:
        calls.append(("read_transcript_snippet", row.id))
        return None if row.transcript_burned else "native snippet"

    def burn_transcript(database: FakeDatabase, native_session_id: int) -> bool:
        calls.append(("burn_transcript", native_session_id))
        database.rows[native_session_id].transcript_burned = True
        return True

    home_visit = SimpleNamespace(
        create_session=create_session,
        run_phase1=run_phase1,
        run_phase2=run_phase2,
        read_transcript_snippet=read_transcript_snippet,
        burn_transcript=burn_transcript,
    )
    dependencies = {
        "Session": lambda engine: nullcontext(db),
        "VisitSession": object(),
        "engine": object(),
        "home_visit": home_visit,
        "init_db": lambda: calls.append(("init_db",)),
        "settings": SimpleNamespace(data_path=data_root),
    }
    monkeypatch.setattr(native_adapter, "_dependencies", lambda: dependencies)
    monkeypatch.setattr(
        native_adapter,
        "require_legacy_doc_capability",
        lambda path: calls.append(("doc_capability", Path(path).suffix)),
    )

    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"ID3audio")
    template = tmp_path / "template.docx"
    template.write_bytes(b"template")
    start = native_adapter.handle(
        "start",
        {
            "title": "Internal meeting",
            "note": "weekly",
            "mode": "internal_meeting",
            "audio_path": str(audio),
            "template_path": str(template),
        },
    )
    assert start["native_session_id"] == 17
    assert start["session"]["status"] == "pending_review"
    assert ("run_phase1", 17, "internal_meeting") in calls
    create_call = next(call for call in calls if call[0] == "create_session")
    assert create_call[3] == ("meeting.mp3", b"ID3audio")
    assert create_call[4] == ("template.docx", b"template")

    status = native_adapter.handle("status", {"native_session_id": 17})
    assert status["session"]["transcript_snippet"] == "native snippet"

    reviewed = native_adapter.handle(
        "review",
        {
            "native_session_id": 17,
            "slot_content_final": {"summary": "approved"},
            "reviewer": "worker-1",
        },
    )
    assert reviewed["session"]["status"] == "confirmed"
    assert reviewed["native_artifact_path"].endswith("visit_note_17_20260802.docx")
    assert ("run_phase2", 17, {"summary": "approved"}, "worker-1") in calls

    phase2_count = sum(call[0] == "run_phase2" for call in calls)
    exported = native_adapter.handle("export", {"native_session_id": 17})
    assert exported["native_artifact_path"] == reviewed["native_artifact_path"]
    assert sum(call[0] == "run_phase2" for call in calls) == phase2_count

    burned = native_adapter.handle("burn", {"native_session_id": 17})
    assert burned["burned"] is True
    assert burned["session"]["transcript_burned"] is True
    assert burned["session"]["transcript_snippet"] is None
    assert ("burn_transcript", 17) in calls
