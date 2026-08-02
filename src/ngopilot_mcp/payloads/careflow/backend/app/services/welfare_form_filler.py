"""v0.4.0-beta：將 elder profile 套到 form template，產生填好的 PDF。

兩種策略
--------
1. **acroform**：透過 widget 名直接 `widget.field_value = "..."` + `widget.update()`，
   PDF 內既有的互動 widget 會自動顯示文字。joyyou 走這條路徑。
2. **coord_anchor**：純文字 PDF，沒 widget。每欄都有 `anchor_text` 做運行期校驗，
   找到後在 `write_rect` 處 `page.insert_text()` 寫入；勾選 / radio 在 `tick_rect` 寫 `glyph`。
   OALA 走這條。

ElderProfile 路徑解析
---------------------
`elder_profile_path = "name_zh.family"` → 走 dict 取 `elder["name_zh"]["family"]`。
找不到回 `""`（後續 review UI 可手填）。

輸出
----
PDF 寫到 `data/welfare_outputs/<elder_id>_<template_id>_<ts>.pdf`，回 download URL
（透過既有 `/api/files/{path}` 端點供應）。
"""
from __future__ import annotations
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from ..config import settings
from .welfare_form_templates import TEMPLATE_DIR, load_template

logger = logging.getLogger(__name__)

DATA_DIR = settings.data_path
PDF_SOURCE_DIR = DATA_DIR / "templates"
OUTPUT_DIR = DATA_DIR / "welfare_outputs"

# 中文字體 — PyMuPDF 內建 china-s（簡體繁體都涵蓋）
FONT_NAME = "china-s"
DEFAULT_FONT_SIZE = 10
DEFAULT_COLOR = (0, 0, 0)
LONG_TEXT_OVERFLOW_CHARS = 28  # 寫到第一行的最多字數，超過跳 overflow_rect


# ─── 工具：路徑解析 ──────────────────────────────────────────────────────
def _resolve_path(elder: dict[str, Any], path: str | None) -> Any:
    """elder profile 取值：`name_zh.family` → elder["name_zh"]["family"]。"""
    if not path:
        return None
    cur: Any = elder
    for seg in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(seg)
        if cur is None:
            return None
    return cur


def _stringify(v: Any, default: str = "") -> str:
    if v is None:
        return default
    if isinstance(v, (str, int, float)):
        return str(v)
    return json.dumps(v, ensure_ascii=False)


# ─── acroform 策略 ──────────────────────────────────────────────────────
def _fill_acroform(doc: fitz.Document, template: dict, field_values: dict[str, str]) -> dict:
    """走 widget 名稱寫入；回 stats。
    注意：PyMuPDF 的 Widget 物件不能 cache（會 detach from page），
    所以這裡先建一張 (page_no, widget_name) → value 對應表，再逐頁 walk widgets 寫入。"""
    stats = {"strategy": "acroform", "filled": 0, "missing_widget": [], "empty_value": []}

    plan: dict[tuple[int, str], dict] = {}
    for f in template.get("fields", []):
        fill = f.get("fill", {})
        page_no = int(fill.get("page", 1))
        wname = fill.get("widget")
        if not wname:
            continue
        value = field_values.get(f["key"], "")
        plan[(page_no, wname)] = {"key": f["key"], "value": value}

    seen_widgets: set[tuple[int, str]] = set()
    for pi, page in enumerate(doc):
        for w in page.widgets() or []:
            key = (pi + 1, w.field_name)
            seen_widgets.add(key)
            if key not in plan:
                continue
            entry = plan[key]
            if not entry["value"]:
                stats["empty_value"].append(entry["key"])
                w.field_value = ""
                w.update()
                continue
            w.field_value = entry["value"]
            w.update()
            stats["filled"] += 1

    for k in plan:
        if k not in seen_widgets:
            stats["missing_widget"].append(k[1])
    return stats


