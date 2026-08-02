"""Welfare form templates — 預設套組載入器。

設計理念
========
不同政府表格的「可機器化程度」差別很大：
  * `joyyou_apply.pdf` 內建 AcroForm widget（已命名欄位），可直接 `widget.field_value = "..."`
  * `OALA / SSA / CSSA / CCSV` 是純文字 PDF，沒 widget，必須用「文字錨點 + 偏移座標」寫上去

所以每個 template 都有 `fill_strategy`：
  - "acroform"     → 透過 widget name 寫入
  - "coord_anchor" → 透過 `anchor_text` 找錨點，於 `write_rect` 處 `page.insert_text()`

統一 input 來自 ElderProfile（mock 在 `data/mock_elder_profile.json`）。

回傳給 frontend 的 schema：
{
  "id": "joyyou",
  "display_name": "...",
  "pdf_pages": 4,
  "fill_strategy": "acroform" | "coord_anchor",
  "elder_profile_keys": [<list of elder profile keys this form needs>],
  "fields": [
    {"key":"name_zh","label_zh":"姓名(中文)","label_en":"Name (Chinese)",
     "type":"text"|"radio"|"date_parts"|"hkid",
     "elder_profile_path":"name_zh",
     "fill":{...strategy-specific...}}
  ]
}
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from ..config import settings

TEMPLATE_DIR = settings.data_path / "form_templates"


def list_templates() -> list[dict[str, Any]]:
    """列出所有可用預設套組，回傳精簡摘要（不含 fields 細節）。"""
    if not TEMPLATE_DIR.exists():
        return []
    out = []
    for fp in sorted(TEMPLATE_DIR.glob("*.json")):
        if fp.name.startswith("_"):
            continue
        try:
            t = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        out.append({
            "id": t.get("id"),
            "display_name": t.get("display_name"),
            "display_name_en": t.get("display_name_en"),
            "source_pdf": t.get("source_pdf"),
            "pdf_pages": t.get("pdf_pages"),
            "fill_strategy": t.get("fill_strategy"),
            "field_count": len(t.get("fields") or []),
            "status": t.get("status", "ready"),
            "notes": t.get("notes"),
        })
    return out


def load_template(template_id: str) -> dict[str, Any]:
    """載入完整 template；找不到時拋 ValueError。"""
    fp = TEMPLATE_DIR / f"{template_id}.json"
    if not fp.exists():
        raise ValueError(f"template not found: {template_id}")
    return json.loads(fp.read_text(encoding="utf-8"))
