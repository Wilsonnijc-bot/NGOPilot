from __future__ import annotations

import pytest
from pydantic import ValidationError

from ngopilot_mcp.tools.careflow_paper_forms_to_excel.schemas import (
    FIELD_KEYS,
    ReviewCall,
    StartCall,
    validate_request,
)


def _final_fields() -> dict[str, object]:
    return {key: None for key in FIELD_KEYS}


def test_start_schema_is_strict_and_preserves_native_values() -> None:
    request = validate_request(
        {
            "operation": "start",
            "job_id": None,
            "request_id": "request-1",
            "input": {
                "title": "August volunteer visits",
                "image_paths": ["/tmp/form-01.jpg"],
                "volunteer_team": "Team A",
                "visit_date": "2026-08-02",
                "note": "morning round",
                "auto_complete": False,
            },
        }
    )

    assert isinstance(request, StartCall)
    assert request.input.visit_date == "2026-08-02"
    assert request.input.auto_complete is False


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "start", "input": {"title": "x", "image_paths": []}},
        {"operation": "start", "input": {"title": "  ", "image_paths": ["/tmp/a.jpg"]}},
        {
            "operation": "start",
            "input": {
                "title": "x",
                "image_paths": ["/tmp/a.jpg"],
                "visit_date": "02/08/2026",
            },
        },
        {
            "operation": "start",
            "input": {"title": "x", "image_paths": ["/tmp/a.jpg"], "auto_complete": 1},
        },
        {
            "operation": "start",
            "input": {"title": "x", "image_paths": ["/tmp/a.jpg"], "unexpected": True},
        },
        {"operation": "unknown", "input": {}},
    ],
)
def test_invalid_start_or_operation_is_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        validate_request(payload)


def test_review_requires_all_thirteen_fields() -> None:
    fields = _final_fields()
    fields.pop("follow_up_note")

    with pytest.raises(ValidationError):
        validate_request(
            {
                "operation": "review",
                "job_id": "job-1",
                "input": {"reviews": [{"record_id": 9, "final_fields": fields}]},
            }
        )


def test_review_accepts_complete_fields_and_rejects_extra_field() -> None:
    request = validate_request(
        {
            "operation": "review",
            "job_id": "job-1",
            "input": {
                "reviews": [
                    {
                        "record_id": 9,
                        "final_fields": _final_fields(),
                        "reviewer": "A. Reviewer",
                    }
                ]
            },
        }
    )
    assert isinstance(request, ReviewCall)
    assert tuple(request.input.reviews[0].final_fields.model_dump()) == FIELD_KEYS

    fields = _final_fields()
    fields["not_a_careflow_field"] = "x"
    with pytest.raises(ValidationError):
        validate_request(
            {
                "operation": "review",
                "job_id": "job-1",
                "input": {"reviews": [{"record_id": 9, "final_fields": fields}]},
            }
        )


def test_review_rejects_duplicate_record_ids() -> None:
    item = {"record_id": 9, "final_fields": _final_fields()}
    with pytest.raises(ValidationError):
        validate_request(
            {
                "operation": "review",
                "job_id": "job-1",
                "input": {"reviews": [item, item]},
            }
        )
