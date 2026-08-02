from __future__ import annotations

from pathlib import Path

import pytest

from ngopilot_mcp.shared.errors import InvalidRequestError, ToolError
from ngopilot_mcp.tools.careflow_government_forms.validation import (
    require_ready_template,
    supported_image_extensions,
    validate_complete_field_values,
    validate_image_source,
)


def _discovery(*, image_extensions: list[str] | None = None) -> dict[str, object]:
    return {
        "count": 1,
        "templates": [{"id": "oala", "field_count": 2}],
        "source_capabilities": {
            "image_extensions": image_extensions or [".jpg", ".jpeg", ".png"]
        },
    }


def test_ready_template_and_capabilities_are_taken_from_native_discovery() -> None:
    discovery = _discovery()
    assert require_ready_template(discovery, "oala")["field_count"] == 2
    assert supported_image_extensions(discovery) == (".jpg", ".jpeg", ".png")
    with pytest.raises(InvalidRequestError) as error:
        require_ready_template(discovery, "joyyou")
    assert error.value.details["available_template_ids"] == ["oala"]


def test_image_source_requires_discovered_format_and_absolute_file(
    tmp_path: Path,
) -> None:
    image = tmp_path / "elder.jpg"
    image.write_bytes(b"\xff\xd8\xffelder\xff\xd9")
    assert (
        validate_image_source(
            str(image.resolve()),
            supported_extensions=(".jpg", ".jpeg", ".png"),
        )
        == image.resolve()
    )

    heic = tmp_path / "elder.heic"
    heic.write_bytes(b"\x00\x00\x00\x18ftypheic")
    with pytest.raises(ToolError) as error:
        validate_image_source(
            str(heic.resolve()),
            supported_extensions=(".jpg", ".jpeg", ".png"),
        )
    assert error.value.code == "UNSUPPORTED_FILE_TYPE"

    link = tmp_path / "elder-link.jpg"
    link.symlink_to(image)
    with pytest.raises(ToolError) as symlink_error:
        validate_image_source(
            str(link),
            supported_extensions=(".jpg", ".jpeg", ".png"),
        )
    assert symlink_error.value.code == "PATH_NOT_ALLOWED"


def test_review_must_replace_exact_preview_key_set() -> None:
    result = {
        "preview": {
            "mappings": [
                {"key": "name", "value": "draft"},
                {"key": "phone", "value": ""},
            ]
        }
    }
    validate_complete_field_values(result, {"name": "final", "phone": ""})

    with pytest.raises(InvalidRequestError) as missing:
        validate_complete_field_values(result, {"name": "final"})
    assert missing.value.details == {
        "missing_fields": ["phone"],
        "unknown_fields": [],
    }

    with pytest.raises(InvalidRequestError) as extra:
        validate_complete_field_values(
            result,
            {"name": "final", "phone": "", "other": "x"},
        )
    assert extra.value.details["unknown_fields"] == ["other"]
