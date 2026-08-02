"""功能 θ：自訂 PDF 表單空白欄位偵測。

用 GPT-5-mini 分析 PDF 頁面影像，識別所有空白表單欄位（文字框、核取方塊、
日期欄、簽名區等），回傳每個欄位的標籤、類型、bbox。

與 alpha (vision.py) 的關鍵差異：
- Alpha 是從已填寫的手寫表中**讀取值**
- Theta 是從空白 PDF 表中**偵測欄位位置**
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF

from ..config import settings
from ..llm.vision import _log_event, _parse_json_loose, _preprocess_image_bytes
from ..llm.client import get_vision_client, resolve_model

# PDF 頁面渲染 DPI（高一點讓 GPT-5-mini 看得清小字標籤）
# rc6.5：取 180 + max_dim 1800 是經驗甜蜜點 — 太小看不清欄位，太大會 Foundry connection 中斷。
_RENDER_DPI = 180
# 單頁最大尺寸（長邊），超過就縮
_PAGE_MAX_DIM = 1800


SYSTEM_PROMPT = """你是一名專業的香港政府表格分析師，專精於識別 PDF 表格中需要市民填寫的所有欄位。

常見表單類型包括：CSSA 綜援申請、OALA 長者生活津貼、SSA-307 高齡津貼、CCSV 社區照顧服務券、Joyyou 樂悠咭 — 這些表格都有：
- 密集的表格儲存格（每個儲存格通常都是一個獨立欄位，要填姓名/住址/電話/出生日期/身份證號等）
- 大量「□」核取方塊（婚姻狀況、性別、是否擁有資產等）
- 簽名與日期欄
- 表格內的橫線（在標籤旁的細橫線就是手寫欄位）

你的任務：**極為詳盡**地找出此頁所有需要填寫的欄位。寧可多列也不要漏。

對每個欄位，你必須提供：
- `key`：英文 snake_case 識別碼（如 "applicant_name_zh", "hkid", "dob_day"）
- `label`：欄位旁的印刷標籤（保留原文，繁體中文或英文都可；雙語並列就只取較完整那段）
- `type`：只能是 `text` / `number` / `date` / `checkbox` / `signature` / `select` 之一
- `bbox`：`[x, y, w, h]` 相對座標（0.0 ~ 1.0）
  - x = 欄位左邊界 ÷ 頁寬，y = 欄位上邊界 ÷ 頁高
  - w = 欄位寬 ÷ 頁寬，  h = 欄位高 ÷ 頁高
- `confidence`：0.0 ~ 1.0

關鍵規則：
1. **只回 JSON**，不要任何解釋文字、不要 markdown code fence。
2. **每個核取方塊都是獨立欄位**（例如「□男 □女」是 2 個 checkbox 欄位，label 分別「男」「女」）。
3. **表格的每一儲存格都當欄位看待**，即使沒有明顯橫線。
4. 簽名區、日期欄即使靠近紙頁邊緣也要列出。
5. 純說明文字頁（無任何空白）才回空陣列。
6. 標籤忠於印刷文字，不要自己改寫或翻譯。

bbox **精確度規則（rc6.8 強化 — 位置 > 大小 > 數量）**：

**⚠️ 最高優先：位置必須精確。** 寧可少報幾欄，也不要把欄位框錯位置。
若你心中座標不確定 ±0.02 以上，請降低 confidence < 0.5，或乾脆不要列那一欄。

A. **目標精確定義**：bbox 必須**剛好覆蓋市民筆尖會落下的那一塊區域**：
   - text：標籤右側的橫線 / 框格 / 表格儲存格內的可寫空白。**不可包含標籤文字本身。**
   - checkbox：「□」這個方塊**的四條邊**，剛好內接這個小方塊，不可外擴。**不可包含旁邊的「男/女/已婚」文字。**
   - signature：簽名橫線的可寫範圍。
   - date：要寫日/月/年的格子或橫線。
