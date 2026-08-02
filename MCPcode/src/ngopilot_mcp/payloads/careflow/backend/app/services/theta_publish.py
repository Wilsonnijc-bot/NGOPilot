"""v0.4.0-rc6.7：把已 confirm 的 theta 模板「發佈」到 gamma 套組列表。

設計
====
Theta 流程產出的 ThetaField 用「頁面相對 bbox（0..1）」；γ filler 需要 PDF point
座標的 `write_rect` / `tick_rect`。本檔負責：

1. 開啟原始 PDF，讀每頁尺寸（pt）
2. 將每個 theta field 的 bbox → write_rect（text/date/...）或 tick_rect（checkbox）
3. 寫成 `data/form_templates/theta_<id>.json`，schema 與 OALA/CSSA 同款
4. 留 `elder_profile_path=""` —— 由 γ 端的 LLM 對映或人工 review 後填入

副作用：γ 端 `list_form_templates()` 會自動撿到此檔案。

注意：寫到 `data/form_templates/` 是設計取捨 —— 重新 confirm 同一個 theta
template 會覆蓋舊檔；刪除 theta template 時也應該刪掉對應檔案（呼叫
`unpublish_theta_template`）。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from ..config import settings
from .welfare_form_templates import TEMPLATE_DIR

logger = logging.getLogger(__name__)


def _published_path(theta_id: int) -> Path:
    return TEMPLATE_DIR / f"theta_{theta_id}.json"


def _convert_field(
    f: dict,
    page_w: float,
    page_h: float,
) -> dict | None:
    """ThetaField row dict → gamma form_template field dict。bbox 缺失回 None。"""
    bbox = f.get("bbox") or [0, 0, 0, 0]
    if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
        return None
    x, y, w, h = (float(v) for v in bbox)
    # PDF points (origin top-left for fitz)
    x0 = round(x * page_w, 1)
    y0 = round(y * page_h, 1)
    x1 = round((x + w) * page_w, 1)
    y1 = round((y + h) * page_h, 1)
    if x1 <= x0 or y1 <= y0:
        return None

    ftype = (f.get("type") or "text").lower()
    page_no = int(f.get("page_number", 0)) + 1  # gamma 用 1-indexed

    label = f.get("label") or f.get("key") or ""
    base = {
        "key": f.get("key") or f"field_{page_no}_{int(x*1000)}_{int(y*1000)}",
        "label_zh": label,
        "type": "text",
        "elder_profile_path": "",  # 留空 → γ preview 會顯示 missing；之後人工 / LLM 對映
        "_theta_origin": {
            "page_number": int(f.get("page_number", 0)),
            "bbox": [round(v, 4) for v in bbox],
            "confidence": float(f.get("confidence", 0.0)),
        },
    }

    if ftype == "checkbox":
        base["type"] = "checkbox"
        base["fill"] = {
            "page": page_no,
            "anchor_text": "",        # 留空 → _check_anchor 直接 pass
            "tick_rect": [x0, y0, x1, y1],
            "tick_when_equals": "TRUE",  # 人工 review 時改成真正條件
        }
    elif ftype == "signature":
        base["type"] = "text"
        base["fill"] = {
            "page": page_no,
            "anchor_text": "",
            "write_rect": [x0, y0, x1, y1],
            "font_size": 10,
        }
    else:
        # text / number / date / select 都走文字寫入
        base["type"] = "long_text" if (x1 - x0) > page_w * 0.45 else "text"
        base["fill"] = {
            "page": page_no,
            "anchor_text": "",
            "write_rect": [x0, y0, x1, y1],
            "font_size": 10 if ftype != "date" else 11,
        }
    return base


def publish_theta_template(
    theta_template: Any,
    theta_fields: list[Any],
) -> Path:
    """把 ThetaTemplate + ThetaField 寫成 gamma form_template JSON。

    `theta_template` 與 `theta_fields` 接受 ORM 物件或 dict（測試方便）。
    """
    def _g(obj: Any, attr: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(attr, default)
        return getattr(obj, attr, default)

    tid = _g(theta_template, "id")
    name = _g(theta_template, "name") or f"自訂模板 #{tid}"
    pdf_rel = _g(theta_template, "original_pdf_path") or ""
    page_count = int(_g(theta_template, "page_count", 0))

    pdf_full = settings.data_path / pdf_rel
    if not pdf_full.exists():
        raise FileNotFoundError(f"PDF not found for theta template {tid}: {pdf_full}")

    # 讀每頁尺寸
    page_sizes: dict[int, tuple[float, float]] = {}
    doc = fitz.open(pdf_full)
    try:
        for i in range(len(doc)):
            r = doc[i].rect
            page_sizes[i] = (r.width, r.height)
    finally:
        doc.close()

    # 轉欄位
    fields_out: list[dict] = []
    for f in theta_fields:
        page_idx = int(_g(f, "page_number", 0))
        pw, ph = page_sizes.get(page_idx, (595.0, 842.0))  # fallback A4
        # ThetaField 用 field_key / field_label / field_type，先 normalise
        row = {
            "key": _g(f, "field_key") or _g(f, "key"),
            "label": _g(f, "field_label") or _g(f, "label"),
            "type": _g(f, "field_type") or _g(f, "type") or "text",
            "bbox": _g(f, "bbox"),
            "confidence": _g(f, "confidence", 0.0),
            "page_number": page_idx,
        }
        conv = _convert_field(row, pw, ph)
        if conv:
            fields_out.append(conv)

    out = {
        "id": f"theta_{tid}",
        "display_name": name,
        "display_name_en": "",
        "source_pdf": Path(pdf_rel).name,
        "pdf_pages": page_count,
        "form_page": 1,
        "fill_strategy": "coord_anchor",
        "status": "ready",
        "notes": (
            f"由 θ 流水線發佈（template #{tid}）。bbox 從相對座標轉為 PDF point；"
            "anchor_text 留空（_check_anchor pass），elder_profile_path 待人工 / LLM 對映。"
        ),
        "font": {"family": "china-s", "size": 10, "color": [0, 0, 0]},
        "elder_profile_keys": [],
        "_theta_origin": {"template_id": tid, "page_count": page_count, "pdf_path": pdf_rel},
        "fields": fields_out,
    }

    target = _published_path(tid)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("theta_publish wrote %s (%d fields)", target, len(fields_out))
    return target


def unpublish_theta_template(theta_id: int) -> bool:
    p = _published_path(theta_id)
    if p.exists():
        p.unlink()
        logger.info("theta_publish removed %s", p)
        return True
    return False
