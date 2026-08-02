"""功能 3 占位 API。功能 1 已由 `home_visit` 路由實作。"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from ..services import welfare_form
from ..services import welfare_form_filler
from ..services import welfare_form_mapping
from ..services import welfare_form_extractor
from ..services.welfare_form_templates import load_template

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["placeholder"])


@router.get("/welfare-form/status")
def welfare_form_status():
    return welfare_form.placeholder_status()


# ── v0.4.0-alpha：預設套組 ─────────────────────────────────────────────────
@router.get("/welfare-form/templates")
def list_welfare_templates():
    """列出所有福利表預設套組（含 ready / pending_coord_mapping 狀態）。"""
    return welfare_form.list_form_templates()


@router.get("/welfare-form/templates/{template_id}")
def get_welfare_template(template_id: str):
    """取得單一 template 完整定義 + mock elder profile。"""
    try:
        return welfare_form.get_form_template(template_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@router.get("/welfare-form/mock-elder")
def get_mock_elder():
    """取 mock 長者 profile（v0.4.0-alpha：寫死，下一版會接 elders 表）。"""
    return welfare_form.get_mock_elder_profile()


# ── v0.4.0-beta：PDF 實際回填 ──────────────────────────────────────────────
class FillRequest(BaseModel):
    template_id: str
    elder_profile: dict[str, Any] | None = None  # 為 None → 用 mock
    field_values: dict[str, str] | None = None  # 前端 review 後直接傳；優先於 elder_profile
    overrides: dict[str, str] | None = None     # 永遠覆寫前兩者


class PreviewMappingRequest(BaseModel):
    template_id: str
    elder_profile: dict[str, Any] | None = None
    use_llm: bool = False


@router.post("/welfare-form/preview-mapping")
def preview_welfare_mapping(req: PreviewMappingRequest):
    """先給前端看每欄會填什麼（直接 / default / LLM 推測 / 缺）。"""
    try:
        elder = req.elder_profile or welfare_form.get_mock_elder_profile()
        if not elder:
            raise HTTPException(400, "no elder_profile and mock not found")
        # 注入 today
        from datetime import date
        elder = dict(elder)
        if "today" not in elder:
            d = date.today()
            elder["today"] = {
                "iso": d.isoformat(),
                "year": str(d.year),
                "month": f"{d.month:02d}",
                "day": f"{d.day:02d}",
            }
        template = load_template(req.template_id)
        result = welfare_form_mapping.map_elder_to_template(template, elder, use_llm=req.use_llm)
        return {
            "template_id": req.template_id,
            "display_name": template.get("display_name"),
            "fill_strategy": template.get("fill_strategy"),
            **result,
            "elder_today": elder.get("today"),
        }
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/welfare-form/fill")
def fill_welfare_form(req: FillRequest):
    """產生填好的 PDF；回 stats + download_url。"""
    try:
        elder = req.elder_profile or welfare_form.get_mock_elder_profile()
        return welfare_form_filler.fill_form(
            req.template_id,
            elder_profile=elder,
            field_values=req.field_values,
            overrides=req.overrides,
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:  # noqa: BLE001
        logger.exception("welfare_form fill failed")
        raise HTTPException(500, "internal error")


# ── v0.4.0-rc2：raw text → ElderProfile → 立刻可填表 ───────────────────────
class ExtractProfileRequest(BaseModel):
    text: str
    source_hint: str | None = None  # e.g. "社工筆記" / "病人卡"


@router.post("/welfare-form/extract-profile")
def extract_profile(req: ExtractProfileRequest):
    """把一段散文／表格／病歷文字丟給 LLM，抽成 ElderProfile（跟 mock 同 schema）。
    回的 profile 可直接丟給 /preview-mapping 或 /fill。"""
    try:
        prof = welfare_form_extractor.extract_elder_profile_from_text(
            req.text, source_hint=req.source_hint
        )
        from ..config import settings
        return {"profile": prof, "mock_mode": bool(settings.is_mock_mode)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:  # noqa: BLE001
        logger.exception("welfare_form extract-profile (text) failed")
        raise HTTPException(500, "internal error")


# ── v0.4.0-rc3：照片 → vision LLM → ElderProfile ──────────────────────────
@router.post("/welfare-form/extract-profile-from-image")
async def extract_profile_from_image(
    image: UploadFile = File(..., description="病人卡 / 社工筆記 / 表格頁照片"),
    source_hint: str | None = Form(default=None),
):
    """上傳一張照片，後端壓縮 ≤800KB 後丟給 vision LLM 抽 ElderProfile。
    回的 profile 可直接丟給 /preview-mapping 或 /fill。"""
    try:
        raw = await image.read()
        if not raw:
            raise HTTPException(400, "image is empty")
        # 取得副檔名（fallback jpeg）
        ext = "jpeg"
        if image.filename:
            ext = (image.filename.rsplit(".", 1)[-1] or "jpeg").lower()
        prof = welfare_form_extractor.extract_elder_profile_from_image(
            raw, ext=ext, source_hint=source_hint
        )
        from ..config import settings
        return {
            "profile": prof,
            "mock_mode": bool(settings.is_mock_mode),
            "image_filename": image.filename,
            "image_bytes": len(raw),
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:  # noqa: BLE001
        logger.exception("welfare_form extract-profile (image) failed")
        raise HTTPException(500, "internal error")
