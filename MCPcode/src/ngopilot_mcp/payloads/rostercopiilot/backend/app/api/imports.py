"""Workbook import endpoints.

These routes are support/demo tooling for reverse-engineering fixtures and
source evidence. The scheduler-first product path should consume a normalized
``SchedulerSnapshot`` instead of making ``/api/import/workbooks`` the primary
weekly workflow.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from ..importer.errors import ImporterError
from ..importer import (
    parse_division_workbook,
    parse_escort_workbook,
    parse_hc_timetable_workbook,
    parse_skills_sheet,
    parse_transfer_log,
    resolve_import_batch,
)
from ..importer.promotion import build_canonical_preview
from ..importer.serialization import to_jsonable
from ..importer.workbook_utils import load_workbook, require_sheet
from ..services.state import get_state

router = APIRouter(prefix="/api/import", tags=["import"])

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = REPO_ROOT / "docs"
DEFAULT_DIVISION = DOCS_DIR / "照顧員工作分工表2026(HKU).xlsx"
DEFAULT_HC = DOCS_DIR / "2026_HC 時間表(HKU).xlsx"
DEFAULT_ESCORT = DOCS_DIR / "護送個案總表(2026)(HKU).xlsx"
ALLOWED_WORKBOOK_SUFFIXES = {".xlsx", ".xlsm"}


class AmbiguityResolutionRequest(BaseModel):
    status: Literal["resolved", "rejected", "ignored"] = "resolved"
    resolution: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class AliasResolutionRequest(BaseModel):
    entity_type: Literal["worker", "elder"]
    alias: str = Field(min_length=1)
    canonical_id: str = Field(min_length=1)
    canonical_name: str | None = None
    confidence: str = "manual"
    note: str | None = None


async def _save_upload(upload: UploadFile | None, path: Path) -> Path | None:
    if upload is None:
        return None
    suffix = Path(upload.filename or path.name).suffix or ".xlsx"
    if suffix.lower() not in ALLOWED_WORKBOOK_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNSUPPORTED_WORKBOOK_TYPE",
                "message": f"unsupported workbook extension: {suffix}",
                "allowed_extensions": sorted(ALLOWED_WORKBOOK_SUFFIXES),
            },
        )
    target = path.with_suffix(suffix)
    data = await upload.read()
    if not data:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EMPTY_UPLOAD",
                "message": f"empty upload: {upload.filename}",
            },
        )
    target.write_bytes(data)
    return target


def _source_display(kind: str, path: Path, upload: UploadFile | None) -> str:
    if upload is not None and upload.filename:
        return f"{kind}:upload:{upload.filename}"
    try:
        return f"{kind}:{path.resolve().relative_to(REPO_ROOT.resolve())}"
    except ValueError:
        return f"{kind}:{path.name}"


def _importer_error_detail(exc: ImporterError) -> dict[str, Any]:
    return {
        "code": exc.__class__.__name__,
        "message": str(exc),
        "source": to_jsonable(getattr(exc, "source", None)),
    }


def _summary_from_import_result(result) -> dict[str, Any]:
    summary = result.summary
    return {
        "parser_name": summary.parser_name,
        "status": summary.status,
        "parsed_count": summary.parsed_count,
        "inferred_count": summary.inferred_count,
        "flagged_count": summary.flagged_count,
        "silently_dropped_cells": summary.silently_dropped_cells,
        "notes": list(summary.notes),
    }


def _division_summary(result) -> dict[str, Any]:
    summary = dict(result.summary)
    return {
        "parser_name": "division.regular_services",
        "status": summary.get("status", "ok"),
        "parsed_count": summary.get("fixed_service_candidate_count", 0),
        "inferred_count": summary.get("assignment_count", 0),
        "flagged_count": summary.get("ambiguity_count", len(result.ambiguities)),
        "silently_dropped_cells": summary.get("silently_dropped_cells", 0),
        "notes": [
            f"workers={summary.get('worker_count')}",
            f"counter_mismatches={summary.get('counter_mismatch_count')}",
        ],
    }


def _collect_ambiguities(parser_name: str, result) -> list[dict[str, Any]]:
    out = []
    for ambiguity in result.ambiguities:
        row = to_jsonable(ambiguity)
        row["parser_name"] = parser_name
        out.append(row)
    return out


@router.post("/workbooks")
async def import_workbooks(
    division_workbook: UploadFile | None = File(default=None),
    hc_workbook: UploadFile | None = File(default=None),
    escort_workbook: UploadFile | None = File(default=None),
    use_default_docs: bool = Query(
        default=False,
        description="Import the three real workbook samples from docs/",
    ),
) -> dict[str, Any]:
    with TemporaryDirectory(prefix="rostercopiilot_import_") as tmp:
        tmpdir = Path(tmp)
        division_path = await _save_upload(division_workbook, tmpdir / "division.xlsx")
        hc_path = await _save_upload(hc_workbook, tmpdir / "hc.xlsx")
        escort_path = await _save_upload(escort_workbook, tmpdir / "escort.xlsx")

        if use_default_docs:
            division_path = division_path or DEFAULT_DIVISION
            hc_path = hc_path or DEFAULT_HC
            escort_path = escort_path or DEFAULT_ESCORT

        if not any((division_path, hc_path, escort_path)):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "WORKBOOK_REQUIRED",
                    "message": (
                        "upload at least one workbook or pass "
                        "use_default_docs=true"
                    ),
                },
            )
        if division_path is None:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "DIVISION_WORKBOOK_REQUIRED",
                    "message": "division workbook is required",
                },
            )

        try:
            division = parse_division_workbook(division_path)
            division_wb = load_workbook(division_path)
            skills = parse_skills_sheet(
                require_sheet(division_wb, "新同工跟服務紀錄表"),
                workbook_path=division_path,
            )
            transfers = parse_transfer_log(
                require_sheet(division_wb, "個案轉移紀錄_2025"),
                workbook_path=division_path,
            )
            hc = parse_hc_timetable_workbook(hc_path) if hc_path else None
            escort = parse_escort_workbook(escort_path) if escort_path else None
        except ImporterError as exc:
            raise HTTPException(
                status_code=422,
                detail=_importer_error_detail(exc),
            ) from exc

        resolution_inputs = [skills, transfers]
        if hc is not None:
            resolution_inputs.append(hc)
        if escort is not None:
            resolution_inputs.append(escort)
        resolution = resolve_import_batch(*resolution_inputs)

        empty_result = None
        if hc is None or escort is None:
            from ..importer.base import ImportResult
            empty_result = ImportResult.empty(parser_name="missing")
        hc_result = hc or empty_result
        escort_result = escort or empty_result
        assert hc_result is not None and escort_result is not None

        parser_stats = {
            "division": _division_summary(division),
            "skills": _summary_from_import_result(skills),
            "transfers": _summary_from_import_result(transfers),
            "hc": _summary_from_import_result(hc_result),
            "escort": _summary_from_import_result(escort_result),
            "entity_resolution": _summary_from_import_result(resolution),
        }
        silent_drops = sum(s["silently_dropped_cells"] for s in parser_stats.values())
        summary = {
            "status": "ok" if silent_drops == 0 else "partial",
            "parsed_count": sum(s["parsed_count"] for s in parser_stats.values()),
            "inferred_count": sum(s["inferred_count"] for s in parser_stats.values()),
            "flagged_count": sum(s["flagged_count"] for s in parser_stats.values()),
            "silently_dropped_cells": silent_drops,
            "parser_stats": parser_stats,
        }

        canonical_preview = build_canonical_preview(
            division=division,
            skills=skills,
            transfers=transfers,
            hc=hc_result,
            escort=escort_result,
            resolution=resolution,
        )
        payload = {
            "division": division.to_json_dict(),
            "skills": to_jsonable(skills),
            "transfers": to_jsonable(transfers),
            "hc": to_jsonable(hc_result),
            "escort": to_jsonable(escort_result),
            "entity_resolution": to_jsonable(resolution),
            "canonical_preview": canonical_preview,
        }
        ambiguities = []
        ambiguities.extend(_collect_ambiguities("division", division))
        ambiguities.extend(_collect_ambiguities("skills", skills))
        ambiguities.extend(_collect_ambiguities("transfers", transfers))
        ambiguities.extend(_collect_ambiguities("hc", hc_result))
        ambiguities.extend(_collect_ambiguities("escort", escort_result))
        ambiguities.extend(_collect_ambiguities("entity_resolution", resolution))

        source_names = []
        for kind, path, upload in (
            ("division", division_path, division_workbook),
            ("hc", hc_path, hc_workbook),
            ("escort", escort_path, escort_workbook),
        ):
            if path is not None:
                source_names.append(_source_display(kind, path, upload))
        store = get_state().store
        if store is None:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "STORE_DISABLED",
                    "message": "persistent store is disabled",
                },
            )
        batch = store.create_import_batch(
            summary=summary,
            payload=payload,
            source_names=source_names,
            ambiguities=ambiguities,
        )
        return {
            **batch,
            "summary": summary,
            "canonical_preview": {
                "employees": canonical_preview["employees"],
                "fixed_services": {
                    "count": canonical_preview["fixed_services"]["count"],
                    "source_of_truth": "division",
                    "hc_enrichment_count": canonical_preview["fixed_services"]["hc_enrichment_count"],
                },
                "escort_requests": {
                    "count": canonical_preview["escort_requests"]["count"],
                    "source_of_truth": "escort_workbook",
                },
            },
        }


@router.get("/batches")
def list_batches() -> list[dict[str, Any]]:
    store = get_state().store
    return [] if store is None else store.list_import_batches()


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str) -> dict[str, Any]:
    store = get_state().store
    batch = None if store is None else store.get_import_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="import batch not found")
    return batch


@router.get("/ambiguities")
def list_ambiguities(
    status: str | None = "pending",
    batch_id: str | None = None,
) -> list[dict[str, Any]]:
    store = get_state().store
    return [] if store is None else store.list_import_ambiguities(
        status=status, batch_id=batch_id)


@router.post("/ambiguities/{ambiguity_id}/resolution")
def resolve_ambiguity(
    ambiguity_id: str,
    req: AmbiguityResolutionRequest,
) -> dict[str, Any]:
    store = get_state().store
    if store is None:
        raise HTTPException(status_code=500, detail="persistent store is disabled")
    resolution = dict(req.resolution)
    if req.note:
        resolution["note"] = req.note
    row = store.resolve_import_ambiguity(
        ambiguity_id, status=req.status, resolution=resolution)
    if row is None:
        raise HTTPException(status_code=404, detail="ambiguity not found")
    return row


@router.post("/resolutions")
def save_alias_resolution(req: AliasResolutionRequest) -> dict[str, Any]:
    store = get_state().store
    if store is None:
        raise HTTPException(status_code=500, detail="persistent store is disabled")
    return store.save_alias_resolution(
        entity_type=req.entity_type,
        alias=req.alias,
        canonical_id=req.canonical_id,
        canonical_name=req.canonical_name,
        confidence=req.confidence,
        payload={"note": req.note} if req.note else {},
    )
