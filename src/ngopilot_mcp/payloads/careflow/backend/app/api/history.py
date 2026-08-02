"""歷史記錄 API — 列表 / 詳情 / 篩選 / 批量導出 / 修正 diff。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, and_, or_, select

from ..config import settings
from ..db import get_session
from ..models import FieldCorrection, VolunteerBatch, VolunteerRecord
from ..services import excel_export, volunteer_form

router = APIRouter(prefix="/api/history", tags=["history"])


class ExportCombinedPayload(BaseModel):
    batch_ids: list[int]
    title: Optional[str] = "合併匯出"


@router.get("/batches")
def list_batches(
    q: Optional[str] = Query(None, description="關鍵詞：批次標題 / 志工隊 / 備註"),
    status: Optional[str] = None,
    volunteer_team: Optional[str] = None,
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    stmt = select(VolunteerBatch)
    filters = []
    if q:
        like = f"%{q}%"
        filters.append(or_(
            VolunteerBatch.title.like(like),
            VolunteerBatch.volunteer_team.like(like),
            VolunteerBatch.note.like(like),
        ))
    if status:
        filters.append(VolunteerBatch.status == status)
    if volunteer_team:
        filters.append(VolunteerBatch.volunteer_team == volunteer_team)
    if date_from:
        filters.append(VolunteerBatch.visit_date >= date_from)
    if date_to:
        filters.append(VolunteerBatch.visit_date <= date_to)
    if filters:
        stmt = stmt.where(and_(*filters))
    stmt = stmt.order_by(VolunteerBatch.created_at.desc()).offset(offset).limit(limit)

    batches = session.exec(stmt).all()
    return {
        "total": len(batches),
        "batches": [b.model_dump() for b in batches],
    }


@router.get("/batches/{batch_id}/detail")
def batch_detail(batch_id: int, session: Session = Depends(get_session)):
    batch = session.get(VolunteerBatch, batch_id)
    if not batch:
        raise HTTPException(404, "batch not found")
    records = session.exec(
        select(VolunteerRecord).where(VolunteerRecord.batch_id == batch_id).order_by(VolunteerRecord.id)
    ).all()
    diff = volunteer_form.compute_diff_stats(session, batch_id)

    from ..llm.vision import assess_completeness

    rec_dicts = []
    for r in records:
        rd = r.model_dump()
        rd["photo_url"] = f"/api/files/{r.photo_path}"
        # 信息完整性 + 自動補全標記
        ai_ext = r.ai_extracted or {}
        auto_keys = ai_ext.get("__auto_filled_keys__") or []
        clean = {k: v for k, v in ai_ext.items() if not k.startswith("__")}
        comp = assess_completeness(clean, r.ai_confidence)
        rd["ai_extracted"] = clean
        if r.final_fields:
            rd["final_fields"] = {k: v for k, v in r.final_fields.items() if not k.startswith("__")}
        rd["is_complete"] = comp["is_complete"]
        rd["missing_fields"] = comp["missing_fields"]
        rd["low_confidence_fields"] = comp["low_confidence_fields"]
        rd["partial_fields"] = comp.get("partial_fields") or {}
        rd["auto_filled_keys"] = list(auto_keys)
        rd["suggestions"] = ai_ext.get("__suggestions__") or {}
        rd["suggestion_confidence"] = ai_ext.get("__suggestion_confidence__") or {}
        rd["reviewed_keys"] = list(ai_ext.get("__reviewed_keys__") or [])
        rd["reviewed_reasons"] = ai_ext.get("__reviewed_reasons__") or {}
        rd["reviewed_confidence"] = ai_ext.get("__reviewed_confidence__") or {}
        rd["qwen_original"] = ai_ext.get("__qwen_original__") or {}
        rec_dicts.append(rd)

    return {
        "batch": batch.model_dump(),
        "records": rec_dicts,
        "diff_stats": diff,
    }


@router.get("/corrections/by-field")
def corrections_by_field(session: Session = Depends(get_session)):
    """所有歷史批次 aggregated diff，用於 prompt 改進線索。"""
    corr = session.exec(select(FieldCorrection)).all()
    by_field: dict[str, dict] = {}
    for c in corr:
        f = by_field.setdefault(c.field_name, {"count": 0, "low_conf_count": 0, "samples": []})
        f["count"] += 1
        if (c.ai_confidence or 0.0) < 0.7:
            f["low_conf_count"] += 1
        if len(f["samples"]) < 5:
            f["samples"].append({
                "ai": c.ai_value,
                "final": c.final_value,
                "conf": c.ai_confidence,
            })
    return {"total": len(corr), "by_field": by_field}


@router.post("/export-combined")
def export_combined(
    payload: "ExportCombinedPayload",
    session: Session = Depends(get_session),
):
    """將多個批次內已審查的紀錄合併為一個 Excel。"""
    batch_ids = payload.batch_ids
    title = payload.title or "合併匯出"
    if not batch_ids:
        raise HTTPException(400, "至少需要一個 batch_id")

    rows: list[dict] = []
    teams: set[str] = set()
    for bid in batch_ids:
        batch = session.get(VolunteerBatch, bid)
        if not batch:
            continue
        if batch.volunteer_team:
            teams.add(batch.volunteer_team)
        records = session.exec(
            select(VolunteerRecord).where(
                VolunteerRecord.batch_id == bid,
                VolunteerRecord.is_reviewed == True,  # noqa: E712
            ).order_by(VolunteerRecord.id)
        ).all()
        for r in records:
            rows.append({
                "final_fields": {**(r.final_fields or {}), "batch_title": batch.title},
                "reviewer": r.reviewer,
                "reviewed_at": r.reviewed_at.strftime("%Y-%m-%d %H:%M") if r.reviewed_at else None,
            })

    if not rows:
        raise HTTPException(400, "所選批次中沒有任何已審查的紀錄")

    out_path = settings.data_path / "exports" / f"combined_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    excel_export.export_batch(
        batch_title=title,
        volunteer_team=", ".join(teams) if teams else None,
        rows=rows,
        out_path=out_path,
    )

    rel = str(out_path.relative_to(settings.data_path))
    return {
        "exported_file": rel,
        "download_url": f"/api/files/{rel}",
        "row_count": len(rows),
        "batch_ids": batch_ids,
    }
