"""XLSX integrity and naming rules for Roster-delivered workbooks."""

from __future__ import annotations

import hashlib
from pathlib import Path
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile, is_zipfile

from ngopilot_mcp.shared.errors import ToolError

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REVIEW_ARTIFACT_KIND = "roster_review_workbook"
FINAL_ARTIFACT_KIND = "roster_final_workbook"
REVIEW_FILENAME = "照顧員工作分工表_審核草稿.xlsx"
FINAL_FILENAME = "照顧員工作分工表_正式版.xlsx"
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_roster_workbook(
    raw_path: str | Path,
    *,
    expected_filename: str,
    expected_sha256: str | None = None,
) -> Path:
    path = Path(raw_path)
    details = {
        "native_path": str(path),
        "expected_filename": expected_filename,
    }
    if not path.is_absolute():
        raise ToolError(
            "INVALID_ARTIFACT",
            "RosterCopiilot returned a non-absolute workbook path.",
            details=details,
        )
    resolved = path.resolve(strict=False)
    valid_name = resolved.name == expected_filename or resolved.name.endswith(
        f"_{expected_filename}"
    )
    if not valid_name or resolved.suffix.lower() != ".xlsx":
        raise ToolError(
            "INVALID_ARTIFACT",
            f"RosterCopiilot did not return {expected_filename}.",
            details=details,
        )
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise ToolError(
            "INVALID_ARTIFACT",
            "The RosterCopiilot workbook is missing or empty.",
            details=details,
        )
    if not is_zipfile(resolved):
        raise ToolError(
            "INVALID_ARTIFACT",
            "The RosterCopiilot workbook is not a valid OOXML ZIP container.",
            details=details,
        )

    required = {"[Content_Types].xml", "xl/workbook.xml"}
    try:
        with ZipFile(resolved) as workbook:
            names = set(workbook.namelist())
            missing = sorted(required - names)
            if missing or not any(
                name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
                for name in names
            ):
                raise ToolError(
                    "INVALID_ARTIFACT",
                    "The RosterCopiilot workbook has an incomplete OOXML structure.",
                    details={**details, "missing_members": missing},
                )
            if (
                sum(info.file_size for info in workbook.infolist())
                > MAX_UNCOMPRESSED_BYTES
            ):
                raise ToolError(
                    "INVALID_ARTIFACT",
                    "The RosterCopiilot workbook is unexpectedly large when expanded.",
                    details=details,
                )
            for member in required:
                ElementTree.fromstring(workbook.read(member))
    except ToolError:
        raise
    except (BadZipFile, KeyError, OSError, ElementTree.ParseError) as exc:
        raise ToolError(
            "INVALID_ARTIFACT",
            "The RosterCopiilot workbook cannot be reopened structurally.",
            details=details,
        ) from exc

    actual_sha256 = sha256_file(resolved)
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise ToolError(
            "ARTIFACT_INTEGRITY_ERROR",
            "The final workbook does not match the native publication SHA-256.",
            details={
                **details,
                "expected_sha256": expected_sha256,
                "actual_sha256": actual_sha256,
            },
        )
    return resolved
