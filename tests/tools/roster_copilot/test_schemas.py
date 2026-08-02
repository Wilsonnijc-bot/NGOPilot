from __future__ import annotations

import pytest
from pydantic import ValidationError

from ngopilot_mcp.tools.roster_copilot.schemas import (
    GetPublishedCall,
    PublishCall,
    ReviewCall,
    StartCall,
    validate_request,
)


def _start() -> dict[str, object]:
    return {
        "operation": "start",
        "job_id": None,
        "request_id": "start-1",
        "input": {
            "hc_workbook_path": "/tmp/hc.xlsx",
            "escort_workbook_path": "/tmp/escort.xlsm",
            "week_start": "2026-08-03",
            "changes": [{"type": "leave", "worker_id": "worker-1"}],
        },
    }


def _review(action: str = "approve") -> dict[str, object]:
    payload: dict[str, object] = {
        "source_version_id": "version-1",
        "content_hash": "hash-1",
        "idempotency_key": "review-once",
        "actor": "supervisor",
        "action": action,
        "audit_id": "audit-1",
        "audit_ids": ["audit-2", "audit-2"],
        "note": None,
        "override_note": None,
        "edited_entry": None,
    }
    return {"operation": "review", "job_id": "job-1", "input": payload}


def test_start_is_strict_and_preserves_structured_changes() -> None:
    request = validate_request(_start())
    assert isinstance(request, StartCall)
    assert request.input.week_start == "2026-08-03"
    assert request.input.changes == [{"type": "leave", "worker_id": "worker-1"}]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["input"].update(week_start="03/08/2026"),
        lambda value: value["input"].update(changes=["leave"]),
        lambda value: value["input"].update(changes={"type": "leave"}),
        lambda value: value["input"].update(unexpected=True),
        lambda value: value.update(job_id="caller-chosen"),
    ],
)
def test_invalid_start_variants_are_rejected(mutator: object) -> None:
    value = _start()
    mutator(value)  # type: ignore[operator]
    with pytest.raises(ValidationError):
        validate_request(value)


def test_review_canonicalizes_ids_and_matches_native_action_contract() -> None:
    request = validate_request(_review())
    assert isinstance(request, ReviewCall)
    assert request.input.audit_ids == ["audit-2"]

    reject = _review("reject")
    reject["input"]["note"] = "  supervisor bypass  "  # type: ignore[index]
    parsed = validate_request(reject)
    assert isinstance(parsed, ReviewCall)
    assert parsed.input.note == "supervisor bypass"


@pytest.mark.parametrize(
    "action, updates",
    [
        ("reject", {}),
        ("edit", {"note": "reason"}),
        ("approve", {"edited_entry": {"entry_id": "entry-1"}}),
        ("approve", {"override_note": "not allowed"}),
        (
            "edit",
            {
                "note": "reason",
                "edited_entry": {"entry_id": "entry-1", "elder_id": "forbidden"},
            },
        ),
    ],
)
def test_invalid_review_action_combinations_are_rejected(
    action: str,
    updates: dict[str, object],
) -> None:
    value = _review(action)
    value["input"].update(updates)  # type: ignore[union-attr]
    with pytest.raises(ValidationError):
        validate_request(value)


def test_edit_accepts_only_native_editable_patch_fields() -> None:
    value = _review("edit")
    value["input"].update(  # type: ignore[union-attr]
        {
            "note": "move worker",
            "override_note": "hard-rule explanation",
            "edited_entry": {
                "entry_id": "entry-1",
                "worker_id": "worker-2",
                "schedule_date": "2026-08-03",
                "period": "am",
                "session_index": 1,
                "start_time": "09:00:00",
                "end_time": "10:00:00",
                "notes": "reviewed",
            },
        }
    )
    request = validate_request(value)
    assert isinstance(request, ReviewCall)
    assert request.input.edited_entry["worker_id"] == "worker-2"


def test_publish_and_get_published_have_distinct_strict_payloads() -> None:
    publish = validate_request(
        {
            "operation": "publish",
            "job_id": "job-1",
            "input": {
                "actor": "supervisor",
                "source_version_id": "version-1",
                "content_hash": "hash-1",
            },
        }
    )
    get_published = validate_request(
        {
            "operation": "get_published",
            "job_id": "job-1",
            "input": {"publication_id": "publication-1"},
        }
    )
    assert isinstance(publish, PublishCall)
    assert isinstance(get_published, GetPublishedCall)

    with pytest.raises(ValidationError):
        validate_request(
            {
                "operation": "get_published",
                "job_id": "job-1",
                "input": {"publication_id": "publication-1", "actor": "x"},
            }
        )
