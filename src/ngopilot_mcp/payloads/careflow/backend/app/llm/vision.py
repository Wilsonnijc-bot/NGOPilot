"""GPT-5-mini 視覺抽取：志工探訪表照片 → 結構化 JSON。

v0.4.0-rc6：主視覺路徑由 Qwen3.6-Plus / Azure GPT-5-mini 雙路改為 **OpenAI 官方 GPT-5-mini 單路**。
走 `get_vision_client()` (OpenAI 官網 base_url)。

設計重點：
1. **強制 JSON output** — 用 response_format=json_object 並在 prompt 鎖 schema。
2. **per-field confidence + bbox 溯源** — 後端要把這兩項一併存入，前端做色標 + 點欄看區域。
3. **Mock 模式** — 沒 OpenAI API key 時回傳合理 mock，demo 不被卡。
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import settings
from .client import get_vision_client, resolve_model

logger = logging.getLogger(__name__)

# ── 影像預處理（v0.3.6）─────────────────────────────────────────
# 超過此體積或長邊即縮+重壓 JPEG@85，避免大 PNG 把 base64 撐爆 + 拖慢 Qwen
_IMAGE_MAX_BYTES = 800 * 1024  # 800 KB
_IMAGE_MAX_DIM = 1600  # px
_JPEG_QUALITY = 85


def _preprocess_image_bytes(raw: bytes, ext: str) -> tuple[bytes, str]:
    """若圖太大就縮 + 重壓為 JPEG；否則原樣返回。

    Returns: (out_bytes, out_ext)
    """
    if len(raw) <= _IMAGE_MAX_BYTES and ext.lower() not in {"png"}:
        return raw, ext
    try:
        from PIL import Image  # 局部 import 避免測試環境負擔
    except Exception:
        logger.warning("vision preprocess (PIL import) failed", exc_info=True)
        return raw, ext  # 沒裝 Pillow 就跳過
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
        # 處理透明 PNG → 鋪白底
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, (255, 255, 255))
            if im.mode == "P":
                im = im.convert("RGBA")
            bg.paste(im, mask=im.split()[-1] if im.mode in ("RGBA", "LA") else None)
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        # 縮圖（保持長寬比）
        w, h = im.size
        long_side = max(w, h)
        if long_side > _IMAGE_MAX_DIM:
            scale = _IMAGE_MAX_DIM / long_side
            new_size = (int(w * scale), int(h * scale))
            im = im.resize(new_size, Image.LANCZOS)
        # 重壓 JPEG
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
        return buf.getvalue(), "jpeg"
    except Exception:
        logger.warning("vision preprocess (image convert) failed", exc_info=True)
        return raw, ext  # 任何錯誤都退回原檔，不要擋住主流程

# ── 視覺呼叫日誌（JSONL，附時間戳，便於使用者實測後分析） ──────────────────
_LOG_LOCK = threading.Lock()


def _log_path() -> Path:
    p = Path(__file__).resolve().parents[2] / "logs" / "vision.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _log_event(kind: str, **fields: Any) -> None:
    """附加一行 JSONL 到 backend/logs/vision.log，附 ISO 時間戳 + PID + thread。"""
    rec = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "pid": os.getpid(),
        "thread": threading.current_thread().name,
        "kind": kind,
        **fields,
    }
    line = json.dumps(rec, ensure_ascii=False)
    with _LOG_LOCK:
        try:
            with _log_path().open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:  # noqa: BLE001
            logger.warning("vision log write failed", exc_info=True)

# ── 志工表 schema（與 frontend 對齊）──────────────────────────────────────
VOLUNTEER_FORM_FIELDS = [
    {"key": "elder_name",        "label": "長者姓名",       "type": "string"},
    {"key": "elder_age",         "label": "年齡",          "type": "number"},
    {"key": "elder_gender",      "label": "性別",          "type": "enum", "options": ["男", "女"]},
    {"key": "elder_phone",       "label": "聯絡電話",       "type": "string"},
    {"key": "elder_address",     "label": "地址",          "type": "string"},
    {"key": "living_alone",      "label": "獨居",          "type": "enum", "options": ["是", "否", "不詳"]},
    {"key": "visit_date",        "label": "探訪日期",       "type": "date"},
    {"key": "volunteer_name",    "label": "志工姓名",       "type": "string"},
    {"key": "duration_minutes",  "label": "探訪時長（分鐘）", "type": "number"},
    {"key": "mood",              "label": "情緒狀態",       "type": "enum", "options": ["良好", "一般", "低落", "焦慮", "不詳"]},
    {"key": "health_concerns",   "label": "健康關注",       "type": "string"},
    {"key": "follow_up_needed",  "label": "需要跟進",       "type": "enum", "options": ["是", "否"]},
    {"key": "follow_up_note",    "label": "跟進備註",       "type": "string"},
]

FIELD_KEYS = [f["key"] for f in VOLUNTEER_FORM_FIELDS]


SYSTEM_PROMPT = """你是一名專業的香港 NGO 行政助理，擅長從志工手寫的長者探訪表照片中精準抽取結構化資料。

