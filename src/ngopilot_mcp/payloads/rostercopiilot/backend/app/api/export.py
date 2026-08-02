"""Excel export endpoints."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..exporter import build_assignment_grid_workbook, save_ngo_division_workbook
from ..scheduler import representative_snapshot, run_scheduler
from ..services.excel_export import save_workbook
from ..services.state import get_state

router = APIRouter(prefix="/api/export", tags=["export"])

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DIVISION_TEMPLATE = REPO_ROOT / "docs" / "照顧員工作分工表2026(HKU).xlsx"
ALLOWED_TEMPLATE_SUFFIXES = {".xlsx", ".xlsm"}


class ExportRequest(BaseModel):
    version_id: str | None = None  # default: current version


class NgoFormatExportRequest(BaseModel):
    version_id: str | None = None
    template_path: str | None = None


def _resolve_template_path(raw: str | None) -> Path:
    if raw is None:
        return DEFAULT_DIVISION_TEMPLATE
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "TEMPLATE_WORKBOOK_NOT_FOUND",
                "message": "template workbook not found",
            },
        ) from exc
    if resolved.suffix.lower() not in ALLOWED_TEMPLATE_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "UNSUPPORTED_TEMPLATE_TYPE",
                "message": f"unsupported template extension: {resolved.suffix}",
                "allowed_extensions": sorted(ALLOWED_TEMPLATE_SUFFIXES),
            },
        )
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "TEMPLATE_OUTSIDE_REPO",
                "message": "template_path must point inside the RosterCopiilot repo",
            },
        ) from exc
    return resolved


@router.get("/current")
def export_current() -> FileResponse:
    state = get_state()
    path = save_workbook(state.dataset, state.current)
    return FileResponse(path, media_type=XLSX_MEDIA, filename=path.name)


@router.post("/excel")
def export_excel(req: ExportRequest) -> FileResponse:
    state = get_state()
    version = state.get_version(req.version_id) if req.version_id else state.current
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")
    path = save_workbook(state.dataset, version)
    return FileResponse(path, media_type=XLSX_MEDIA, filename=path.name)


@router.post("/ngo-format")
def export_ngo_format(req: NgoFormatExportRequest) -> FileResponse:
    state = get_state()
    version = state.get_version(req.version_id) if req.version_id else state.current
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")
    template_path = _resolve_template_path(req.template_path)
    path = save_ngo_division_workbook(
        template_path=template_path,
        dataset=state.dataset,
        version=version,
    )
    return FileResponse(path, media_type=XLSX_MEDIA, filename=path.name)


@router.post("/assignment-grid")
def export_assignment_grid() -> FileResponse:
    """Export the scheduler-first representative draft into a staff grid."""
    result = run_scheduler(representative_snapshot())
    wb = build_assignment_grid_workbook(result.version, workers=result.snapshot.workers)
    raw_dir = os.getenv("ROSTER_EXPORT_DIR")
    output_dir = Path(raw_dir) if raw_dir else REPO_ROOT / "data" / "exports"
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"assignment_grid_{result.version.id}.xlsx"
    wb.save(path)
    return FileResponse(path, media_type=XLSX_MEDIA, filename=path.name)
