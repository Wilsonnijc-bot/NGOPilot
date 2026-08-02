from __future__ import annotations

import hashlib
from pathlib import Path
from zipfile import ZipFile

import pytest

from ngopilot_mcp.shared.errors import ToolError
from ngopilot_mcp.tools.roster_copilot.artifacts import (
    FINAL_FILENAME,
    REVIEW_FILENAME,
    validate_roster_workbook,
)
from ngopilot_mcp.tools.roster_copilot.validation import (
    MAX_WORKBOOK_BYTES,
    validate_workbook_source,
)


def write_xlsx(path: Path) -> Path:
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
    return path.resolve()


def test_review_and_promoted_final_names_are_structurally_verified(
    tmp_path: Path,
) -> None:
    review = write_xlsx(tmp_path / REVIEW_FILENAME)
    promoted = write_xlsx(tmp_path / f"abc123_{FINAL_FILENAME}")
    digest = hashlib.sha256(promoted.read_bytes()).hexdigest()

    assert (
        validate_roster_workbook(
            review,
            expected_filename=REVIEW_FILENAME,
        )
        == review
    )
    assert (
        validate_roster_workbook(
            promoted,
            expected_filename=FINAL_FILENAME,
            expected_sha256=digest,
        )
        == promoted
    )


@pytest.mark.parametrize("content", [b"", b"not an xlsx"])
def test_corrupt_output_is_rejected(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / FINAL_FILENAME
    path.write_bytes(content)
    with pytest.raises(ToolError) as error:
        validate_roster_workbook(path.resolve(), expected_filename=FINAL_FILENAME)
    assert error.value.code == "INVALID_ARTIFACT"


def test_publication_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    path = write_xlsx(tmp_path / FINAL_FILENAME)
    with pytest.raises(ToolError) as error:
        validate_roster_workbook(
            path,
            expected_filename=FINAL_FILENAME,
            expected_sha256="0" * 64,
        )
    assert error.value.code == "ARTIFACT_INTEGRITY_ERROR"


def test_input_validation_accepts_only_absolute_nonempty_workbooks(
    tmp_path: Path,
) -> None:
    workbook = write_xlsx(tmp_path / "hc.XLSX")
    assert validate_workbook_source(str(workbook), role="hc_workbook_path") == workbook

    with pytest.raises(ToolError) as error:
        validate_workbook_source("relative.xlsx", role="hc_workbook_path")
    assert error.value.code == "PATH_NOT_ABSOLUTE"

    oversized = tmp_path / "oversized.xlsx"
    with oversized.open("wb") as stream:
        stream.truncate(MAX_WORKBOOK_BYTES + 1)
    with pytest.raises(ToolError) as error:
        validate_workbook_source(str(oversized.resolve()), role="escort_workbook_path")
    assert error.value.code == "FILE_TOO_LARGE"
