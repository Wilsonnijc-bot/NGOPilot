"""DeepSeek-V4-Pro 文本 helper — v0.4.0-rc6 起改走 DeepSeek 官方 OpenAI 相容 API。

所有文字推理（批次摘要、二次審查、補全）皆透過 `get_text_client()`，
避免再經百煉。
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..config import settings
from .client import get_text_client, resolve_model


# ── 日誌（與 vision.py 同檔，便於統一分析） ────────────────────────────────
_LOG_LOCK = threading.Lock()


def _log_path() -> Path:
    p = Path(__file__).resolve().parents[2] / "logs" / "vision.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _log_event(kind: str, **fields: Any) -> None:
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
            pass


def summarise_batch(records_text: str) -> Optional[str]:
    """讓 DeepSeek 對一個批次給出簡短摘要（總人數、健康關注、需跟進等）。"""
    if settings.is_text_mock:
        return "[mock] 此批次共 5 位長者：3 位獨居，2 位情緒低落、1 位焦慮，4 位需跟進。"

    client = get_text_client()
    model = resolve_model("text")
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是 NGO 行政助理，請用 2-3 句繁體中文概括這批志工探訪紀錄。"},
                {"role": "user", "content": records_text[:8000]},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        return resp.choices[0].message.content
    except Exception:  # noqa: BLE001
        return None


# ─────────────────────────────────────────────────────────────────────────
# v0.3.4：DeepSeek 二次審查 + 自動補全
# ─────────────────────────────────────────────────────────────────────────
REVIEW_SYSTEM = """你是一名嚴謹的 NGO 行政助理，擅長審查 OCR / VLM 抽取出來的志工探訪表資料品質。
你會收到 Qwen Vision 抽取出來的**所有欄位**、信心值，以及一份「**重點關注**」清單（這些是已被本地規則判定為 missing / partial / low_confidence 的欄位）。

任務：對**每一個**欄位都做品質判斷，凡是發現問題就修正；沒問題的不要動。

問題類型：
1. 整欄空白 (missing)：必填欄位卻為空 → 嘗試從其他欄位推斷；推不出 → null。
2. 局部模糊 (partial)：值中含「？？」「〇」「XX」「__」「…」等佔位符。
3. **碎片中文** (fragmented)：值中含「漢字 + 空格 + 漢字」(例如「邀 加中心活」應為「邀請參加中心活動」、「九龍 灣」應為「九龍灣」)。**這類務必修補成通順詞**。
4. 低信心 (low_confidence)：confidence < 0.5。
5. 不合理：例如年齡填了 "1234"、性別填了 "X"、電話格式異常、日期格式錯等。
6. 拼字 / 錯字：明顯的香港繁體錯字。

修補策略：
- 同一筆紀錄中找可推斷線索（例如地址含「邨」「邨」字 → 香港地址；mood 跟 follow_up_needed 應該邏輯一致）。
- 碎片中文 → 補成通順詞語。
- 找不到可靠線索 → 設為 null，**寧缺勿造假**。
- 對於**值是完全合理且通順**的欄位，**不要列入 reviewed**（哪怕它在 flagged_keys 裡）。

