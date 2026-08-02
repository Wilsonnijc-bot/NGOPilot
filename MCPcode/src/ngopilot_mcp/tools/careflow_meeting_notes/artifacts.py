"""Artifact semantics for CareFlow meeting-note DOCX output."""

from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile, ZipFile

ARTIFACT_KIND = "meeting_note_docx"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
_REQUIRED_DOCX_MEMBERS = frozenset({"[Content_Types].xml", "word/document.xml"})


def validate_native_docx(raw_path: str | Path) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        raise ValueError("CareFlow returned a non-absolute DOCX path")
    if path.suffix.lower() != ".docx":
        raise ValueError("CareFlow meeting-note output must be a .docx file")
    if not path.is_file():
        raise ValueError(f"CareFlow meeting-note output does not exist: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"CareFlow meeting-note output is empty: {path}")
    try:
        with ZipFile(path) as archive:
            missing = _REQUIRED_DOCX_MEMBERS.difference(archive.namelist())
    except BadZipFile as exc:
        raise ValueError(
            f"CareFlow meeting-note output is not a valid DOCX: {path}"
        ) from exc
    if missing:
        raise ValueError(
            "CareFlow meeting-note output is missing required DOCX members: "
            + ", ".join(sorted(missing))
        )
    return path.resolve(strict=True)
