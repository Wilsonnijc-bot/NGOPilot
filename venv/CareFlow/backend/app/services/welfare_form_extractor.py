"""v0.4.0-rc2：raw text → ElderProfile JSON。

接受用戶丟進來的散文 / 表格 / 個人介紹文字（中英混雜），用 DeepSeek-V4-Pro
（response_format=json_object）抽取成 mock_elder_profile.json 結構的字典，
然後可以直接接 /welfare-form/preview-mapping 或 /fill。

mock 模式下回一個固定 demo profile（陳大文）配合單元測試。
"""
from __future__ import annotations
import json
import logging
import re
import time
from typing import Any

from ..config import settings
from ..llm.client import get_text_client, get_vision_client, resolve_model

logger = logging.getLogger(__name__)


# ── 嚴格 schema 提示，跟 mock_elder_profile.json 對齊 ───────────────────────
EXTRACT_SYSTEM = (
    "你是香港 NGO 社工資料萃取助理。給你一段長者個人資料（散文 / 表格 / 病歷 / "
    "對話記錄都有可能），請抽成嚴格 JSON。\n\n"
    "規則：\n"
    "1. 全部使用繁體中文；英文姓名保留原大小寫，並補一份 full_upper 全大寫版本。\n"
    "2. HKID 找不到 → 'main' 留空字串；找到要拆 main+check（括號內字）。\n"
    "3. 出生日期一律轉成 ISO 'YYYY-MM-DD'；同時拆 year/month/day（month/day 兩位零補齊）。\n"
    "4. 電話只保留數字（去除 +852 / 空格 / 連字號）。\n"
    "5. 地址盡量拆 room/floor/block/estate/street/district；同時給整段 address_text。\n"
    "6. 找不到的欄位用空字串 / null（不要編造）。\n"
    "7. sex ∈ {'M','F'}；marital_status ∈ {'single','married','divorced','separated','widowed','cohabiting'}。\n\n"
    "回傳 JSON 結構（完全照抄這個 schema 的 key）：\n"
    "{\n"
    '  "elder_id": "EXTRACTED-XXXX",\n'
    '  "name_zh": {"full":"","family":"","given":""},\n'
    '  "name_en": {"full":"","full_upper":"","family":"","given":""},\n'
    '  "hkid": {"main":"","check":"","full":""},\n'
    '  "sex": "M",\n'
    '  "marital_status": "married",\n'
    '  "date_of_birth": {"iso":"","year":"","month":"","day":""},\n'
    '  "phone_home": {"area_code":"852","number":"","full":""},\n'
    '  "phone_mobile": {"area_code":"852","number":"","full":""},\n'
    '  "email": "",\n'
    '  "address": {"room":"","floor":"","block":"","estate":"","street":"","district":""},\n'
    '  "address_text": "",\n'
    '  "_extraction": {"confidence": 0.0, "notes": "", "missing_fields": []}\n'
    "}"
)


def _mock_extract(text: str) -> dict[str, Any]:
    """無 API key 時的離線範本——回固定例子，方便前端 demo + e2e 測試。"""
    return {
        "elder_id": "EXTRACTED-MOCK01",
        "name_zh": {"full": "李婉芬", "family": "李", "given": "婉芬"},
        "name_en": {"full": "Lee Yuen Fan", "full_upper": "LEE YUEN FAN", "family": "LEE", "given": "YUEN FAN"},
        "hkid": {"main": "B654321", "check": "3", "full": "B654321(3)"},
        "sex": "F",
        "marital_status": "widowed",
        "date_of_birth": {"iso": "1952-08-22", "year": "1952", "month": "08", "day": "22"},
        "phone_home": {"area_code": "852", "number": "23456789", "full": "23456789"},
        "phone_mobile": {"area_code": "852", "number": "61234567", "full": "61234567"},
        "email": "",
        "address": {"room": "5B", "floor": "12", "block": "B 座", "estate": "麗安邨", "street": "蘇屋道", "district": "深水埗"},
        "address_text": "深水埗蘇屋道麗安邨 B 座 12 樓 5B 室",
        "_extraction": {
            "confidence": 0.0,
            "notes": "[mock] 未設 LLM API key；回固定 demo 樣本（李婉芬，深水埗）。",
            "missing_fields": [],
            "source_text_chars": len(text or ""),
        },
    }


