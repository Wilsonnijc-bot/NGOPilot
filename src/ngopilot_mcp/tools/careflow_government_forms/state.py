"""Government-form job projections and worker-envelope checks."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from ngopilot_mcp.shared.errors import ToolError


def validate_discovery(response: object) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow returned a non-object template discovery response.",
        )
    templates = response.get("templates")
    count = response.get("count")
    capabilities = response.get("source_capabilities")
    if not isinstance(templates, list) or not isinstance(count, int):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow template discovery omitted templates or count.",
        )
    if count != len(templates) or not isinstance(capabilities, dict):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow template discovery returned inconsistent metadata.",
        )
    return deepcopy(response)


def unpack_start(response: object) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    result, native_refs, warnings = _unpack(response)
    profile = result.get("elder_profile")
    preview = result.get("preview")
    if not isinstance(profile, dict) or not isinstance(preview, dict):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow omitted the elder profile or mapping preview.",
        )
    if not isinstance(preview.get("mappings"), list) or not isinstance(
        preview.get("summary"), dict
    ):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow returned an invalid government-form mapping preview.",
        )
    return result, native_refs, warnings


def unpack_export(
    response: object,
) -> tuple[dict[str, Any], dict[str, Any], list[Any], str, int]:
    result, native_refs, warnings = _unpack(response)
    if not isinstance(response, dict):
        raise AssertionError("_unpack accepted a non-dictionary response")
    artifact_path = response.get("artifact_path")
    page_count = response.get("artifact_page_count")
    if not isinstance(artifact_path, str) or not isinstance(page_count, int):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow omitted the filled PDF path or page count.",
        )
    return result, native_refs, warnings, artifact_path, page_count


def _unpack(
    response: object,
) -> tuple[dict[str, Any], dict[str, Any], list[Any]]:
    if not isinstance(response, dict):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow returned a non-object government-form response.",
        )
    result = response.get("result")
    native_refs = response.get("native_refs", {})
    warnings = response.get("warnings", [])
    if not isinstance(result, dict):
        raise ToolError("NATIVE_PROTOCOL_ERROR", "CareFlow omitted its result object.")
    if not isinstance(native_refs, dict) or not isinstance(warnings, list):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow returned an invalid government-form worker envelope.",
        )
    return deepcopy(result), deepcopy(native_refs), deepcopy(warnings)


def reviewed_values(result: Mapping[str, Any]) -> dict[str, str] | None:
    values = result.get("reviewed_values")
    if not isinstance(values, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in values.items()
    ):
        return None
    return dict(values)
