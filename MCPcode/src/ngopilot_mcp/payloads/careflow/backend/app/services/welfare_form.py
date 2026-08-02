"""功能 γ（政府福利表自動填寫） — v0.4.0-alpha：預設套組階段。

本檔提供：
1. `placeholder_status()` — 仍保留供既有前端讀取
2. `list_form_templates()` — 列出 form_templates/*.json 摘要
3. `get_form_template(id)` — 取得完整 template + 已綁定的 mock elder profile
4. `get_mock_elder_profile()` — 讀 data/mock_elder_profile.json

PDF 回填、LLM 對應、人工 review 預留下個迭代。
"""
from __future__ import annotations
import json
from datetime import date
from pathlib import Path
from typing import Any

from .welfare_form_templates import list_templates, load_template
from ..config import settings

DATA_DIR = settings.data_path
MOCK_ELDER_PATH = DATA_DIR / "mock_elder_profile.json"


def placeholder_status() -> dict[str, Any]:
    """v0.3.x 起前端首頁打的健康檢查端點 — 維持回相容資料。"""
    templates = list_templates()
    return {
        "feature": "welfare_form_autofill",
        "status": "preset_templates_loaded",
        "version": "v0.4.0-alpha",
        "templates_count": len(templates),
        "templates_ready": [t["id"] for t in templates if t.get("status") == "ready"],
        "next_steps": [
            "PDF 實際回填（PyMuPDF widget.field_value / page.insert_text）",
            "LLM 把 elder profile 映射到 fields（DeepSeek-V4-Pro）",
            "前端 review UI（每欄左右並列、可改）",
            "其餘 3 份 PDF 補座標標註",
        ],
    }


def list_form_templates() -> dict[str, Any]:
    """回所有預設套組摘要 + 是否有 mock 長者資料。"""
    templates = list_templates()
    return {
        "version": "v0.4.0-alpha",
        "count": len(templates),
        "templates": templates,
        "has_mock_elder": MOCK_ELDER_PATH.exists(),
    }


def get_form_template(template_id: str) -> dict[str, Any]:
    """取完整 template，附上 mock elder profile 供前端預覽 binding。"""
    tpl = load_template(template_id)
    elder = get_mock_elder_profile()
    # runtime 注入 today（OALA 等表格的「申請日期」欄位會用）
    today = date.today()
    elder = dict(elder)
    elder["today"] = {
        "iso": today.isoformat(),
        "year": str(today.year),
        "month": f"{today.month:02d}",
        "day": f"{today.day:02d}",
    }
    return {"template": tpl, "elder_profile": elder}


def get_mock_elder_profile() -> dict[str, Any]:
    if not MOCK_ELDER_PATH.exists():
        return {}
    return json.loads(MOCK_ELDER_PATH.read_text(encoding="utf-8"))