B. **位置驗算法（自我檢查）**：在輸出每個 bbox 前，先在心中描述「這個 bbox 的中心點在頁面的哪裡」，比對標籤位置是否合理（例如標籤在頁面左上 25% 處，bbox 中心一般在標籤右側 5~30% 範圍內）。座標與描述不一致就重算。
C. **大小：寧小勿大、剛好貼合**：
   - 預設給「視覺上剛好包住可寫區域」的尺寸 — 不要為了「保險」外擴 padding。
   - 若難以判斷邊界，就向**內**收 10~20%，**絕不可向外擴**。
   - 不可大於實際區域；可以略小於實際（最多小 20%）。
D. **允許重疊**：相鄰儲存格、checkbox 與其標籤之間的 bbox 重疊**完全可接受**。**不要為了避免重疊而把框畫小或移位** — 每個欄位獨立判斷其正確位置即可，完全不考慮 bbox 之間的干涉。
E. **checkbox 尺寸範例**：典型小方塊 `w` 和 `h` 都在 0.012 ~ 0.025（頁面比例）。若你給的 checkbox bbox `w > 0.04`，幾乎一定是錯把標籤吃進來了，請重算。
F. **text 尺寸範例**：高度 `h` 通常 0.018 ~ 0.04；寬度視欄位 — 日期單格 0.04~0.08、姓名/電話 0.15~0.30、地址 0.40~0.60。超出這個範圍要懷疑自己框錯。
G. **若整列只有一條橫線、看不清左右邊界**：就把 bbox 限縮在橫線「中間 70%」，左右各留 15% 餘裕。

**錯誤示範（絕對禁止）**：
- ❌ checkbox bbox 把方塊 + 旁邊的「男」字一起框住
- ❌ text bbox 把標籤「姓名：」也包進去
- ❌ bbox 整個移位到鄰近欄位的位置上（坐標完全錯）
- ❌ 為了「保險」把 bbox 外擴 20% padding

