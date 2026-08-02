"""Input-role validation specific to completed volunteer-form images."""

from __future__ import annotations

from pathlib import Path

from ngopilot_mcp.shared.errors import ToolError

ALLOWED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")


def _invalid(path: Path, reason: str) -> ToolError:
    return ToolError(
        "UNSUPPORTED_FILE_TYPE",
        (
            f"'{path}' is not a supported completed volunteer-form image: "
            f"{reason}. Attach a non-empty JPG, JPEG, or PNG image."
        ),
        details={
            "path": str(path),
            "expected_role": "completed_volunteer_form_image",
            "allowed_extensions": list(ALLOWED_IMAGE_EXTENSIONS),
        },
    )


def validate_image_source(source_path: str) -> Path:
    """Perform role checks before shared staging performs its full file audit."""

    path = Path(source_path)
    if not path.is_absolute():
        raise _invalid(path, "the path is not absolute")
    if path.is_symlink():
        raise _invalid(path, "symbolic links are not accepted")
    if path.suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS:
        raise _invalid(path, "the filename extension does not match this tool")
    if not path.exists() or not path.is_file():
        raise _invalid(path, "the path is not an existing regular file")
    if path.stat().st_size == 0:
        raise _invalid(path, "the file is empty")

    with path.open("rb") as source:
        header = source.read(32)
        source.seek(max(path.stat().st_size - 64, 0))
        trailer = source.read()

    suffix = path.suffix.lower()
    if suffix == ".png":
        valid_content = (
            header.startswith(b"\x89PNG\r\n\x1a\n")
            and header[12:16] == b"IHDR"
            and b"IEND" in trailer
        )
    else:
        valid_content = header.startswith(b"\xff\xd8\xff") and b"\xff\xd9" in trailer
    if not valid_content:
        raise _invalid(
            path, "the file content is corrupt or does not match its extension"
        )

    return path.resolve(strict=True)


def start_warnings(image_count: int) -> list[str]:
    if image_count > 20:
        return [
            f"This batch contains {image_count} images; CareFlow recommends at most 20 per batch."
        ]
    return []
