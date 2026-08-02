"""v0.4.0-beta：elder profile → template fields 對映。

預設走 direct mapping（直接走 `elder_profile_path` 取值），
找不到時可選擇性呼叫 DeepSeek 推測（`use_llm=True`）。

回傳 per-field：
  {
    "key": "...",
    "value": "...",
    "source": "direct" | "default" | "llm" | "missing",
    "confidence": 0.0~1.0,
    "reason"?: str,
    "elder_profile_path": "..."
  }
"""
from __future__ import annotations
import json
import logging
import time
from typing import Any

from ..config import settings
from ..llm import client as llm_client_mod

logger = logging.getLogger(__name__)


def _resolve_path(elder: dict[str, Any], path: str | None) -> Any:
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


def _stringify(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (str, int, float)):
        return str(v)
    return json.dumps(v, ensure_ascii=False)


def _direct_map_one(elder: dict, field: dict) -> dict:
    path = field.get("elder_profile_path")
    raw = _resolve_path(elder, path)
    if raw not in (None, ""):
        return {
            "key": field["key"],
            "label_zh": field.get("label_zh"),
            "value": _stringify(raw),
            "source": "direct",
            "confidence": 1.0,
            "elder_profile_path": path,
        }
    default = field.get("default", "")
    if default:
        return {
            "key": field["key"],
            "label_zh": field.get("label_zh"),
            "value": str(default),
            "source": "default",
            "confidence": 0.9,
            "elder_profile_path": path,
        }
    return {
        "key": field["key"],
        "label_zh": field.get("label_zh"),
        "value": "",
        "source": "missing",
        "confidence": 0.0,
        "elder_profile_path": path,
    }


# ─── 選用：LLM 補空白欄位 ────────────────────────────────────────────────
LLM_SYSTEM = (
    "你是香港 NGO 社工助理，協助把長者個人資料對應到政府福利表格欄位。\n"
    "給你一份 elder profile JSON + 一張表格的某些欄位（這些欄位沒辦法用直接路徑取值），"
    "請從整個 elder profile 推測合理值。\n"
    "規則：\n"
    "1. 香港繁體中文，姓名英文用大寫。\n"
    "2. 找不到 / 無法合理推測 → value=null。\n"
    "3. 不要編造（例如不在 profile 中的證件號）。\n"
    "4. 回 JSON：{\"fields\": {\"<key>\": {\"value\": ..., \"reason\": \"<10字內理由>\", \"confidence\": 0.5~0.9}}}"
)


def _llm_fill_missing(elder: dict, missing_fields: list[dict]) -> dict[str, dict]:
    """對 missing 欄位呼叫 DeepSeek 推測；mock mode 直接回空。"""
    if not missing_fields:
        return {}
    if settings.is_text_mock:
        return {
            f["key"]: {"value": None, "reason": "[mock] 跳過 LLM", "confidence": 0.0}
            for f in missing_fields
        }

    profile_blob = json.dumps(elder, ensure_ascii=False, indent=2)
    fields_md = "\n".join(
        f"- `{f['key']}` ({f.get('label_zh')}, type={f.get('type')}) elder_profile_path={f.get('elder_profile_path')}"
        for f in missing_fields
    )
    user_prompt = (
        f"## Elder Profile\n```json\n{profile_blob}\n```\n\n"
        f"## 待推測欄位\n{fields_md}\n\n"
        f"請對每個欄位給出 value / reason / confidence。"
    )

    try:
        client = llm_client_mod.get_text_client()
        model = llm_client_mod.resolve_model("text")
        t0 = time.time()
        resp = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": LLM_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        latency_ms = int((time.time() - t0) * 1000)
        data = json.loads(resp.choices[0].message.content or "{}")
        out: dict[str, dict] = {}
        for k, v in (data.get("fields") or {}).items():
            if isinstance(v, dict):
                out[k] = {
                    "value": v.get("value"),
                    "reason": str(v.get("reason") or "")[:80],
                    "confidence": float(v.get("confidence") or 0.5),
                }
        logger.info("welfare_mapping llm_fill: %d→%d in %dms", len(missing_fields), len(out), latency_ms)
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("welfare_mapping llm_fill failed: %s", e)
        return {}


# ─── 主入口 ──────────────────────────────────────────────────────────────
def map_elder_to_template(
    template: dict,
    elder: dict,
    use_llm: bool = False,
) -> dict[str, Any]:
    """每欄回 {value, source, confidence, reason?}；source ∈ direct/default/llm/missing。"""
    mappings: list[dict] = []
    missing_fields: list[dict] = []

    for f in template.get("fields", []):
        # checkbox / radio_group 不適用 direct stringify（看的是值是否等於某條件）
        ftype = f.get("type", "text")
        if ftype in ("checkbox", "radio_group"):
            raw = _resolve_path(elder, f.get("elder_profile_path"))
            mappings.append({
                "key": f["key"],
                "label_zh": f.get("label_zh"),
                "value": _stringify(raw),
                "source": "direct" if raw not in (None, "") else "missing",
                "confidence": 1.0 if raw not in (None, "") else 0.0,
                "elder_profile_path": f.get("elder_profile_path"),
                "type": ftype,
            })
            if raw in (None, ""):
                missing_fields.append(f)
            continue

        m = _direct_map_one(elder, f)
        m["type"] = ftype
        mappings.append(m)
        if m["source"] == "missing":
            missing_fields.append(f)

    if use_llm and missing_fields:
        llm_res = _llm_fill_missing(elder, missing_fields)
        idx = {m["key"]: m for m in mappings}
        for k, v in llm_res.items():
            if k not in idx:
                continue
            if v.get("value") in (None, ""):
                continue
            idx[k]["value"] = _stringify(v["value"])
            idx[k]["source"] = "llm"
            idx[k]["confidence"] = v.get("confidence", 0.5)
            idx[k]["reason"] = v.get("reason", "")

    summary = {
        "total": len(mappings),
        "direct": sum(1 for m in mappings if m["source"] == "direct"),
        "default": sum(1 for m in mappings if m["source"] == "default"),
        "llm": sum(1 for m in mappings if m["source"] == "llm"),
        "missing": sum(1 for m in mappings if m["source"] == "missing"),
    }
    return {"mappings": mappings, "summary": summary, "used_llm": use_llm}
