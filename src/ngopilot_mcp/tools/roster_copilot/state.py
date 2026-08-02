"""Interpret Roster state without duplicating roster-domain decisions."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from ngopilot_mcp.shared.errors import ToolError

from .artifacts import sha256_file

NATIVE_STATES = frozenset({"blocked", "draft", "ready", "published"})


def unpack_worker_result(
    response: Mapping[str, Any],
) -> tuple[dict[str, Any], str, dict[str, Any], list[str | dict[str, Any]]]:
    result = response.get("result")
    native_status = response.get("native_status")
    native_refs = response.get("native_refs", {})
    warnings = response.get("warnings", [])
    if not isinstance(result, dict) or not isinstance(native_status, str):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "RosterCopiilot omitted its result or publication state.",
        )
    if native_status not in NATIVE_STATES:
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            f"RosterCopiilot returned unknown state '{native_status}'.",
        )
    if not isinstance(native_refs, dict) or not isinstance(warnings, list):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "RosterCopiilot returned an invalid worker envelope.",
        )
    return (
        deepcopy(result),
        native_status,
        deepcopy(native_refs),
        deepcopy(warnings),
    )


def normalized_state(native_status: str) -> str:
    if native_status not in NATIVE_STATES:
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            f"RosterCopiilot returned unknown state '{native_status}'.",
        )
    return native_status


def native_run_id(job: Any) -> str | None:
    value = getattr(job, "native_refs", {}).get("run_id")
    return value if isinstance(value, str) and value else None


def merge_native_refs(job: Any, incoming: Mapping[str, Any]) -> dict[str, Any]:
    refs = deepcopy(getattr(job, "native_refs", {}))
    refs.update(deepcopy(dict(incoming)))
    return refs


def staged_workbook_ref(path: Path, *, role: str, original_name: str) -> dict[str, Any]:
    return {
        "role": role,
        "original_name": original_name,
        "staged_path": str(path.resolve(strict=True)),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def next_operations(result: Mapping[str, Any], native_status: str) -> list[str]:
    operations = ["status", "revalidate"]
    audit_items = result.get("audit_items")
    if isinstance(audit_items, list) and any(
        isinstance(item, Mapping) and item.get("status") == "pending"
        for item in audit_items
    ):
        operations.append("review")
    if result.get("review_export_allowed") is True:
        operations.append("export")
    if native_status == "ready" and result.get("publication") is None:
        operations.append("publish")
    publications = result.get("publications")
    if isinstance(publications, list) and publications:
        operations.append("get_published")
    return operations


def publication_artifact(job: Any, publication_id: str) -> dict[str, Any] | None:
    raw = getattr(job, "native_refs", {}).get("publication_artifacts", {})
    if not isinstance(raw, Mapping):
        return None
    value = raw.get(publication_id)
    return deepcopy(dict(value)) if isinstance(value, Mapping) else None


def record_publication_artifact(
    refs: dict[str, Any],
    *,
    publication_id: str,
    artifact: Any,
) -> dict[str, Any]:
    projected = deepcopy(refs)
    mappings = projected.get("publication_artifacts", {})
    if not isinstance(mappings, dict):
        mappings = {}
    mappings[publication_id] = {
        "artifact_id": artifact.artifact_id,
        "path": artifact.path,
        "sha256": artifact.sha256,
    }
    projected["publication_artifacts"] = mappings
    return projected