核心原則：
- 你**必定**會仔細看照片，把照片上能讀到的每一個欄位都寫進 JSON。
- 即使字跡潦草、有筆誤、或拍攝角度不佳，**仍要**根據可見筆畫做最佳猜測，並在 confidence 上反映不確定度。
- **絕對不要**回傳整份 fields 全為 null 的結果。如果照片完全不可讀，請在 `_global_error` 欄位寫入「照片不可讀: <原因>」並仍嘗試提取任何可見資訊。

抽取規則：
1. 嚴格只回傳 JSON，不要任何解釋文字、不要 markdown code fence。
2. JSON 必須包含四個頂層 key：`fields`、`confidence`、`bbox`、`_global_error`（可為 null）。
3. `fields`：每個欄位的值（字串、數字、或 null）。**有看到內容就填**，看不見才設 null。
4. `confidence`：每個欄位的信心值（0.0 ~ 1.0 浮點數）。寫了值的欄位 confidence 不應低於 0.3。
5. `bbox`：每個欄位在照片上的座標 `[x, y, w, h]`，全部為相對值 0.0 ~ 1.0。即使不準也要給一個粗略區域，不要全給 0。
6. 香港常用繁體中文，日期用 YYYY-MM-DD。年齡只填數字。電話保留原樣（含分隔符）。
7. 不要照抄使用者訊息裡列出的欄位清單，那只是 schema 說明。"""


def _user_prompt() -> str:
    fields_md = "\n".join(
        f"- `{f['key']}` ({f['label']}, {f['type']})"
        + (f" 可選: {f.get('options')}" if f.get("options") else "")
        for f in VOLUNTEER_FORM_FIELDS
    )
    # 用「示意值」而不是 null，避免 LLM 直接照抄空殼回傳
    example = {
        "fields": {
            "elder_name": "張三",
            "elder_age": 80,
            "elder_gender": "男",
            "elder_phone": "9123 4567",
            "elder_address": "九龍XX邨X樓X室",
            "living_alone": "是",
            "visit_date": "2026-05-01",
            "volunteer_name": "李四",
            "duration_minutes": 45,
            "mood": "良好",
            "health_concerns": "高血壓",
            "follow_up_needed": "否",
            "follow_up_note": "",
        },
        "confidence": {k: 0.85 for k in FIELD_KEYS},
        "bbox": {k: [0.1, 0.1 + i * 0.05, 0.4, 0.05] for i, k in enumerate(FIELD_KEYS)},
        "_global_error": None,
    }
    return (
        "請從這張志工探訪表照片中抽取以下欄位：\n\n"
        f"{fields_md}\n\n"
        "以下是**格式示意**（值僅為示範，不可照抄；你必須讀照片上實際內容）：\n"
        f"```json\n{json.dumps(example, ensure_ascii=False, indent=2)}\n```\n\n"
        "再次提醒：照片上有什麼，你就填什麼。不要回傳全 null。\n請開始抽取。"
    )


# ── Mock 數據池 ────────────────────────────────────────────────────────────
_MOCK_POOL = [
    {"elder_name": "陳秀蘭", "elder_age": 82, "elder_gender": "女", "elder_phone": "9123 4567",
     "elder_address": "深水埗保安道 12 號 8 樓 B 室", "living_alone": "是",
     "visit_date": "2026-05-10", "volunteer_name": "李志明", "duration_minutes": 45,
     "mood": "低落", "health_concerns": "膝關節痛, 失眠", "follow_up_needed": "是",
     "follow_up_note": "建議轉介物理治療"},
    {"elder_name": "黃國強", "elder_age": 76, "elder_gender": "男", "elder_phone": "6234 5678",
     "elder_address": "觀塘瑞和街 28 號", "living_alone": "否",
     "visit_date": "2026-05-10", "volunteer_name": "陳家欣", "duration_minutes": 30,
     "mood": "良好", "health_concerns": "高血壓控制中", "follow_up_needed": "否",
     "follow_up_note": ""},
    {"elder_name": "李美玲", "elder_age": 79, "elder_gender": "女", "elder_phone": "9876 5432",
     "elder_address": "葵涌大連排道 35 號", "living_alone": "是",
     "visit_date": "2026-05-09", "volunteer_name": "張偉", "duration_minutes": 60,
     "mood": "一般", "health_concerns": "糖尿病, 視力下降", "follow_up_needed": "是",
     "follow_up_note": "下週覆診陪同"},
    {"elder_name": "張伯", "elder_age": 85, "elder_gender": "男", "elder_phone": "6111 2222",
     "elder_address": "黃大仙橫頭磡邨", "living_alone": "是",
     "visit_date": "2026-05-09", "volunteer_name": "林小慧", "duration_minutes": 50,
     "mood": "焦慮", "health_concerns": "近期失去配偶", "follow_up_needed": "是",
     "follow_up_note": "情緒支援, 連絡社工跟進"},
    {"elder_name": "吳婆婆", "elder_age": 88, "elder_gender": "女", "elder_phone": "5444 5555",
     "elder_address": "屯門安定邨", "living_alone": "否",
     "visit_date": "2026-05-08", "volunteer_name": "王俊輝", "duration_minutes": 40,
     "mood": "良好", "health_concerns": "輕度認知障礙", "follow_up_needed": "否",
     "follow_up_note": ""},
]


def _mock_extract(idx: int) -> dict[str, Any]:
    base = _MOCK_POOL[idx % len(_MOCK_POOL)].copy()
    # 製造一些信心值差異，讓 review UI 展示色標
    confidence = {k: round(0.7 + ((idx * 7 + i) % 30) / 100, 2) for i, k in enumerate(FIELD_KEYS)}
    # 隨機讓某幾個欄位低信心
    low_idx = (idx * 3) % len(FIELD_KEYS)
    confidence[FIELD_KEYS[low_idx]] = 0.45
    confidence[FIELD_KEYS[(low_idx + 2) % len(FIELD_KEYS)]] = 0.62
    # bbox（粗略網格分布）
    bbox = {}
    cols, rows = 2, 7
    for i, k in enumerate(FIELD_KEYS):
        col = i % cols
        row = i // cols
        bbox[k] = [round(0.08 + col * 0.46, 3), round(0.10 + row * 0.11, 3), 0.40, 0.08]
    return {
        "fields": {k: base.get(k) for k in FIELD_KEYS},
        "confidence": confidence,
        "bbox": bbox,
        "_mock": True,
    }


# ── 主入口 ────────────────────────────────────────────────────────────────
def extract_volunteer_form(photo_path: Path, photo_index: int = 0) -> dict[str, Any]:
    """從一張照片抽取志工探訪表結構化資料。

    回傳格式：
        {"fields": {...}, "confidence": {...}, "bbox": {...},
         "_meta": {"provider", "model", "latency_ms", "raw"}}
    """
    started = time.time()

    if settings.is_vision_mock:
        result = _mock_extract(photo_index)
        result["_meta"] = {
            "provider": "mock",
            "model": "mock-volunteer-extractor",
            "latency_ms": int((time.time() - started) * 1000),
            "raw": "[mock mode]",
        }
        return result

    client = get_vision_client()
    model = resolve_model("vision")

    # 讀檔 → 預處理 → base64
    image_bytes_raw = photo_path.read_bytes()
    raw_kb = round(len(image_bytes_raw) / 1024, 1)
    ext = photo_path.suffix.lower().lstrip(".") or "jpeg"
    if ext == "jpg":
        ext = "jpeg"
    image_bytes, ext = _preprocess_image_bytes(image_bytes_raw, ext)
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    image_url = f"data:image/{ext};base64,{image_b64}"

    photo_label = photo_path.name
    bytes_kb = round(len(image_bytes) / 1024, 1)
    vision_max_tokens = 2048
    if model == "careflow-gpt-5-mini" and client.__class__.__name__ == "_FoundryWrapper":
        # Foundry reasoning models can spend completion tokens on hidden reasoning before emitting JSON.
        vision_max_tokens = 4096
    _log_event(
        "extract_start",
        photo=photo_label,
        photo_index=photo_index,
        size_kb=bytes_kb,
        raw_size_kb=raw_kb,
        preprocessed=(bytes_kb != raw_kb),
        model=model,
        provider="azure_openai",
        timeout_s=settings.vision_timeout_seconds,
        max_retries=settings.vision_max_retries,
        max_tokens=vision_max_tokens,
    )

    last_error: Exception | None = None
    raw_text = ""
    # 增加 1 個額外 attempt 給「上次返回空」情形（不算進 max_retries，避免改設定）
    max_attempts = settings.vision_max_retries + 1 + 1
    prev_was_empty = False
    for attempt in range(max_attempts):
        attempt_started = time.time()
        try:
            _log_event(
                "extract_attempt",
                photo=photo_label,
                attempt=attempt + 1,
                attempts_max=max_attempts,
                corrective=prev_was_empty,
            )
            # 若上次回傳空殼，用更強的提示重試
            user_text = _user_prompt()
            sys_text = SYSTEM_PROMPT
            extra_temp = 0.1
            if prev_was_empty:
                user_text = (
                    "**注意：你剛剛回傳了一份空白 / 全 null 的 JSON，這是錯誤的。**\n\n"
                    "請仔細**重新檢視這張照片**：\n"
                    "- 一定有人在表格上寫了字（即使潦草）。\n"
                    "- 你必須讀出**至少 3 個欄位**，否則我會視為 API 故障。\n"
                    "- 如果某些字真的看不清，請用「？」佔位（例如「深水？？街」），**不要**整欄留空。\n\n"
                ) + _user_prompt()
                extra_temp = 0.35  # 提溫鼓勵不同輸出
            # v0.3.7: 不再用 with_options(timeout=float) — 會被 SDK 重解讀為 per-chunk；
            # 用 client 預設的 httpx.Timeout(read=60) 反而能真的 60s 切斷
            resp = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": sys_text},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_url}},
                            {"type": "text", "text": user_text},
                        ],
                    },
                ],
                temperature=extra_temp,
                max_tokens=vision_max_tokens,
            )
            raw_text = resp.choices[0].message.content or "{}"
            data = _parse_json_loose(raw_text)
            normalised = _normalise(data)
            non_empty = sum(1 for k in FIELD_KEYS if not _is_blank(normalised["fields"].get(k)))
            attempt_ms = int((time.time() - attempt_started) * 1000)
            # 偵測「整份空」回應 → 觸發 corrective retry
            if non_empty == 0 and attempt < max_attempts - 1:
                _log_event(
                    "extract_empty_response",
                    photo=photo_label,
                    attempt=attempt + 1,
                    attempt_ms=attempt_ms,
                    raw_len=len(raw_text),
                )
                prev_was_empty = True
                continue
            latency_ms = int((time.time() - started) * 1000)
            normalised["_meta"] = {
                "provider": "azure_openai",
                "model": model,
                "latency_ms": latency_ms,
                "raw": raw_text[:8000],
                "attempts": attempt + 1,
                "was_corrective": prev_was_empty,
            }
            _log_event(
                "extract_ok",
                photo=photo_label,
                attempt=attempt + 1,
                attempt_ms=attempt_ms,
                total_ms=latency_ms,
                non_empty_fields=non_empty,
                raw_len=len(raw_text),
                corrective=prev_was_empty,
            )
            return normalised
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            _log_event(
                "extract_attempt_fail",
                photo=photo_label,
                attempt=attempt + 1,
                attempt_ms=int((time.time() - attempt_started) * 1000),
                error=str(exc)[:500],
            )
            continue

    _log_event(
        "extract_fail",
        photo=photo_label,
        total_ms=int((time.time() - started) * 1000),
        error=str(last_error) if last_error else "unknown",
    )

    # 全部重試都失敗 → 回傳空殼 + 錯誤訊息（前端會引導人工填）
    return {
        "fields": {k: None for k in FIELD_KEYS},
        "confidence": {k: 0.0 for k in FIELD_KEYS},
        "bbox": {k: [0, 0, 0, 0] for k in FIELD_KEYS},
        "_meta": {
            "provider": "azure_openai",
            "model": model,
            "latency_ms": int((time.time() - started) * 1000),
            "raw": raw_text[:8000],
            "error": str(last_error) if last_error else "unknown",
        },
    }


def _parse_json_loose(text: str) -> dict[str, Any]:
    """容錯 JSON 解析：去掉可能的 ```json 包裝。"""
    text = text.strip()
    # 砍掉 markdown code fence
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    # 找第一個 { 到最後一個 }
    if not text.startswith("{"):
        s = text.find("{")
        e = text.rfind("}")
        if s != -1 and e != -1:
            text = text[s : e + 1]
    return json.loads(text)


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    fields = data.get("fields", {}) or {}
    confidence = data.get("confidence", {}) or {}
    bbox = data.get("bbox", {}) or {}

    out_fields: dict[str, Any] = {}
    out_conf: dict[str, float] = {}
    out_bbox: dict[str, list] = {}

    for k in FIELD_KEYS:
        out_fields[k] = fields.get(k) if k in fields else None
        try:
            out_conf[k] = float(confidence.get(k) or 0.0)
        except (TypeError, ValueError):
            out_conf[k] = 0.0
        bb = bbox.get(k) or [0, 0, 0, 0]
        try:
            out_bbox[k] = [float(x) for x in bb][:4]
            while len(out_bbox[k]) < 4:
                out_bbox[k].append(0.0)
        except (TypeError, ValueError):
            out_bbox[k] = [0.0, 0.0, 0.0, 0.0]

    return {"fields": out_fields, "confidence": out_conf, "bbox": out_bbox}


# ── 必填欄位 + 完整性評估 ──────────────────────────────────────────────────
# 「資訊完整」定義：所有 REQUIRED_KEYS 都有非空值，且 confidence ≥ 0.5
REQUIRED_KEYS = [
    "elder_name", "elder_age", "elder_gender", "elder_phone",
    "elder_address", "visit_date", "volunteer_name", "mood",
]
LOW_CONF_THRESHOLD = 0.5

# ── 局部識別失敗偵測 ────────────────────────────────────────────────────────
# 偵測 OCR/VLM 常見的「無法辨識」佔位符：?? ？？ 〇〇 ○○ XX xx ＿＿ ___ … ...
# 至少連續 2 個才算（避免誤判正常文字「X 光」「？」單字）。
_PARTIAL_PATTERNS = [
    re.compile(r"[?？]{2,}"),
    re.compile(r"[〇○]{1,}"),
    re.compile(r"(?:[Xx]){2,}"),
    re.compile(r"[＿_]{2,}"),
    re.compile(r"[…\u2026]{1,}"),
    re.compile(r"\.{3,}"),
    re.compile(r"[．。]{3,}"),
    re.compile(r"\[?(?:無法辨識|看不清|不清楚|模糊)\]?"),
    # 中文字 + 空格 + 中文字（OCR 漏字產生的「邀 加中心活」這類碎片）
    # 至少出現一次「漢字 + 空格 + 漢字」即視為可疑片段
    re.compile(r"[\u4e00-\u9fff][\s\u3000]+[\u4e00-\u9fff]"),
]


def find_partial_spans(value: Any) -> list[list[int]]:
    """回傳該欄位值中所有「無法辨識佔位符」的 [start, end] 位置陣列。

    e.g. "深水？？街1号" → [[2,4]]；"張〇某" → [[1,2]]。
    僅對字串生效；非字串回 []。
    """
    if not isinstance(value, str) or not value:
        return []
    spans: list[list[int]] = []
    for pat in _PARTIAL_PATTERNS:
        for m in pat.finditer(value):
            spans.append([m.start(), m.end()])
    spans.sort()
    # 合併重疊
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    return False


def assess_completeness(
    fields: dict[str, Any] | None,
    confidence: dict[str, float] | None,
) -> dict[str, Any]:
    """回傳 `{is_complete, missing_fields, low_confidence_fields}`。

    missing_fields = REQUIRED 且為空。
    low_confidence_fields = 有值但 confidence < LOW_CONF_THRESHOLD。
    is_complete = 沒有任何 missing。
    """
    fields = fields or {}
    confidence = confidence or {}
    missing: list[str] = []
    low_conf: list[str] = []
    partial: dict[str, list[list[int]]] = {}
    # 1) 對 REQUIRED 欄位偵測缺失 / 低信心
    for k in REQUIRED_KEYS:
        if _is_blank(fields.get(k)):
            missing.append(k)
            continue
        try:
            c = float(confidence.get(k) or 0.0)
        except (TypeError, ValueError):
            c = 0.0
        if 0 < c < LOW_CONF_THRESHOLD:
            low_conf.append(k)
    # 2) 對所有欄位偵測「局部識別失敗」佔位符（?? 〇〇 XX … 等）
    for k, v in fields.items():
        if k.startswith("__"):
            continue
        spans = find_partial_spans(v)
        if spans:
            partial[k] = spans
    return {
        "is_complete": (not missing) and (not partial),
        "missing_fields": missing,
        "low_confidence_fields": low_conf,
        "partial_fields": partial,
    }


# ── 自動補全 ───────────────────────────────────────────────────────────────
AUTO_COMPLETE_SYSTEM = """你是一名 NGO 行政助理，根據志工探訪表照片 + 已抽取的部分欄位，
針對「缺失」或「低信心」欄位，做出**合理推測**並補全。

規則：
1. 你只回傳一個 JSON，內含 `auto_filled`（每個鍵對應補全後的值）和 `auto_filled_confidence`（0.0 ~ 1.0）。
2. 對於完全無法推測的欄位，請省略不要硬填。
3. 補全策略：
   - 數字欄位：根據其他線索（例如出生年→年齡）。
   - 列舉欄位：若上下文暗示，選最合理選項，否則設「不詳」。
   - 文字欄位：如「跟進備註」可根據 mood/health_concerns 給出 1 句不超過 30 字的建議。
4. **不要**修改使用者已給定的欄位（present_fields）。
5. 香港繁體中文，YYYY-MM-DD。"""


def auto_complete_fields(
    photo_path: Path,
    present_fields: dict[str, Any],
    missing_fields: list[str],
    low_confidence_fields: list[str] | None = None,
) -> dict[str, Any]:
    """呼叫 LLM 對缺失/低信心欄位做補全。

    回傳：
        {"auto_filled": {key: value, ...},
         "auto_filled_confidence": {key: 0.0~1.0},
         "_meta": {provider, model, latency_ms}}
    """
    started = time.time()
    targets = list(dict.fromkeys((missing_fields or []) + (low_confidence_fields or [])))
    if not targets:
        return {"auto_filled": {}, "auto_filled_confidence": {}, "_meta": {"provider": "noop", "latency_ms": 0}}

    if settings.is_mock_mode:
        filled: dict[str, Any] = {}
        confs: dict[str, float] = {}
        defaults = {
            "elder_name": "未具名長者",
            "elder_age": 75,
            "elder_gender": "不詳",
            "elder_phone": "未提供",
            "elder_address": "地址不詳",
            "living_alone": "不詳",
            "visit_date": time.strftime("%Y-%m-%d"),
            "volunteer_name": "志工",
            "duration_minutes": 30,
            "mood": "不詳",
            "health_concerns": "無紀錄",
            "follow_up_needed": "否",
            "follow_up_note": "",
        }
        for k in targets:
            if k in defaults:
                filled[k] = defaults[k]
                confs[k] = 0.55
        return {
            "auto_filled": filled,
            "auto_filled_confidence": confs,
            "_meta": {"provider": "mock", "model": "mock-autocomplete",
                       "latency_ms": int((time.time() - started) * 1000)},
        }

    client = get_client()
    model = resolve_model("vision")
    image_bytes = photo_path.read_bytes()
    ext = photo_path.suffix.lower().lstrip(".") or "jpeg"
    if ext == "jpg":
        ext = "jpeg"
    image_bytes, ext = _preprocess_image_bytes(image_bytes, ext)
    image_url = f"data:image/{ext};base64,{base64.b64encode(image_bytes).decode('ascii')}"

    target_schema = [f for f in VOLUNTEER_FORM_FIELDS if f["key"] in targets]
    user_prompt = (
        "請對下列**缺失或低信心**欄位做合理補全：\n"
        + "\n".join(
            f"- `{f['key']}` ({f['label']}, {f['type']})"
            + (f" 可選: {f.get('options')}" if f.get("options") else "")
            for f in target_schema
        )
        + "\n\n已知欄位（不要修改）：\n"
        + json.dumps({k: v for k, v in present_fields.items() if not _is_blank(v)},
                     ensure_ascii=False, indent=2)
        + "\n\n請只回傳：\n```json\n{\"auto_filled\": {...}, \"auto_filled_confidence\": {...}}\n```"
    )

    photo_label = photo_path.name
    _log_event("autocomplete_start", photo=photo_label, targets=targets, model=model)
    try:
        resp = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": AUTO_COMPLETE_SYSTEM},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": user_prompt},
                ]},
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        raw = resp.choices[0].message.content or "{}"
        data = _parse_json_loose(raw)
        filled = {k: v for k, v in (data.get("auto_filled") or {}).items() if k in targets}
        confs_raw = data.get("auto_filled_confidence") or {}
        confs = {}
        for k in filled:
            try:
                confs[k] = float(confs_raw.get(k) or 0.5)
            except (TypeError, ValueError):
                confs[k] = 0.5
        latency_ms = int((time.time() - started) * 1000)
        _log_event(
            "autocomplete_ok", photo=photo_label,
            latency_ms=latency_ms, filled_keys=list(filled.keys()),
        )
        return {
            "auto_filled": filled,
            "auto_filled_confidence": confs,
            "_meta": {"provider": settings.llm_provider, "model": model,
                       "latency_ms": latency_ms},
        }
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.time() - started) * 1000)
        _log_event(
            "autocomplete_fail", photo=photo_label,
            latency_ms=latency_ms, error=str(exc)[:500],
        )
        return {
            "auto_filled": {},
            "auto_filled_confidence": {},
            "_meta": {"provider": settings.llm_provider, "model": model,
                       "latency_ms": latency_ms,
                       "error": str(exc)},
        }
