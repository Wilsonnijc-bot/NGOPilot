"""模板管理 API — 上傳 / 查詢 / 重設 / 修改映射。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..services import template_store
from ..services.excel_export import HEADER_LABELS

router = APIRouter(prefix="/api/templates", tags=["templates"])


class MappingPayload(BaseModel):
    mapping: dict[str, str]


@router.get("")
def get_active():
    info = template_store.get_active()
    return {
        **info.__dict__,
        "schema_keys": list(HEADER_LABELS.keys()),
        "schema_labels": HEADER_LABELS,
    }


@router.post("/upload")
async def upload(
    file: UploadFile = File(...),
    kind: Optional[str] = Form(None),
):
    content = await file.read()
    if not content:
        raise HTTPException(400, "空檔案")
    name = file.filename or "template"
    lower = name.lower()
    try:
        if lower.endswith(".xlsx") or lower.endswith(".xls"):
            info = template_store.upload_excel_template(content, name)
        elif any(lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")):
            info = template_store.upload_image_template(content, name)
        else:
            raise HTTPException(400, "只支援 .xlsx / .xls 或圖片格式")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return info.__dict__


@router.post("/mapping")
def update_mapping(payload: MappingPayload):
    info = template_store.update_mapping(payload.mapping)
    return info.__dict__


@router.post("/reset")
def reset():
    info = template_store.reset_to_builtin()
    return info.__dict__
