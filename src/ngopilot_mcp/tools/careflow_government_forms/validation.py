"""Government-form-specific request and review validation."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ngopilot_mcp.shared.errors import InvalidRequestError, ToolError

GUARANTEED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")
OPTIONAL_IMAGE_EXTENSIONS = (".heic", ".heif")
ALL_IMAGE_EXTENSIONS = GUARANTEED_IMAGE_EXTENSIONS + OPTIONAL_IMAGE_EXTENSIONS


def validate_image_source(
    raw_path: str,
    *,
    supported_extensions: tuple[str, ...],
) -> Path:
    path = Path(raw_path).expanduser()
    supported = tuple(extension.lower() for extension in supported_extensions)
    if not path.is_absolute():
        raise ToolError(
            "PATH_NOT_ABSOLUTE",
            "image_path must be an absolute local path.",
            details={"path": str(path)},
        )
    if path.is_symlink():
        raise ToolError(
            "PATH_NOT_ALLOWED",
            "image_path cannot be a symbolic link.",
            details={"path": str(path)},
        )
    if path.suffix.lower() not in supported:
        raise ToolError(
            "UNSUPPORTED_FILE_TYPE",
            "image_path uses a format unavailable in the managed CareFlow runtime.",
            details={"path": str(path), "supported_extensions": list(supported)},
        )
    if not path.exists():
        raise ToolError(
            "FILE_NOT_FOUND",
            "The elder-profile image does not exist.",
            details={"path": str(path)},
        )
    if not path.is_file():
        raise ToolError(
            "PATH_NOT_ALLOWED",
            "image_path must identify a regular file.",
            details={"path": str(path)},
        )
    if path.stat().st_size <= 0:
        raise ToolError(
            "EMPTY_FILE",
            "The elder-profile image is empty.",
            details={"path": str(path)},
        )
    return path.resolve(strict=True)


def supported_image_extensions(discovery: Mapping[str, Any]) -> tuple[str, ...]:
    capabilities = discovery.get("source_capabilities")
    extensions = (
        capabilities.get("image_extensions")
        if isinstance(capabilities, Mapping)
        else None
    )
    if not isinstance(extensions, list) or not all(
        isinstance(item, str) for item in extensions
    ):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow template discovery omitted image format capabilities.",
        )
    normalized = tuple(item.lower() for item in extensions)
    if not set(GUARANTEED_IMAGE_EXTENSIONS).issubset(normalized):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow did not report all guaranteed image formats.",
        )
    if any(item not in ALL_IMAGE_EXTENSIONS for item in normalized):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow reported an unknown government-form image format.",
        )
    return normalized


def require_ready_template(
    discovery: Mapping[str, Any],
    template_id: str,
) -> dict[str, Any]:
    templates = discovery.get("templates")
    if not isinstance(templates, list):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow template discovery omitted the ready template list.",
        )
    for template in templates:
        if isinstance(template, dict) and template.get("id") == template_id:
            return dict(template)
    available = [
        item.get("id")
        for item in templates
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]
    raise InvalidRequestError(
        f"Government-form template '{template_id}' is not ready.",
        details={"template_id": template_id, "available_template_ids": available},
    )


def preview_field_keys(result: Mapping[str, Any]) -> tuple[str, ...]:
    preview = result.get("preview")
    mappings = preview.get("mappings") if isinstance(preview, Mapping) else None
    if not isinstance(mappings, list) or not mappings:
        raise InvalidRequestError(
            "This job has no reviewable CareFlow mapping preview."
        )
    keys: list[str] = []
    for index, mapping in enumerate(mappings):
        key = mapping.get("key") if isinstance(mapping, Mapping) else None
        if not isinstance(key, str) or not key:
            raise ToolError(
                "NATIVE_PROTOCOL_ERROR",
                f"CareFlow preview mapping {index} has no valid field key.",
            )
        if key in keys:
            raise ToolError(
                "NATIVE_PROTOCOL_ERROR",
                f"CareFlow preview repeats field key '{key}'.",
            )
        keys.append(key)
    return tuple(keys)


def validate_complete_field_values(
    result: Mapping[str, Any],
    field_values: Mapping[str, str],
) -> None:
    expected = preview_field_keys(result)
    supplied = set(field_values)
    expected_set = set(expected)
    missing = [key for key in expected if key not in supplied]
    extra = sorted(supplied - expected_set)
    if missing or extra:
        raise InvalidRequestError(
            "field_values must be the complete replacement set for the preview.",
            details={"missing_fields": missing, "unknown_fields": extra},
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