def _postprocess(profile: dict[str, Any]) -> dict[str, Any]:
    """補 hkid.full / address_text / phone full 等衍生欄位，確保跟 mapping path 對齊。"""
    # hkid.full
    hk = profile.get("hkid") or {}
    if isinstance(hk, dict):
        main = (hk.get("main") or "").strip()
        chk = (hk.get("check") or "").strip()
        if main and not hk.get("full"):
            hk["full"] = f"{main}({chk})" if chk else main
        profile["hkid"] = hk

    # DOB year/month/day from iso if missing
    dob = profile.get("date_of_birth") or {}
    if isinstance(dob, dict):
        iso = (dob.get("iso") or "").strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
            y, m, d = iso.split("-")
            dob.setdefault("year", y)
            dob.setdefault("month", m)
            dob.setdefault("day", d)
        profile["date_of_birth"] = dob

    # phone full
    for key in ("phone_home", "phone_mobile"):
        ph = profile.get(key) or {}
        if isinstance(ph, dict):
            num = re.sub(r"\D", "", ph.get("number") or "")
            ph["number"] = num
            ph.setdefault("full", num)
            ph.setdefault("area_code", "852")
            profile[key] = ph

    # name_en full_upper
    en = profile.get("name_en") or {}
    if isinstance(en, dict) and en.get("full") and not en.get("full_upper"):
        en["full_upper"] = en["full"].upper()
        profile["name_en"] = en

    # address_text fallback from parts
    if not (profile.get("address_text") or "").strip():
        addr = profile.get("address") or {}
        if isinstance(addr, dict):
            parts = [addr.get(k, "") for k in ("district", "street", "estate", "block", "floor", "room") if addr.get(k)]
            if parts:
                joined = " ".join(p for p in parts if p)
                # 樓 / 室 suffix
                if addr.get("floor") and not str(addr["floor"]).endswith("樓"):
                    joined = joined.replace(addr["floor"], f"{addr['floor']} 樓")
                if addr.get("room"):
                    joined = joined.replace(addr["room"], f"{addr['room']} 室")
                profile["address_text"] = joined
    return profile


def extract_elder_profile_from_text(text: str, source_hint: str | None = None) -> dict[str, Any]:
    """raw text → ElderProfile dict.

    `source_hint`：例如 "社工筆記" / "病人卡" — 加進 prompt 給模型上下文。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text")

    if settings.is_text_mock:
        prof = _mock_extract(text)
        return _postprocess(prof)

    started = time.time()
    client = get_text_client()
    model = resolve_model("text")
    user = (
        f"資料來源：{source_hint or '未指定'}\n"
        f"==== 原始文字 START ====\n{text[:8000]}\n==== 原始文字 END ===="
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM},
                {"role": "user", "content": user},
            ],
            temperature=0.2,
            max_tokens=1500,
        )
        raw = resp.choices[0].message.content or "{}"
        prof = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("extract_elder_profile JSON decode failed: %s", e)
        raise ValueError(f"LLM returned non-JSON: {e}")
    except Exception as e:  # noqa: BLE001
        logger.error("extract_elder_profile LLM error: %s", e)
        raise

    prof.setdefault("_extraction", {})
    prof["_extraction"].setdefault("source_text_chars", len(text))
    prof["_extraction"]["latency_ms"] = int((time.time() - started) * 1000)
    return _postprocess(prof)


# ── v0.4.0-rc3：照片 → ElderProfile（vision LLM）──────────────────────────
def extract_elder_profile_from_image(image_bytes: bytes, ext: str = "jpeg",
                                     source_hint: str | None = None) -> dict[str, Any]:
    """壓縮照片後丟給 vision LLM 抽 ElderProfile。

    用 backend/app/llm/vision.py 的 `_preprocess_image_bytes` 同款壓縮邏輯
    （≤800KB、長邊 ≤1600px、轉 JPEG@85），然後走 client.chat.completions.create
    的 image_url + text 雙 part user message，response_format=json_object。
    """
    import base64 as _b64
    from ..llm.vision import _preprocess_image_bytes

    if not image_bytes:
        raise ValueError("empty image")

    if settings.is_vision_mock:
        prof = _mock_extract(f"[image:{len(image_bytes)}B]")
        prof["_extraction"]["notes"] = (
            "[mock] 未設 OpenAI API key；回固定 demo 樣本（李婉芬）。實際照片內容未讀。"
        )
        prof["_extraction"]["source_kind"] = "image"
        prof["_extraction"]["image_bytes"] = len(image_bytes)
        return _postprocess(prof)

    started = time.time()
    pre_bytes, out_ext = _preprocess_image_bytes(image_bytes, ext.lower().lstrip(".") or "jpeg")
    b64 = _b64.b64encode(pre_bytes).decode("ascii")
    data_url = f"data:image/{out_ext};base64,{b64}"

    client = get_vision_client()
    model = resolve_model("vision")  # gpt-5-mini (rc6)
    user_text = (
        f"資料來源：{source_hint or '照片（可能是病人卡 / 社工筆記 / 身份證掃描 / 表格頁）'}\n\n"
        "請看這張照片，把上面能辨識到的長者個人資料抽取出來。圖中字若潦草請用 '？' 佔位，"
        "但**不要整欄留空**——盡量讀。最終嚴格按 system 中的 JSON schema 輸出。"
    )
    try:
        resp = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": EXTRACT_SYSTEM},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": user_text},
                    ],
                },
            ],
            temperature=0.2,
            max_tokens=1800,
        )
        raw = resp.choices[0].message.content or "{}"
        prof = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("extract_from_image JSON decode failed: %s", e)
        raise ValueError(f"vision LLM returned non-JSON: {e}")
    except Exception as e:  # noqa: BLE001
        logger.error("extract_from_image LLM error: %s", e)
        raise

    prof.setdefault("_extraction", {})
    prof["_extraction"]["source_kind"] = "image"
    prof["_extraction"]["image_bytes_raw"] = len(image_bytes)
    prof["_extraction"]["image_bytes_sent"] = len(pre_bytes)
    prof["_extraction"]["latency_ms"] = int((time.time() - started) * 1000)
    return _postprocess(prof)

