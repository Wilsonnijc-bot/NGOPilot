"""Interpret CareFlow paper-batch state without reimplementing domain logic."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ngopilot_mcp.shared.errors import ToolError

NATIVE_TO_MCP_STATE = {
    "uploaded": "running",
    "extracting": "running",
    "pending_review": "pending_review",
    "confirmed": "reviewed",
    "exported": "exported",
    "failed": "failed",
}


def unpack_worker_result(
    response: dict[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any], list[str | dict[str, Any]]]:
    if not isinstance(response, dict):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR", "CareFlow returned a non-object response."
        )
    result = response.get("result")
    native_status = response.get("native_status")
    native_refs = response.get("native_refs", {})
    warnings = response.get("warnings", [])
    if not isinstance(result, dict) or not isinstance(native_status, str):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "CareFlow omitted its result or native batch status.",
        )
    if not isinstance(native_refs, dict) or not isinstance(warnings, list):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR", "CareFlow returned an invalid worker envelope."
        )
    return deepcopy(result), native_status, deepcopy(native_refs), deepcopy(warnings)


def normalized_state(native_status: str) -> str:
    try:
        return NATIVE_TO_MCP_STATE[native_status]
    except KeyError as exc:
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            f"CareFlow returned unknown batch status '{native_status}'.",
        ) from exc


def next_operations(result: dict[str, Any], native_status: str) -> list[str]:
    if native_status in {"uploaded", "extracting"}:
        return ["status"]
    if native_status == "failed":
        return ["status"]

    operations = ["status", "review"]
    if int(result.get("reviewed_count", 0)) > 0:
        operations.append("export")
    return operations


def record_ids(result: dict[str, Any]) -> list[int]:
    records = result.get("records", [])
    if not isinstance(records, list):
        return []
    return [
        record["id"]
        for record in records
        if isinstance(record, dict) and isinstance(record.get("id"), int)
    ]


def add_source_paths(
    result: dict[str, Any],
    source_paths: dict[str, str],
) -> dict[str, Any]:
    projected = deepcopy(result)
    records = projected.get("records", [])
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            source_path = source_paths.get(str(record.get("id")))
            if source_path is not None:
                record["source_path"] = source_path
    return projected


def native_batch_id(job: Any) -> int | None:
    value = getattr(job, "native_refs", {}).get("batch_id")
    return value if isinstance(value, int) and value > 0 else None