回傳格式（JSON）：
{
  "reviewed": {
    "<field_key>": {"value": <新值>, "reason": "<10字內理由>", "confidence": 0.0~1.0}
  }
}
- **只列出你實際改動的欄位**；沒問題的一律不要列。
- 香港繁體中文，日期 YYYY-MM-DD。"""


def review_volunteer_extraction(
    fields: dict[str, Any],
    confidence: dict[str, float],
    suspicious_keys: list[str],
    field_schema: list[dict],
    flagged_keys: list[str] | None = None,
) -> dict[str, Any]:
    """DeepSeek 對 Qwen 抽取做審查 + 補全。**不走視覺**，純文字推理。

    Args:
        fields: Qwen 抽出的欄位字典
        confidence: Qwen 信心字典
        suspicious_keys: 要 DeepSeek 審查的 key 清單（一般是「所有非 meta key」）
        field_schema: VOLUNTEER_FORM_FIELDS
        flagged_keys: 子集 —— 已被本地規則旗標為 missing/partial/low_conf 的 key
                      （prompt 會把這些標為「重點關注」）

    Returns:
        {
          "reviewed": {key: {value, reason, confidence}},
          "_meta": {provider, model, latency_ms, error?}
        }
    """
    started = time.time()
    if not suspicious_keys:
        return {"reviewed": {}, "_meta": {"provider": "noop", "latency_ms": 0}}
    flagged_keys = flagged_keys or []

    if settings.is_text_mock:
        rev: dict[str, dict] = {}
        for k in flagged_keys:
            if k == "elder_address":
                rev[k] = {"value": "九龍深水埗保安道 1 號", "reason": "mock 修補", "confidence": 0.6}
            elif k == "volunteer_name":
                rev[k] = {"value": "志工", "reason": "mock 推測", "confidence": 0.55}
            elif k == "mood":
                rev[k] = {"value": "良好", "reason": "mock 預設", "confidence": 0.5}
        return {"reviewed": rev, "_meta": {"provider": "mock", "latency_ms": int((time.time() - started) * 1000)}}

    schema_md = "\n".join(
        f"- `{f['key']}` ({f['label']}, {f['type']})"
        + (f" 可選: {f.get('options')}" if f.get("options") else "")
        for f in field_schema if f["key"] in suspicious_keys
    )

    user_prompt = (
        f"以下是視覺 LLM（GPT-5-mini）抽取的志工探訪表結果。請審查並補全有問題的欄位。\n\n"
        f"## 欄位 schema（候選審查欄位）\n{schema_md}\n\n"
        f"## 視覺抽取結果（**完整內容**）\n```json\n{json.dumps(fields, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## 視覺信心值\n```json\n{json.dumps(confidence, ensure_ascii=False)}\n```\n\n"
        f"## 重點關注（本地已標記為 missing / partial / low_conf）\n{flagged_keys or '（無）'}\n\n"
        f"## 全部候選審查欄位\n{suspicious_keys}\n\n"
        f"請對**所有**候選欄位做品質判斷，列出**你實際修改**的欄位（只列改的；認可原值的不要列）。\n"
        f"回傳 JSON，格式：\n"
        f"```json\n{{\"reviewed\": {{\"<key>\": {{\"value\": ..., \"reason\": \"...\", \"confidence\": 0.7}}}}}}\n```"
    )

    client = get_text_client()
    model = resolve_model("text")
    _log_event("review_start", model=model, suspicious_keys=suspicious_keys)

    # v0.3.7: 使用 client 預設的 httpx.Timeout（不再用 with_options(timeout=float)，
    # 後者會被 OpenAI SDK 重新包成 single-float → 觸發 per-chunk 解讀，實測 60s → 184s）
    # 並在 timeout 時做 1 次重試
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": REVIEW_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
            reviewed_raw = data.get("reviewed") or {}
            # 規範化結構：value/reason/confidence
            reviewed: dict[str, dict] = {}
            for k, v in reviewed_raw.items():
                if k not in suspicious_keys:
                    continue
                if isinstance(v, dict):
                    reviewed[k] = {
                        "value": v.get("value"),
                        "reason": str(v.get("reason") or "")[:80],
                        "confidence": float(v.get("confidence") or 0.5),
                    }
                else:
                    # 模型只回了值（沒附 reason / confidence）
                    reviewed[k] = {"value": v, "reason": "", "confidence": 0.5}
            latency_ms = int((time.time() - started) * 1000)
            _log_event(
                "review_ok",
                latency_ms=latency_ms,
                reviewed_keys=list(reviewed.keys()),
                raw_len=len(raw),
                attempt=attempt + 1,
            )
            return {
                "reviewed": reviewed,
                "_meta": {"provider": "deepseek_official", "model": model, "latency_ms": latency_ms},
            }
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            latency_ms = int((time.time() - started) * 1000)
            _log_event(
                "review_attempt_fail",
                latency_ms=latency_ms,
                error=str(exc)[:500],
                attempt=attempt + 1,
            )
            # 只 retry timeout / 連線錯誤
            err_class = type(exc).__name__
            if "timeout" not in str(exc).lower() and "Timeout" not in err_class and "Connection" not in err_class:
                break

    latency_ms = int((time.time() - started) * 1000)
    _log_event("review_fail", latency_ms=latency_ms, error=str(last_error)[:500] if last_error else "unknown")
    return {
        "reviewed": {},
        "_meta": {"provider": "deepseek_official", "model": model,
                   "latency_ms": latency_ms, "error": str(last_error) if last_error else "unknown"},
    }
