"""Roster workbook-role validation before shared immutable staging."""

from __future__ import annotations

from pathlib import Path

from ngopilot_mcp.shared.errors import ToolError

ALLOWED_WORKBOOK_EXTENSIONS = (".xlsx", ".xlsm")
MAX_WORKBOOK_BYTES = 10 * 1024 * 1024


def validate_workbook_source(raw_path: str, *, role: str) -> Path:
    path = Path(raw_path).expanduser()
    details = {
        "role": role,
        "path": str(path),
        "allowed_extensions": list(ALLOWED_WORKBOOK_EXTENSIONS),
        "max_bytes": MAX_WORKBOOK_BYTES,
    }
    if not path.is_absolute():
        raise ToolError(
            "PATH_NOT_ABSOLUTE",
            f"The {role} must be an absolute local workbook path.",
            details=details,
        )
    if path.is_symlink():
        raise ToolError(
            "PATH_NOT_ALLOWED",
            f"The {role} cannot be a symbolic link.",
            details=details,
        )
    if path.suffix.lower() not in ALLOWED_WORKBOOK_EXTENSIONS:
        raise ToolError(
            "UNSUPPORTED_FILE_TYPE",
            f"The {role} must be an .xlsx or .xlsm workbook.",
            details=details,
        )
    if not path.exists() or not path.is_file():
        raise ToolError(
            "FILE_NOT_FOUND",
            f"The {role} must identify an existing regular workbook.",
            details=details,
        )
    size = path.stat().st_size
    if size <= 0:
        raise ToolError("EMPTY_FILE", f"The {role} workbook is empty.", details=details)
    if size > MAX_WORKBOOK_BYTES:
        details["size_bytes"] = size
        raise ToolError(
            "FILE_TOO_LARGE",
            f"The {role} exceeds the {MAX_WORKBOOK_BYTES}-byte limit.",
            details=details,
        )
    return path.resolve(strict=True)