# ─── coord_anchor 策略 ───────────────────────────────────────────────────
def _check_anchor(page: fitz.Page, anchor: str | None) -> bool:
    """anchor_text 必須能在此頁找到；找不到代表 PDF 版面漂移，回 False。"""
    if not anchor:
        return True
    try:
        rects = page.search_for(anchor)
        return bool(rects)
    except Exception:  # noqa: BLE001
        logger.warning("welfare anchor check failed for %r", anchor, exc_info=True)
        return False


def _insert_text(page: fitz.Page, rect: list[float], text: str, font_size: int, spread: bool = False, font: str = FONT_NAME) -> None:
    """在 rect 起點稍上方寫入文字（rect 是 PDF 規範，y 軸向下；baseline 約在 rect 底邊 - 3）。
    spread=True 時，逐字等距分佈於 rect 寬度（適用日期框、HKID 等等距格子）。
    font='helv' for ASCII-only fields to avoid CJK full-width spacing."""
    if not text:
        return
    baseline_y = rect[3] - 3
    if spread and len(text) > 1:
        width = rect[2] - rect[0]
        step = width / len(text)
        for i, ch in enumerate(text):
            cx = rect[0] + step * (i + 0.5) - font_size * 0.3
            try:
                page.insert_text((cx, baseline_y), ch, fontname=font, fontsize=font_size, color=DEFAULT_COLOR)
            except Exception as exc:  # noqa: BLE001
                logger.warning("welfare insert_text(spread) char %r failed: %s", ch, exc)
                page.insert_text((cx, baseline_y), ch, fontsize=font_size, color=DEFAULT_COLOR)
        return
    x = rect[0] + 2
    try:
        page.insert_text(
            (x, baseline_y),
            text,
            fontname=font,
            fontsize=font_size,
            color=DEFAULT_COLOR,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("insert_text fallback (no chinese font?) %s: %s", e, text[:30])
        page.insert_text(
            (x, baseline_y),
            text,
            fontsize=font_size,
            color=DEFAULT_COLOR,
        )


def _insert_tick(page: fitz.Page, rect: list[float] | None, font_size: int) -> None:
    """在 tick_rect 中央畫一個勾選 ✓。
    避開 china-s 字型在 ✓ (U+2713) 的 CID 對應錯位（會渲染成 ㎏ 一類無關字符），
    改用 Helvetica + ASCII "X" 確保跨環境穩定。"""
    if not rect:
        return
    cx = (rect[0] + rect[2]) / 2 - font_size * 0.35
    cy = (rect[1] + rect[3]) / 2 + font_size * 0.35
    try:
        page.insert_text(
            (cx, cy),
            "X",
            fontname="helv",
            fontsize=font_size + 1,
            color=DEFAULT_COLOR,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("insert_tick failed: %s", e)


def _fill_coord_anchor(doc: fitz.Document, template: dict, field_values: dict[str, str]) -> dict:
    stats = {
        "strategy": "coord_anchor",
        "filled": 0,
        "anchor_missing": [],
        "empty_value": [],
        "ticked": 0,
    }
    font_cfg = template.get("font", {})
    base_font_size = int(font_cfg.get("size", DEFAULT_FONT_SIZE))

    for f in template.get("fields", []):
        fill = f.get("fill", {})
        page_no = int(fill.get("page", 1))
        page = doc[page_no - 1]
        ftype = f.get("type", "text")
        value = field_values.get(f["key"], "")
        # 容許每欄覆蓋字級（HKID/DOB 等寫入區窄要縮小）
        font_size = int(fill.get("font_size", base_font_size))

        # 1. 文字 / long_text
        if ftype in ("text", "long_text"):
            anchor = fill.get("anchor_text")
            if not _check_anchor(page, anchor):
                stats["anchor_missing"].append({"key": f["key"], "anchor": anchor})
                continue
            if not value:
                stats["empty_value"].append(f["key"])
                continue
            rect = fill.get("write_rect")
            overflow = fill.get("overflow_rect")
            if ftype == "long_text" and overflow and len(value) > LONG_TEXT_OVERFLOW_CHARS:
                head = value[:LONG_TEXT_OVERFLOW_CHARS]
                tail = value[LONG_TEXT_OVERFLOW_CHARS:]
                _insert_text(page, rect, head, font_size, font=fill.get("font", FONT_NAME))
                _insert_text(page, overflow, tail, font_size, font=fill.get("font", FONT_NAME))
            else:
                _insert_text(page, rect, value, font_size, spread=bool(fill.get("spread_chars")), font=fill.get("font", FONT_NAME))
            stats["filled"] += 1
            continue

        # 2. checkbox：value 就是 elder 給的條件值（例如 "M"），比 tick_when_equals
        if ftype == "checkbox":
            anchor = fill.get("anchor_text")
            if anchor and not _check_anchor(page, anchor):
                stats["anchor_missing"].append({"key": f["key"], "anchor": anchor})
                continue
            target = fill.get("tick_when_equals")
            if str(value) == str(target):
                _insert_tick(page, fill.get("tick_rect"), font_size)
                stats["ticked"] += 1
            continue

        # 3. radio_group：value 是被選中的選項 value
        if ftype == "radio_group":
            options = fill.get("options", [])
            matched = next((o for o in options if str(o.get("value")) == str(value)), None)
            if not matched:
                stats["empty_value"].append(f["key"])
                continue
            if not _check_anchor(page, matched.get("anchor_text")):
                stats["anchor_missing"].append({"key": f["key"], "anchor": matched.get("anchor_text")})
                continue
            _insert_tick(page, matched.get("tick_rect"), font_size)
            stats["ticked"] += 1
            continue

    return stats


# ─── 公開入口 ─────────────────────────────────────────────────────────────
def fill_form(
    template_id: str,
    elder_profile: dict[str, Any] | None = None,
    field_values: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """把 field_values 套到 template 並生成 PDF。

    優先順序：
      1. `field_values` 直接給（一般是前端 review 後傳回）
      2. 否則從 `elder_profile` 走 mapping 自動生
      3. `overrides` 永遠覆寫前兩者
    """
    from .welfare_form_mapping import map_elder_to_template

    template = load_template(template_id)
    source_pdf = PDF_SOURCE_DIR / template["source_pdf"]
    if not source_pdf.exists():
        raise FileNotFoundError(f"source PDF not found: {source_pdf}")

    # 預備 field_values
    if field_values is None:
        if elder_profile is None:
            raise ValueError("either field_values or elder_profile must be provided")
        elder = dict(elder_profile)
        if "today" not in elder:
            from datetime import date
            d = date.today()
            elder["today"] = {
                "iso": d.isoformat(),
                "year": str(d.year),
                "month": f"{d.month:02d}",
                "day": f"{d.day:02d}",
            }
        mapping = map_elder_to_template(template, elder, use_llm=False)
        field_values = {m["key"]: m.get("value", "") for m in mapping["mappings"]}

    if overrides:
        field_values = {**field_values, **{k: str(v) if v is not None else "" for k, v in overrides.items()}}

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    elder_id = (elder_profile or {}).get("elder_id", "anon")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_name = f"{elder_id}_{template_id}_{ts}.pdf"
    output_path = OUTPUT_DIR / output_name

    t0 = time.time()
    doc = fitz.open(source_pdf)
    strategy = template.get("fill_strategy")
    try:
        if strategy == "acroform":
            stats = _fill_acroform(doc, template, field_values)
        elif strategy == "coord_anchor":
            stats = _fill_coord_anchor(doc, template, field_values)
        else:
            raise ValueError(f"unknown fill_strategy: {strategy}")
        doc.save(output_path, garbage=4, deflate=True)
    finally:
        doc.close()
    latency_ms = int((time.time() - t0) * 1000)

    rel_path = output_path.relative_to(settings.data_path) if str(output_path).startswith(str(settings.data_path)) else Path("welfare_outputs") / output_name
    download_url = f"/api/files/{rel_path.as_posix()}"

    return {
        "ok": True,
        "template_id": template_id,
        "output_file": output_name,
        "download_url": download_url,
        "stats": stats,
        "latency_ms": latency_ms,
        "filled_at": datetime.utcnow().isoformat(),
    }
