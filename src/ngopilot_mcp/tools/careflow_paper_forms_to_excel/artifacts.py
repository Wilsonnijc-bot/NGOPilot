"""Excel artifact semantics for CareFlow paper-form exports."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, is_zipfile

from ngopilot_mcp.shared.errors import ToolError

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
EXCEL_ARTIFACT_KIND = "volunteer_forms_excel"
MAX_UNCOMPRESSED_BYTES = 256 * 1024 * 1024


def _artifact_error(path: Path, reason: str) -> ToolError:
    return ToolError(
        "INVALID_ARTIFACT",
        f"CareFlow did not produce a valid Excel workbook: {reason}.",
        details={"native_path": str(path), "expected_extension": ".xlsx"},
    )


def validate_excel_artifact(source_path: str | Path) -> Path:
    """Reopen a generated OOXML workbook before it becomes caller-visible."""

    path = Path(source_path)
    if not path.is_absolute():
        raise _artifact_error(path, "the native output path is not absolute")
    resolved = path.resolve(strict=False)
    if resolved.suffix.lower() != ".xlsx":
        raise _artifact_error(resolved, "the output is not an .xlsx file")
    if not resolved.exists() or not resolved.is_file() or resolved.stat().st_size == 0:
        raise _artifact_error(resolved, "the output file is missing or empty")
    if not is_zipfile(resolved):
        raise _artifact_error(resolved, "the OOXML ZIP container is corrupt")

    required = {"[Content_Types].xml", "xl/workbook.xml"}
    try:
        with ZipFile(resolved) as workbook:
            names = set(workbook.namelist())
            missing = sorted(required - names)
            if missing:
                raise _artifact_error(
                    resolved, f"required OOXML entries are missing: {missing}"
                )
            if not any(
                name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                for name in names
            ):
                raise _artifact_error(resolved, "the workbook contains no worksheet")

            total_size = sum(info.file_size for info in workbook.infolist())
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise _artifact_error(
                    resolved, "the uncompressed workbook is unexpectedly large"
                )
            for name in required:
                ElementTree.fromstring(workbook.read(name))
    except ToolError:
        raise
    except (BadZipFile, KeyError, OSError, ElementTree.ParseError) as exc:
        raise _artifact_error(
            resolved, "the OOXML structure cannot be reopened"
        ) from exc

    return resolved
