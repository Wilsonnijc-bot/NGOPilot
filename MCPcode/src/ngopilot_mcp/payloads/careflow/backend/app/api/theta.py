"""功能 θ API — 自訂 PDF 表單模板上傳 / 分析 / 審查 / 儲存。"""
from __future__ import annotations

import logging
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import settings
from ..db import get_session
from ..models import ThetaTemplate, ThetaTemplateStatus, ThetaField
from ..services import theta_extractor, theta_publish

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/theta", tags=["theta"])


class FieldDef(BaseModel):
    key: str
    label: str
    type: str = "text"
    bbox: list[float] = [0.0, 0.0, 0.0, 0.0]
    confidence: float = 0.0
    page_number: int = 0


class UpdateTemplatePayload(BaseModel):
    name: str | None = None
    fields: list[FieldDef] | None = None


# ── 上傳 + 分析 ──────────────────────────────────────────────────────────
@router.post("/upload", status_code=201)
async def upload(
    name: str = Form(...),
    note: str | None = Form(None),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """上傳 PDF 表單並啟動 GPT-5-mini 分析。同步回傳分析結果（含欄位 + bbox）。"""
    content = await file.read()
    if not content:
        raise HTTPException(400, "空檔案")
    filename = file.filename or "form.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(400, "只接受 PDF 檔案")

    # 儲存 PDF
    pdf_dir = settings.data_path / "theta_pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex}_{Path(filename).name}"
    pdf_path = pdf_dir / safe_name
    pdf_path.write_bytes(content)

    # 建立 template stub
    tmpl = ThetaTemplate(
        name=name,
        original_pdf_path=str(pdf_path.relative_to(settings.data_path)),
        original_pdf_filename=filename,
        note=note,
        status=ThetaTemplateStatus.ANALYZING,
    )
    session.add(tmpl)
    session.commit()
    session.refresh(tmpl)

    # 跑 GPT-5-mini 分析
    result = theta_extractor.extract_form_blanks(pdf_path)
    meta = result.get("_meta", {})
    total_fields = 0

    for page_data in result.get("pages", []):
        page_idx = page_data["page"]
        for f in page_data.get("fields", []):
            tf = ThetaField(
                template_id=tmpl.id,  # type: ignore[arg-type]
                page_number=page_idx,
                field_key=f["key"],
                field_label=f["label"],
                field_type=f.get("type", "text"),
                bbox=f.get("bbox", [0, 0, 0, 0]),
                bbox_llm=f.get("_bbox_llm"),  # rc6.8：保留微調前原始 LLM bbox
                confidence=f.get("confidence", 0.0),
            )
            session.add(tf)
            total_fields += 1

    # 更新 template meta
    tmpl.page_count = len(result.get("pages", []))
    tmpl.status = ThetaTemplateStatus.PENDING_REVIEW
    tmpl.updated_at = datetime.utcnow()
    session.add(tmpl)
    session.commit()

    # 收集頁面錯誤診斷
    page_errors: list[dict] = []
    for page_data in result.get("pages", []):
        if page_data.get("_error"):
            page_errors.append({
                "page": page_data["page"],
                "error": page_data["_error"],
            })

    return {
        "template": _template_out(tmpl),
        "fields": [_field_out(f) for f in _get_fields(session, tmpl.id)],  # type: ignore[arg-type]
        "analysis_meta": {
            "provider": meta.get("provider"),
            "model": meta.get("model"),
            "latency_ms": meta.get("latency_ms"),
            "total_pages": meta.get("total_pages"),
            "total_fields": total_fields,
            "is_mock": meta.get("provider") == "mock",
            "last_error": meta.get("last_error"),
            "page_errors": page_errors,
        },
    }


# ── 模板 CRUD ────────────────────────────────────────────────────────────
@router.get("/templates")
def list_templates(session: Session = Depends(get_session)):
    rows = session.exec(
        select(ThetaTemplate).order_by(ThetaTemplate.created_at.desc())
    ).all()
    return {
        "templates": [
            {
                **_template_out(t),
                "field_count": len(_get_fields(session, t.id)),  # type: ignore[arg-type]
            }
            for t in rows
        ]
    }


@router.get("/templates/{template_id}")
def get_template(template_id: int, session: Session = Depends(get_session)):
    tmpl = session.get(ThetaTemplate, template_id)
    if not tmpl:
        raise HTTPException(404, "template not found")
    fields = _get_fields(session, template_id)
    return {
        "template": _template_out(tmpl),
        "fields": [_field_out(f) for f in fields],
        "page_count": tmpl.page_count,
    }


@router.put("/templates/{template_id}")
def update_template(
    template_id: int,
    payload: UpdateTemplatePayload,
    session: Session = Depends(get_session),
):
    """儲存審查後的欄位定義（使用者調整過 bbox / 新增 / 刪除欄位）。"""
    tmpl = session.get(ThetaTemplate, template_id)
    if not tmpl:
        raise HTTPException(404, "template not found")

    if payload.name is not None:
        tmpl.name = payload.name

    if payload.fields is not None:
        # 刪除舊欄位，寫入新欄位 — 整段必須原子完成，否則一個 constraint
        # violation 會把 template 留在「半邊欄位」狀態。
        try:
            old_fields = _get_fields(session, template_id)
            for f in old_fields:
                session.delete(f)
            for fd in payload.fields:
                tf = ThetaField(
                    template_id=template_id,
                    page_number=fd.page_number,
                    field_key=fd.key,
                    field_label=fd.label,
                    field_type=fd.type,
                    bbox=fd.bbox,
                    confidence=fd.confidence,
                )
                session.add(tf)

            tmpl.status = ThetaTemplateStatus.CONFIRMED
            tmpl.updated_at = datetime.utcnow()
            session.add(tmpl)
            session.commit()
        except Exception:
            session.rollback()
            raise
    else:
        tmpl.status = ThetaTemplateStatus.CONFIRMED
        tmpl.updated_at = datetime.utcnow()
        session.add(tmpl)
        session.commit()

    session.refresh(tmpl)

    # rc6.7：審視通過後自動發佈為 γ（welfare-form）可選的 template
    confirmed_fields = _get_fields(session, template_id)
    publish_info: dict = {"published": False}
    try:
        path = theta_publish.publish_theta_template(tmpl, confirmed_fields)
        publish_info = {
            "published": True,
            "gamma_template_id": f"theta_{tmpl.id}",
            "path": str(path.relative_to(settings.data_path)),
            "field_count": len(confirmed_fields),
        }
    except Exception as e:  # noqa: BLE001
        publish_info = {"published": False, "error": str(e)[:200]}

    return {
        "template": _template_out(tmpl),
        "fields": [_field_out(f) for f in confirmed_fields],
        "gamma_publish": publish_info,
    }


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, session: Session = Depends(get_session)):
    tmpl = session.get(ThetaTemplate, template_id)
    if not tmpl:
        raise HTTPException(404, "template not found")

    # 刪除欄位
    for f in _get_fields(session, template_id):
        session.delete(f)

    # 刪除 PDF 檔案
    pdf_full = settings.data_path / tmpl.original_pdf_path
    try:
        pdf_full.unlink(missing_ok=True)
    except OSError:
        logger.warning("theta unlink failed for %s", pdf_full, exc_info=True)

    # rc6.7：同時移除已發佈到 γ 套組列表的 JSON
    try:
        theta_publish.unpublish_theta_template(template_id)
    except Exception:  # noqa: BLE001
        logger.warning("theta unpublish_theta_template failed for template %s", template_id, exc_info=True)

    session.delete(tmpl)
    session.commit()
    return {"deleted": True, "template_id": template_id}


