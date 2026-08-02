"""Artifact semantics for native CareFlow filled PDFs."""

from __future__ import annotations

from pathlib import Path

from ngopilot_mcp.shared.errors import ToolError

ARTIFACT_KIND = "filled_government_form_pdf"
PDF_MEDIA_TYPE = "application/pdf"


def validate_native_pdf(
    raw_path: str | Path,
    *,
    expected_page_count: int,
    observed_page_count: int,
) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        raise ToolError(
            "OUTPUT_VALIDATION_FAILED",
            "CareFlow returned a non-absolute filled PDF path.",
        )
    if path.suffix.lower() != ".pdf":
        raise ToolError(
            "OUTPUT_VALIDATION_FAILED",
            "CareFlow government-form output must be a .pdf file.",
        )
    if not path.is_file() or path.stat().st_size <= 0:
        raise ToolError(
            "OUTPUT_VALIDATION_FAILED",
            "CareFlow filled PDF is missing or empty.",
            details={"path": str(path)},
        )
    if expected_page_count <= 0 or observed_page_count != expected_page_count:
        raise ToolError(
            "OUTPUT_VALIDATION_FAILED",
            "CareFlow filled PDF has an unexpected page count.",
            details={
                "path": str(path),
                "expected_page_count": expected_page_count,
                "observed_page_count": observed_page_count,
            },
        )
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ToolError(
                "OUTPUT_VALIDATION_FAILED",
                "CareFlow output does not have a valid PDF header.",
            )
        stream.seek(max(0, path.stat().st_size - 4096))
        if b"%%EOF" not in stream.read():
            raise ToolError(
                "OUTPUT_VALIDATION_FAILED",
                "CareFlow output is an incomplete PDF.",
            )
    return path.resolve(strict=True)
