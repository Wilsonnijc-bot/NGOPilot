"""Worker-only adapter for RosterCopiilot's durable weekly demo facade."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

from ngopilot_mcp.shared.errors import ToolError

from .artifacts import REVIEW_FILENAME

DEPENDENCY_VERSION = "0.6.0"


def _bindings() -> SimpleNamespace:
    # This function is the only Roster application import boundary.
    from app.api import demo
    from app.services.weekly_publication import WeeklyPublicationCommand
    from app.services.weekly_review import WeeklyRevalidateCommand, WeeklyReviewCommand
    from starlette.datastructures import UploadFile

    return SimpleNamespace(
        demo=demo,
        UploadFile=UploadFile,
        WeeklyPublicationCommand=WeeklyPublicationCommand,
        WeeklyRevalidateCommand=WeeklyRevalidateCommand,
        WeeklyReviewCommand=WeeklyReviewCommand,
    )


def _required_run_id(payload: dict[str, Any]) -> str:
    value = payload.get("native_run_id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("native_run_id must be a non-empty string")
    return value.strip()


def _required_command(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("command")
    if not isinstance(value, dict):
        raise ValueError("command must be an object")
    return value


def _required_staged_path(payload: dict[str, Any], key: str) -> Path:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a staged absolute path")
    path = Path(value)
    if not path.is_absolute() or not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"{key} must be a staged absolute non-empty file")
    return path.resolve(strict=True)


def _required_plain_filename(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise ValueError(f"{key} must be a plain filename")
    return value


def _start(bindings: SimpleNamespace, payload: dict[str, Any]) -> dict[str, Any]:
    hc_path = _required_staged_path(payload, "hc_workbook_path")
    escort_path = _required_staged_path(payload, "escort_workbook_path")
    hc_name = _required_plain_filename(payload, "hc_original_filename")
    escort_name = _required_plain_filename(payload, "escort_original_filename")
    week_start = date.fromisoformat(str(payload.get("week_start", "")))
    changes = payload.get("changes")
    if not isinstance(changes, list) or any(
        not isinstance(item, dict) for item in changes
    ):
        raise ValueError("changes must be an array of objects")

    with hc_path.open("rb") as hc_stream, escort_path.open("rb") as escort_stream:
        result = _native_call(
            lambda: asyncio.run(
                bindings.demo.build_weekly_roster(
                    hc_workbook=bindings.UploadFile(
                        file=hc_stream,
                        filename=hc_name,
                    ),
                    escort_workbook=bindings.UploadFile(
                        file=escort_stream,
                        filename=escort_name,
                    ),
                    week_start=week_start,
                    changes_json=json.dumps(changes, ensure_ascii=False),
                )
            )
        )
    return _envelope(bindings, result)


def _status(bindings: SimpleNamespace, payload: dict[str, Any]) -> dict[str, Any]:
    result = _native_call(
        lambda: bindings.demo.get_weekly_roster(_required_run_id(payload))
    )
    return _envelope(bindings, result)


def _review(bindings: SimpleNamespace, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _required_run_id(payload)
    command = bindings.WeeklyReviewCommand.model_validate(_required_command(payload))
    result = _native_call(
        lambda: bindings.demo.decide_weekly_roster_audit(run_id, command)
    )
    return _envelope(bindings, result)


def _revalidate(bindings: SimpleNamespace, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _required_run_id(payload)
    command = bindings.WeeklyRevalidateCommand.model_validate(
        _required_command(payload)
    )
    result = _native_call(
        lambda: bindings.demo.revalidate_weekly_roster(run_id, command)
    )
    return _envelope(bindings, result)


def _export(bindings: SimpleNamespace, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _required_run_id(payload)
    response = _native_call(lambda: bindings.demo.export_weekly_roster(run_id))
    native_path = Path(response.path).resolve(strict=True)
    delivery_path = _delivery_copy(native_path, REVIEW_FILENAME)
    result = _native_call(lambda: bindings.demo.get_weekly_roster(run_id))
    result["review_export"] = {
        "filename": REVIEW_FILENAME,
        "native_filename": native_path.name,
    }
    envelope = _envelope(bindings, result)
    envelope.update(
        {
            "artifact_path": str(delivery_path),
            "native_source_path": str(native_path),
        }
    )
    return envelope


def _publish(bindings: SimpleNamespace, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _required_run_id(payload)
    command = bindings.WeeklyPublicationCommand.model_validate(
        _required_command(payload)
    )
    result = _native_call(lambda: bindings.demo.publish_weekly_roster(run_id, command))
    publication_id = _publication_id(result.get("publication"))
    publication = _native_publication(bindings, run_id, publication_id)
    envelope = _envelope(bindings, result, native_status="published")
    envelope.update(
        {
            "artifact_path": publication.artifact_path,
            "artifact_sha256": publication.artifact_sha256,
            "publication_id": publication.publication_id,
        }
    )
    return envelope


def _get_published(
    bindings: SimpleNamespace, payload: dict[str, Any]
) -> dict[str, Any]:
    run_id = _required_run_id(payload)
    command = _required_command(payload)
    publication_id = command.get("publication_id")
    if not isinstance(publication_id, str) or not publication_id.strip():
        raise ValueError("publication_id must be a non-empty string")
    publication_id = publication_id.strip()
    response = _native_call(
        lambda: bindings.demo.download_published_weekly_roster(run_id, publication_id)
    )
    publication = _native_publication(bindings, run_id, publication_id)
    if Path(response.path).resolve(strict=True) != Path(
        publication.artifact_path
    ).resolve(strict=True):
        raise ToolError(
            "PUBLICATION_ARTIFACT_CORRUPT",
            "RosterCopiilot resolved conflicting publication artifact paths.",
            native_code="PUBLICATION_ARTIFACT_CORRUPT",
        )
    result = _native_call(lambda: bindings.demo.get_weekly_roster(run_id))
    result["requested_publication"] = bindings.demo._public_publication(publication)
    envelope = _envelope(bindings, result, native_status="published")
    envelope.update(
        {
            "artifact_path": publication.artifact_path,
            "artifact_sha256": publication.artifact_sha256,
            "publication_id": publication.publication_id,
        }
    )
    return envelope


def _native_publication(
    bindings: SimpleNamespace,
    run_id: str,
    publication_id: str,
) -> Any:
    record = _native_call(lambda: bindings.demo._load_weekly_record_for_api(run_id))
    publication = next(
        (item for item in record.publications if item.publication_id == publication_id),
        None,
    )
    if publication is None:
        raise ToolError(
            "PUBLICATION_NOT_FOUND",
            "RosterCopiilot did not persist the requested publication.",
            native_code="PUBLICATION_NOT_FOUND",
            details={"run_id": run_id, "publication_id": publication_id},
        )
    return publication


def _publication_id(value: Any) -> str:
    if not isinstance(value, dict):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "RosterCopiilot omitted its publication record.",
        )
    publication_id = value.get("publication_id")
    if not isinstance(publication_id, str) or not publication_id:
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "RosterCopiilot returned an invalid publication ID.",
        )
    return publication_id


def _delivery_copy(native_path: Path, filename: str) -> Path:
    delivery_dir = native_path.parent / ".ngopilot-delivery" / uuid4().hex
    delivery_dir.mkdir(parents=True, exist_ok=False)
    target = delivery_dir / filename
    shutil.copy2(native_path, target)
    return target.resolve(strict=True)


def _envelope(
    bindings: SimpleNamespace,
    result: dict[str, Any],
    *,
    native_status: str | None = None,
) -> dict[str, Any]:
    if not isinstance(result, dict):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "RosterCopiilot returned a non-object result.",
        )
    run_id = result.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "RosterCopiilot omitted run_id from its result.",
        )
    record = _native_call(lambda: bindings.demo._load_weekly_record_for_api(run_id))
    version = result.get("version")
    reconciliation = result.get("reconciliation")
    if not isinstance(version, dict) or not isinstance(reconciliation, dict):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "RosterCopiilot omitted current version or reconciliation data.",
        )
    version_id = version.get("id")
    content_hash = reconciliation.get("content_hash")
    if not isinstance(version_id, str) or not isinstance(content_hash, str):
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "RosterCopiilot returned invalid current version identity.",
        )
    template_path = Path(bindings.demo.DEFAULT_DIVISION_TEMPLATE).resolve(strict=True)
    refs = {
        "run_id": run_id,
        "current_version_id": version_id,
        "content_hash": content_hash,
        "master_data_version": record.master_data_version,
        "division_template": {
            "path": str(template_path),
            "sha256": _sha256(template_path),
        },
        "dependency_version": DEPENDENCY_VERSION,
        "publication_ids": [item.publication_id for item in record.publications],
    }
    effective_status = native_status or (
        "published"
        if result.get("publication") is not None
        else result.get("publication_state")
    )
    if effective_status not in {"blocked", "draft", "ready", "published"}:
        raise ToolError(
            "NATIVE_PROTOCOL_ERROR",
            "RosterCopiilot returned an invalid publication state.",
            details={"publication_state": effective_status},
        )
    parse_summary = result.get("parse_summary")
    warnings = (
        list(parse_summary.get("warnings", []))
        if isinstance(parse_summary, dict)
        and isinstance(parse_summary.get("warnings", []), list)
        else []
    )
    return {
        "native_status": effective_status,
        "native_refs": refs,
        "result": result,
        "warnings": warnings,
    }


def _native_call(function: Callable[[], Any]) -> Any:
    try:
        return function()
    except ToolError:
        raise
    except Exception as exc:
        detail = getattr(exc, "detail", None)
        if isinstance(detail, dict):
            code = str(detail.get("code") or "NATIVE_OPERATION_FAILED")
            message = str(detail.get("message") or exc)
            raise ToolError(
                code,
                message,
                native_code=code,
                native_message=message,
                details={
                    key: value
                    for key, value in detail.items()
                    if key not in {"code", "message"}
                },
            ) from exc
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def handle(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    handlers = {
        "start": _start,
        "status": _status,
        "review": _review,
        "revalidate": _revalidate,
        "export": _export,
        "publish": _publish,
        "get_published": _get_published,
    }
    try:
        handler = handlers[operation]
    except KeyError as exc:
        raise ValueError(f"unsupported roster operation: {operation}") from exc
    bindings = _bindings()
    try:
        return handler(bindings, payload)
    except ToolError:
        raise
    except Exception as exc:
        # Route handlers translate native domain failures into HTTPException.
        # Defensive direct-call failures retain a useful native type code.
        raise ToolError(
            getattr(exc, "code", type(exc).__name__),
            str(exc) or type(exc).__name__,
            native_code=getattr(exc, "code", type(exc).__name__),
            native_message=str(exc),
            details=getattr(exc, "details", {}),
        ) from exc
