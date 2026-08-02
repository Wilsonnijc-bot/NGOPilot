from __future__ import annotations

import pytest
from pydantic import ValidationError

from ngopilot_mcp.tools.careflow_government_forms.schemas import validate_request


@pytest.mark.parametrize(
    "source",
    [
        {"kind": "text", "text": "長者資料"},
        {"kind": "image", "image_path": "/tmp/elder.jpg"},
        {"kind": "elder_profile", "elder_profile": {}},
    ],
)
def test_start_accepts_exactly_the_three_profile_sources(
    source: dict[str, object],
) -> None:
    request = validate_request(
        {
            "operation": "start",
            "job_id": None,
            "input": {"template_id": "oala", "use_llm": False, "source": source},
        }
    )
    assert request.input.source.kind == source["kind"]


@pytest.mark.parametrize(
    "payload",
    [
        {
            "template_id": "../oala",
            "use_llm": False,
            "source": {"kind": "text", "text": "data"},
        },
        {
            "template_id": "oala",
            "source": {"kind": "text", "text": "data"},
        },
        {
            "template_id": "oala",
            "use_llm": 0,
            "source": {"kind": "text", "text": "data"},
        },
        {
            "template_id": "oala",
            "use_llm": False,
            "source": {"kind": "text", "text": " "},
        },
        {
            "template_id": "oala",
            "use_llm": False,
            "source": {
                "kind": "image",
                "image_path": "/tmp/a.jpg",
                "text": "two sources",
            },
        },
    ],
)
def test_start_contract_rejects_unsafe_coerced_or_cross_variant_input(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        validate_request({"operation": "start", "job_id": None, "input": payload})


def test_operation_variants_enforce_job_id_and_empty_inputs() -> None:
    validate_request({"operation": "list_templates", "job_id": None, "input": {}})
    validate_request({"operation": "status", "job_id": "job-1", "input": {}})

    with pytest.raises(ValidationError):
        validate_request(
            {"operation": "list_templates", "job_id": "job-1", "input": {}}
        )
    with pytest.raises(ValidationError):
        validate_request({"operation": "status", "job_id": None, "input": {}})
    with pytest.raises(ValidationError):
        validate_request(
            {"operation": "export", "job_id": "job-1", "input": {"force": True}}
        )


def test_review_values_are_strict_strings() -> None:
    request = validate_request(
        {
            "operation": "review",
            "job_id": "job-1",
            "input": {"field_values": {"name": "", "age": "80"}},
        }
    )
    assert request.input.field_values == {"name": "", "age": "80"}

    with pytest.raises(ValidationError):
        validate_request(
            {
                "operation": "review",
                "job_id": "job-1",
                "input": {"field_values": {"age": 80}},
            }
        )


def test_elder_profile_rejects_non_json_values() -> None:
    with pytest.raises(ValidationError):
        validate_request(
            {
                "operation": "start",
                "job_id": None,
                "input": {
                    "template_id": "oala",
                    "use_llm": False,
                    "source": {
                        "kind": "elder_profile",
                        "elder_profile": {"opaque": object()},
                    },
                },
            }
        )
