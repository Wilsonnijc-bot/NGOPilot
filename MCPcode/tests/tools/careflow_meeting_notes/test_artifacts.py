from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from ngopilot_mcp.tools.careflow_meeting_notes.artifacts import validate_native_docx


def _docx(path: Path) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<w:document/>")
    return path


def test_docx_validation_reopens_structural_package(tmp_path: Path) -> None:
    output = _docx(tmp_path / "meeting-note.docx")
    assert validate_native_docx(output) == output.resolve()


@pytest.mark.parametrize("filename", ["meeting-note.pdf", "meeting-note.docx"])
def test_docx_validation_rejects_wrong_or_corrupt_output(
    tmp_path: Path,
    filename: str,
) -> None:
    output = tmp_path / filename
    output.write_bytes(b"not-a-docx")
    with pytest.raises(ValueError):
        validate_native_docx(output)
