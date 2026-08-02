from __future__ import annotations

from pathlib import Path

import pytest

from ngopilot_mcp.shared.errors import ToolError
from ngopilot_mcp.tools.careflow_government_forms.artifacts import validate_native_pdf


def _pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n")
    return path.resolve()


def test_pdf_requires_absolute_complete_file_and_matching_native_page_count(
    tmp_path: Path,
) -> None:
    path = _pdf(tmp_path / "filled.pdf")
    assert (
        validate_native_pdf(
            path,
            expected_page_count=7,
            observed_page_count=7,
        )
        == path
    )

    with pytest.raises(ToolError, match="page count"):
        validate_native_pdf(path, expected_page_count=7, observed_page_count=6)


@pytest.mark.parametrize(
    "name,content",
    [
        ("filled.txt", b"%PDF-1.7\n%%EOF"),
        ("filled.pdf", b"not-pdf\n%%EOF"),
        ("filled.pdf", b"%PDF-1.7\ntruncated"),
    ],
)
def test_corrupt_or_wrong_type_pdf_is_rejected(
    tmp_path: Path,
    name: str,
    content: bytes,
) -> None:
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(ToolError) as error:
        validate_native_pdf(
            path.resolve(), expected_page_count=1, observed_page_count=1
        )
    assert error.value.code == "OUTPUT_VALIDATION_FAILED"
