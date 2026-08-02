from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from ngopilot_mcp.tools.careflow_meeting_notes.schemas import parse_request
from ngopilot_mcp.tools.careflow_meeting_notes.validation import (
    validate_complete_slot_content,
    validate_start_files,
)


@pytest.mark.parametrize("mode", ["home_visit", "internal_meeting"])
def test_start_accepts_both_native_prompt_modes(mode: str) -> None:
    request = parse_request(
        {
            "operation": "start",
            "job_id": None,
            "request_id": "request-1",
            "input": {
                "title": "Weekly case meeting",
                "mode": mode,
                "audio_path": "/tmp/meeting.m4a",
                "template_path": "/tmp/template.docx",
            },
        }
    )
    assert request.input.mode == mode


@pytest.mark.parametrize(
    "mutation",
    [
        {"unknown": True},
        {"mode": "other"},
        {"title": " "},
    ],
)
def test_start_schema_is_strict(mutation: dict[str, object]) -> None:
    data: dict[str, object] = {
        "title": "Case meeting",
        "mode": "home_visit",
        "audio_path": "/tmp/meeting.mp3",
        "template_path": "/tmp/template.docx",
    }
    data.update(mutation)
    with pytest.raises(ValidationError):
        parse_request({"operation": "start", "job_id": None, "input": data})


def test_review_rejects_non_json_content() -> None:
    with pytest.raises(ValidationError):
        parse_request(
            {
                "operation": "review",
                "job_id": "job-1",
                "input": {"slot_content_final": {"summary": object()}},
            }
        )


def test_file_roles_require_absolute_supported_nonempty_files(tmp_path: Path) -> None:
    audio = tmp_path / "meeting.mp3"
    audio.write_bytes(b"ID3audio")
    template = tmp_path / "template.docx"
    template.write_bytes(b"not-empty")
    request = parse_request(
        {
            "operation": "start",
            "job_id": None,
            "input": {
                "title": "Case meeting",
                "mode": "home_visit",
                "audio_path": str(audio),
                "template_path": str(template),
            },
        }
    )
    assert validate_start_files(request.input) == (audio.resolve(), template.resolve())

    request.input.template_path = str(tmp_path / "blank.pdf")
    (tmp_path / "blank.pdf").write_bytes(b"%PDF-1.7")
    with pytest.raises(ValueError, match="template_path.*unsupported"):
        validate_start_files(request.input)


def test_complete_review_requires_exact_dynamic_slot_set() -> None:
    contract = {
        "dynamic_slots": [
            {"slot_id": "summary"},
            {"slot_id": "follow_up"},
        ]
    }
    validate_complete_slot_content(
        contract,
        {"summary": "摘要", "follow_up": ["跟進事項"]},
    )
    with pytest.raises(ValueError, match="missing: follow_up"):
        validate_complete_slot_content(contract, {"summary": "摘要"})
    with pytest.raises(ValueError, match="unknown.*other"):
        validate_complete_slot_content(
            contract,
            {"summary": "摘要", "follow_up": "跟進", "other": "x"},
        )
