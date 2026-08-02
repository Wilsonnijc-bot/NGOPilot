"""志工探訪表 — 上傳 / 抽取 / 審查 / 提交 API。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import settings
from ..db import get_session
from ..llm.vision import VOLUNTEER_FORM_FIELDS, REQUIRED_KEYS, assess_completeness
from ..models import BatchStatus, VolunteerBatch, VolunteerRecord
from ..services import excel_export, volunteer_form

router = APIRouter(prefix="/api/volunteer", tags=["volunteer"])


# ── Schemas ────────────────────────────────────────────────────────────────
class ReviewPayload(BaseModel):
    final_fields: dict
    reviewer: Optional[str] = None


class BatchOut(BaseModel):
    id: int
    title: str
    volunteer_team: Optional[str]
    visit_date: Optional[str]
    note: Optional[str]
    status: str
    total_photos: int
    confirmed_count: int
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime]
    exported_at: Optional[datetime]
    exported_file: Optional[str]


class RecordOut(BaseModel):
    id: int
    batch_id: int
    photo_url: str
    original_filename: str
    ai_extracted: Optional[dict]
    ai_confidence: Optional[dict]
    ai_bbox: Optional[dict]
    ai_provider: Optional[str]
    ai_model: Optional[str]
    ai_latency_ms: Optional[int]
    ai_error: Optional[str]
    final_fields: Optional[dict]
    is_reviewed: bool
    reviewer: Optional[str]
    reviewed_at: Optional[datetime]
    # ── 資訊完整性 (動態計算、不存表) ────────────────────────────────────────────
    is_complete: bool = True
    missing_fields: list[str] = []
    low_confidence_fields: list[str] = []
    partial_fields: dict[str, list[list[int]]] = {}
    auto_filled_keys: list[str] = []
    # AI 建議補全（永遠帶；前端可一鍵採用）
    suggestions: dict = {}
    suggestion_confidence: dict = {}
    # v0.3.4：DeepSeek 二次審查（預設套用，可一鍵撤回）
    reviewed_keys: list[str] = []
    reviewed_reasons: dict[str, str] = {}
    reviewed_confidence: dict[str, float] = {}
    qwen_original: dict = {}
    # v0.3.6：Qwen 連續回空 / 抽取完全失敗 → 需人工輸入
    needs_human_input: bool = False


def _strip_meta(d: Optional[dict]) -> Optional[dict]:
    if not d:
        return d
    return {k: v for k, v in d.items() if not k.startswith("__")}


def _record_to_out(r: VolunteerRecord) -> RecordOut:
    ai_ext = r.ai_extracted or {}
    auto_keys: list[str] = ai_ext.get("__auto_filled_keys__") or []
    suggestions: dict = ai_ext.get("__suggestions__") or {}
    sugg_conf: dict = ai_ext.get("__suggestion_confidence__") or {}
    reviewed_keys: list[str] = ai_ext.get("__reviewed_keys__") or []
    reviewed_reasons: dict = ai_ext.get("__reviewed_reasons__") or {}
    reviewed_conf: dict = ai_ext.get("__reviewed_confidence__") or {}
    qwen_original: dict = ai_ext.get("__qwen_original__") or {}
    comp = assess_completeness(_strip_meta(ai_ext), r.ai_confidence)
    return RecordOut(
        id=r.id,  # type: ignore[arg-type]
        batch_id=r.batch_id,
        photo_url=f"/api/files/{r.photo_path}",
        original_filename=r.original_filename,
        ai_extracted=_strip_meta(r.ai_extracted),
        ai_confidence=r.ai_confidence,
        ai_bbox=r.ai_bbox,
        ai_provider=r.ai_provider,
        ai_model=r.ai_model,
        ai_latency_ms=r.ai_latency_ms,
        ai_error=r.ai_error,
        final_fields=_strip_meta(r.final_fields),
        is_reviewed=r.is_reviewed,
        reviewer=r.reviewer,
        reviewed_at=r.reviewed_at,
        is_complete=comp["is_complete"],
        missing_fields=comp["missing_fields"],
        low_confidence_fields=comp["low_confidence_fields"],
        partial_fields=comp.get("partial_fields") or {},
        auto_filled_keys=list(auto_keys),
        suggestions=suggestions,
        suggestion_confidence=sugg_conf,
        reviewed_keys=list(reviewed_keys),
        reviewed_reasons=reviewed_reasons,
        reviewed_confidence=reviewed_conf,
        qwen_original=qwen_original,
        needs_human_input=bool(ai_ext.get("__needs_human_input__")),
    )


# ── Schema endpoint ────────────────────────────────────────────────────────
@router.get("/schema")
def get_schema():
    return {"fields": VOLUNTEER_FORM_FIELDS}


# ── 建立 batch + 上傳 ──────────────────────────────────────────────────────
@router.post("/batches", response_model=BatchOut, status_code=201)
def create_batch(
    title: str = Form(...),
    volunteer_team: Optional[str] = Form(None),
    visit_date: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    session: Session = Depends(get_session),
):
    batch = volunteer_form.create_batch(
        session,
        title=title,
        volunteer_team=volunteer_team,
        visit_date=visit_date,
        note=note,
    )
    return BatchOut(**batch.model_dump())


@router.post("/batches/{batch_id}/photos")
async def upload_photos(
    batch_id: int,
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
    auto_extract: bool = Form(True),
    auto_complete: bool = Form(False),
    session: Session = Depends(get_session),
):
    batch = session.get(VolunteerBatch, batch_id)
    if not batch:
        raise HTTPException(404, "batch not found")

    bytes_list = []
    for f in files:
        content = await f.read()
        if not content:
            continue
        bytes_list.append((f.filename or "unnamed.jpg", content))
    records = volunteer_form.add_photos(session, batch_id, bytes_list)

    if auto_extract:
        background.add_task(_run_extraction_task, batch_id, auto_complete)

    return {
        "batch_id": batch_id,
        "added": len(records),
        "auto_extract": auto_extract,
        "auto_complete": auto_complete,
        "records": [_record_to_out(r) for r in records],
    }


def _run_extraction_task(batch_id: int, auto_complete: bool = False):
    from ..db import engine
    from sqlmodel import Session as S
    with S(engine) as s:
        volunteer_form.run_extraction(s, batch_id, auto_complete=auto_complete)


@router.post("/batches/{batch_id}/extract")
def trigger_extraction(
    batch_id: int,
    background: BackgroundTasks,
    auto_complete: bool = False,
    session: Session = Depends(get_session),
):
    if not session.get(VolunteerBatch, batch_id):
        raise HTTPException(404, "batch not found")
    background.add_task(_run_extraction_task, batch_id, auto_complete)
    return {"status": "started", "auto_complete": auto_complete}


# ── 取批次 + 紀錄 ──────────────────────────────────────────────────────────
@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(batch_id: int, session: Session = Depends(get_session)):
    batch = session.get(VolunteerBatch, batch_id)
    if not batch:
        raise HTTPException(404, "batch not found")
    return BatchOut(**batch.model_dump())


@router.get("/batches/{batch_id}/records")
def list_records(batch_id: int, session: Session = Depends(get_session)):
    records = session.exec(
        select(VolunteerRecord).where(VolunteerRecord.batch_id == batch_id).order_by(VolunteerRecord.id)
    ).all()
    return {"records": [_record_to_out(r).model_dump() for r in records]}


# ── 人工審查 ───────────────────────────────────────────────────────────────
@router.post("/records/{record_id}/review", response_model=RecordOut)
def review_record(
    record_id: int,
    payload: ReviewPayload,
    session: Session = Depends(get_session),
):
    try:
        rec = volunteer_form.review_record(
            session,
            record_id,
            final_fields=payload.final_fields,
            reviewer=payload.reviewer,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return _record_to_out(rec)


# ── AI 自動補全（單筆） ────────────────────────────────────────────────────
@router.post("/records/{record_id}/auto-complete", response_model=RecordOut)
def auto_complete(record_id: int, session: Session = Depends(get_session)):
    try:
        rec = volunteer_form.auto_complete_record(session, record_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return _record_to_out(rec)


# ── DeepSeek 審查值撤回（單欄位） ──────────────────────────────────────────
@router.post("/records/{record_id}/revert/{field_key}", response_model=RecordOut)
def revert_field(record_id: int, field_key: str, session: Session = Depends(get_session)):
    """把某欄位從 DeepSeek 二次審查值還原為 Qwen 抽取原值。"""
    try:
        rec = volunteer_form.revert_reviewed_field(session, record_id, field_key)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return _record_to_out(rec)


# ── 刪除單張紀錄（v0.3.9） ─────────────────────────────────────────────────
@router.delete("/records/{record_id}")
def delete_record(record_id: int, session: Session = Depends(get_session)):
    """刪除一張紀錄 — 用於「這頁不是表，沒價值，跳過」。

    會：
    1. 從 DB 移除 record + 它的 FieldCorrection
    2. 嘗試刪 disk 上的照片
    3. 更新 batch.total_photos 與 confirmed_count
    """
    try:
        info = volunteer_form.delete_record(session, record_id)
    except ValueError as exc:
        msg = str(exc)
        if "不能刪除" in msg or "只剩" in msg:
            raise HTTPException(400, msg)
        raise HTTPException(404, msg)
    return info


# ── 匯出 Excel ─────────────────────────────────────────────────────────────
@router.post("/batches/{batch_id}/export")
def export_batch(batch_id: int, session: Session = Depends(get_session)):
    batch = session.get(VolunteerBatch, batch_id)
    if not batch:
        raise HTTPException(404, "batch not found")

    records = session.exec(
        select(VolunteerRecord).where(
            VolunteerRecord.batch_id == batch_id,
            VolunteerRecord.is_reviewed == True,  # noqa: E712
        ).order_by(VolunteerRecord.id)
    ).all()

    if not records:
        raise HTTPException(400, "本批次尚無已審查的紀錄，請先完成人工審查再匯出。")

    rows = [
        {
            "final_fields": r.final_fields or {},
            "reviewer": r.reviewer,
            "reviewed_at": r.reviewed_at.strftime("%Y-%m-%d %H:%M") if r.reviewed_at else None,
        }
        for r in records
    ]

    out_path = excel_export.make_export_path(batch_id)
    excel_export.export_batch(
        batch_title=batch.title,
        volunteer_team=batch.volunteer_team,
        rows=rows,
        out_path=out_path,
    )

    rel = str(out_path.relative_to(settings.data_path))
    batch.exported_file = rel
    batch.exported_at = datetime.utcnow()
    batch.status = BatchStatus.EXPORTED
    session.add(batch)
    session.commit()

    return {
        "batch_id": batch_id,
        "exported_file": rel,
        "download_url": f"/api/files/{rel}",
        "row_count": len(rows),
    }
