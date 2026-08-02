from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from ngopilot_mcp.shared.errors import ToolError
from ngopilot_mcp.tools.careflow_paper_forms_to_excel.artifacts import (
    validate_excel_artifact,
)
from ngopilot_mcp.tools.careflow_paper_forms_to_excel.validation import (
    validate_image_source,
)


def _write_workbook(path: Path) -> None:
    with ZipFile(path, "w") as workbook:
        workbook.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        workbook.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
        )
        workbook.writestr(
            "xl/worksheets/sheet1.xml",
            '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"/>',
        )


def test_generated_xlsx_is_reopened_structurally(tmp_path: Path) -> None:
    path = tmp_path / "batch_7.xlsx"
    _write_workbook(path)
    assert validate_excel_artifact(path) == path.resolve()


@pytest.mark.parametrize("content", [b"", b"not a workbook"])
def test_missing_or_corrupt_xlsx_is_rejected(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "batch_7.xlsx"
    path.write_bytes(content)
    with pytest.raises(ToolError, match="valid Excel workbook"):
        validate_excel_artifact(path)


def test_image_validation_checks_content_not_only_suffix(tmp_path: Path) -> None:
    path = tmp_path / "form.jpg"
    path.write_bytes(b"this is not jpeg content")
    with pytest.raises(ToolError) as error:
        validate_image_source(str(path.resolve()))
    assert error.value.code == "UNSUPPORTED_FILE_TYPE"


def test_minimal_jpeg_content_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "form.jpeg"
    path.write_bytes(b"\xff\xd8\xff\xe0" + b"content" + b"\xff\xd9")
    assert validate_image_source(str(path.resolve())) == path.resolve()