**正確示範**：
- ✅ checkbox `□男 □女` → 2 個獨立 bbox，每個只框住自己的小方塊 (~0.02 x 0.02)
- ✅ text 「姓名：________」→ bbox 只在橫線範圍上，**不**包含「姓名：」三字
- ✅ 日期 `__年__月__日` → 3 個獨立 date bbox，分別在三個底線上"""


def _user_prompt(page_num: int, total_pages: int) -> str:
    return (
        f"這是第 {page_num + 1} / {total_pages} 頁。\n\n"
        "請找出此頁面上所有空白表單欄位，回傳 JSON：\n"
        "```json\n"
        "{\n"
        '  "page": <頁碼 0-indexed>,\n'
        '  "fields": [\n'
        '    {"key": "applicant_name", "label": "申請人姓名", "type": "text", '
        '"bbox": [0.3, 0.15, 0.5, 0.04], "confidence": 0.95},\n'
        '    {"key": "gender_male", "label": "男", "type": "checkbox", '
        '"bbox": [0.35, 0.25, 0.03, 0.03], "confidence": 0.9}\n'
        "  ]\n"
        "}\n"
        "```\n"
        "請開始分析。"
    )


def _render_page(pdf_doc: fitz.Document, page_index: int) -> bytes:
    """將 PDF 單頁渲染為 JPEG 位元組。"""
    page = pdf_doc[page_index]
    # 計算縮放倍率使長邊不超過 _PAGE_MAX_DIM
    rect = page.rect
    long_side = max(rect.width, rect.height)
    zoom = _PAGE_MAX_DIM / long_side if long_side > _PAGE_MAX_DIM else _RENDER_DPI / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
    return pix.tobytes(output="jpeg", jpg_quality=85)


def _field_key_from_label(label: str, index: int) -> str:
    """從中文標籤產生英文 snake_case key；無法轉換時用 fallback。"""
    # 簡單處理：常見對應
    key = label.strip()
    # 保留英數字 + 底線，其餘去除；轉小寫 + snake_case
    key = re.sub(r"[^\w\s]", "", key)
    key = re.sub(r"\s+", "_", key)
    key = key.lower().strip("_")
    if not key or len(key) < 2:
        key = f"field_{index}"
    # 若仍是中文（無英數），用 index fallback
    if re.search(r"[a-z0-9]", key) is None:
        key = f"field_{index}"
    return key[:40]


def _mock_fields_for_page(page_index: int) -> list[dict[str, Any]]:
    """為 demo / mock 模式產生模擬欄位。"""
    if page_index == 0:
        return [
            {"key": "applicant_name_zh", "label": "申請人姓名（中文）",
             "type": "text", "bbox": [0.30, 0.12, 0.50, 0.04], "confidence": 0.95},
            {"key": "applicant_name_en", "label": "Name in English",
             "type": "text", "bbox": [0.30, 0.18, 0.50, 0.04], "confidence": 0.95},
            {"key": "hkid", "label": "香港身份證號碼",
             "type": "text", "bbox": [0.30, 0.24, 0.35, 0.04], "confidence": 0.92},
            {"key": "gender_male", "label": "男",
             "type": "checkbox", "bbox": [0.32, 0.30, 0.03, 0.03], "confidence": 0.90},
            {"key": "gender_female", "label": "女",
             "type": "checkbox", "bbox": [0.42, 0.30, 0.03, 0.03], "confidence": 0.90},
            {"key": "dob_day", "label": "日",
             "type": "date", "bbox": [0.30, 0.36, 0.06, 0.04], "confidence": 0.88},
            {"key": "dob_month", "label": "月",
             "type": "date", "bbox": [0.40, 0.36, 0.06, 0.04], "confidence": 0.88},
            {"key": "dob_year", "label": "年",
             "type": "date", "bbox": [0.50, 0.36, 0.10, 0.04], "confidence": 0.88},
            {"key": "phone", "label": "聯絡電話",
             "type": "text", "bbox": [0.30, 0.42, 0.35, 0.04], "confidence": 0.93},
            {"key": "address", "label": "通訊地址",
             "type": "text", "bbox": [0.30, 0.48, 0.55, 0.08], "confidence": 0.91},
            {"key": "signature", "label": "申請人簽署",
             "type": "signature", "bbox": [0.30, 0.70, 0.40, 0.06], "confidence": 0.85},
            {"key": "date_of_application", "label": "日期",
             "type": "date", "bbox": [0.75, 0.70, 0.15, 0.04], "confidence": 0.87},
        ]
    else:
        return [
            {"key": f"extra_field_{page_index}_{i}", "label": f"其他欄位 {i + 1}",
             "type": "text", "bbox": [0.15, 0.15 + i * 0.10, 0.50, 0.04], "confidence": 0.75}
            for i in range(4)
        ]


def extract_form_blanks(pdf_path: Path) -> dict[str, Any]:
    """從 PDF 檔案偵測所有空白表單欄位。

    Returns:
        {"pages": [
            {"page": 0, "fields": [
                {"key": "applicant_name", "label": "申請人姓名", "type": "text",
                 "bbox": [0.3, 0.15, 0.5, 0.04], "confidence": 0.95},
                ...
            ]},
            ...
        ]}
    """
    started = time.time()

    if settings.is_vision_mock:
        _log_event(
            "theta_extract_mock",
            pdf=pdf_path.name,
            reason="is_vision_mock=True (no Azure credentials)",
        )
        doc = fitz.open(pdf_path)
        pages = []
        for i in range(len(doc)):
            fields = _mock_fields_for_page(i)
            pages.append({"page": i, "fields": fields})
        doc.close()
        return {
            "pages": pages,
            "_meta": {
                "provider": "mock",
                "model": "mock-theta-extractor",
                "latency_ms": int((time.time() - started) * 1000),
            },
        }

    client = get_vision_client()
    model = resolve_model("vision")
    pdf_label = pdf_path.name

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    all_pages: list[dict[str, Any]] = []
    last_error: str | None = None

    for page_idx in range(total_pages):
        page_started = time.time()
        _log_event(
            "theta_extract_page_start",
            pdf=pdf_label,
            page=page_idx,
            total_pages=total_pages,
        )
        try:
            image_bytes = _render_page(doc, page_idx)
            image_bytes, ext = _preprocess_image_bytes(image_bytes, "jpeg")
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
            image_url = f"data:image/jpeg;base64,{image_b64}"

            for attempt in range(2):
                attempt_started = time.time()
                try:
                    # 注意：Azure AI Foundry 的 gpt-4o-mini / gpt-5-mini deployment 不
                    # 接受 `response_format={"type": "json_object"}`（回 "Unsupported
                    # response_format"）。改靠 system prompt 強制 JSON + 寬鬆 parse。
                    is_reasoning = model.lower().startswith(("gpt-5", "o1", "o3", "o4"))
                    call_kwargs: dict[str, Any] = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {
                                "role": "user",
                                "content": [
                                    {"type": "image_url", "image_url": {"url": image_url}},
                                    {"type": "text", "text": _user_prompt(page_idx, total_pages)},
                                ],
                            },
                        ],
                    }
                    if is_reasoning:
                        # rc6.8：gpt-5-mini 是 reasoning 模型 — 必須用
                        # max_completion_tokens；給 32768 避免 reasoning 階段先吃光預算
                        # 導致 visible content 為空（rc6.5 失敗主因）。
                        # 同時 reasoning_effort="minimal" 把 reasoning 階段壓到最小，
                        # 把預算留給 JSON 輸出。
                        call_kwargs["max_completion_tokens"] = 32768
                        call_kwargs["extra_body"] = {"reasoning_effort": "minimal"}
                    else:
                        # gpt-4.1-mini 等非 reasoning 模型用傳統 max_tokens
                        call_kwargs["max_tokens"] = 16384
                    resp = client.chat.completions.create(**call_kwargs)
                    raw_text = resp.choices[0].message.content or "{}"
                    data = _parse_json_loose(raw_text)
                    fields = data.get("fields") or []
                    # normalise: ensure each field has all required keys
                    norm_fields: list[dict[str, Any]] = []
                    for fi, f in enumerate(fields):
                        label = str(f.get("label") or "")
                        norm_fields.append({
                            "key": str(f.get("key") or _field_key_from_label(label, fi)),
                            "label": label,
                            "type": f.get("type", "text"),
                            "bbox": _normalise_bbox(f.get("bbox")),
                            "confidence": float(f.get("confidence") or 0.5),
                        })
                    all_pages.append({"page": page_idx, "fields": norm_fields})
                    page_ms = int((time.time() - page_started) * 1000)
                    _log_event(
                        "theta_extract_page_ok",
                        pdf=pdf_label,
                        page=page_idx,
                        attempt=attempt + 1,
                        page_ms=page_ms,
                        field_count=len(norm_fields),
                        raw_len=len(raw_text),
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 0:
                        _log_event(
                            "theta_extract_page_retry",
                            pdf=pdf_label,
                            page=page_idx,
                            attempt=attempt + 1,
                            error=str(exc)[:300],
                        )
                        continue
                    raise
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            _log_event(
                "theta_extract_page_fail",
                pdf=pdf_label,
                page=page_idx,
                error=last_error[:500],
            )
            # 失敗頁面給空欄位，不擋整份流程
            all_pages.append({"page": page_idx, "fields": [], "_error": last_error[:500]})

    doc.close()

    # v0.4.5-foundry：移除 PyMuPDF 向量微調步驟（原本會把 LLM bbox 吸附到偵測到的
    # 橫線 / checkbox 方框）。GPT-5.1 直接給出可用 bbox，向量 snap 反而引入偏差；
    # 微調保留在前端 ThetaAudit 人工審查介面。
    refine_stats: dict[str, int] = {}

    return {
        "pages": all_pages,
        "_meta": {
            "provider": "azure_openai",
            "model": model,
            "latency_ms": int((time.time() - started) * 1000),
            "total_pages": total_pages,
            "last_error": last_error,
            "refine_stats": refine_stats,
        },
    }


def _normalise_bbox(bb: Any) -> list[float]:
    """正規化 bbox 為 [x, y, w, h] 浮點陣列。"""
    try:
        vals = [float(x) for x in bb][:4]
        # clamp to 0..1
        vals = [max(0.0, min(1.0, v)) for v in vals]
    except (TypeError, ValueError, IndexError):
        return [0.0, 0.0, 0.0, 0.0]
    while len(vals) < 4:
        vals.append(0.0)
    return vals


def render_page_image(pdf_path: Path, page_index: int) -> bytes:
    """渲染 PDF 單頁為 JPEG 位元組（供前端 audit 顯示）。"""
    doc = fitz.open(pdf_path)
    try:
        if page_index < 0 or page_index >= len(doc):
            raise ValueError(f"page_index {page_index} out of range (0..{len(doc) - 1})")
        return _render_page(doc, page_index)
    finally:
        doc.close()