# ── 頁面圖片（供前端 audit 顯示用） ───────────────────────────────────────
@router.get("/templates/{template_id}/page/{page_index}/image")
def serve_page_image(template_id: int, page_index: int, session: Session = Depends(get_session)):
    """渲染 PDF 單頁為 JPEG，供前端 audit 介面顯示。"""
    tmpl = session.get(ThetaTemplate, template_id)
    if not tmpl:
        raise HTTPException(404, "template not found")
    if page_index < 0 or page_index >= tmpl.page_count:
        raise HTTPException(404, f"page {page_index} out of range (0..{tmpl.page_count - 1})")

    pdf_full = settings.data_path / tmpl.original_pdf_path
    if not pdf_full.exists():
        raise HTTPException(404, "PDF file not found on disk")

    try:
        jpeg_bytes = theta_extractor.render_page_image(pdf_full, page_index)
    except Exception:
        logger.exception("theta render_page_image failed (template_id=%s, page=%s)", tmpl.id, page_index)
        raise HTTPException(500, "internal error")

    return Response(content=jpeg_bytes, media_type="image/jpeg")


# ── helpers ───────────────────────────────────────────────────────────────
def _get_fields(session: Session, template_id: int) -> list[ThetaField]:
    return list(
        session.exec(
            select(ThetaField)
            .where(ThetaField.template_id == template_id)
            .order_by(ThetaField.page_number, ThetaField.id)
        ).all()
    )


def _template_out(t: ThetaTemplate) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "original_pdf_filename": t.original_pdf_filename,
        "page_count": t.page_count,
        "status": t.status.value if hasattr(t.status, "value") else str(t.status),
        "note": t.note,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _field_out(f: ThetaField) -> dict:
    return {
        "id": f.id,
        "page_number": f.page_number,
        "key": f.field_key,
        "label": f.field_label,
        "type": f.field_type,
        "bbox": f.bbox,
        "bbox_llm": f.bbox_llm,  # rc6.8：audit 雙框模式用
        "refined": bool(f.bbox_llm) and f.bbox_llm != f.bbox,
        "confidence": f.confidence,
    }
