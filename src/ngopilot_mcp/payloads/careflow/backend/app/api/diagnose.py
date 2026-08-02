"""AI 連線自檢 endpoint — v0.4.0-rc6 三路獨立架構。

前端「AI 連線自檢」面板會打 GET /api/llm/diagnose，回傳每一路的 provider /
model / base_url / 是否有 key / 探活結果 / 延遲。三路完全獨立呈現。
"""
from __future__ import annotations

import socket
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter

from ..config import settings
from ..llm.client import get_asr_client, get_text_client, get_vision_client, resolve_model

router = APIRouter(prefix="/api/llm", tags=["diagnose"])


def _dns_check(base_url: str) -> dict[str, Any]:
    """純 DNS / TCP 握手。"""
    parsed = urlparse(base_url or "")
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        return {"ok": False, "host": "", "error": "no host"}
    started = time.time()
    try:
        socket.setdefaulttimeout(5.0)
        ip = socket.gethostbyname(host)
        with socket.create_connection((host, port), timeout=5.0):
            pass
        return {"ok": True, "host": host, "port": port, "ip": ip,
                "latency_ms": int((time.time() - started) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "host": host, "port": port,
                "error": str(exc)[:300],
                "latency_ms": int((time.time() - started) * 1000)}


# ── 三路探活 ───────────────────────────────────────────────────────────

def _probe_text() -> dict[str, Any]:
    model = resolve_model("text")
    base_url = settings.deepseek_base_url
    has_key = bool(settings.deepseek_api_key)
    info = {"provider": "deepseek_official", "model": model, "base_url": base_url,
            "has_key": has_key, "network": _dns_check(base_url)}
    if not has_key:
        info.update({"ok": True, "mock": True, "reply": "[mock] no DEEPSEEK_API_KEY"})
        return info
    started = time.time()
    try:
        client = get_text_client()
        resp = client.with_options(timeout=10.0).chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是測試 echo。"},
                {"role": "user", "content": "請回覆 'pong'。"},
            ],
            temperature=0,
            max_tokens=10,
        )
        info.update({"ok": True, "mock": False,
                     "reply": (resp.choices[0].message.content or "").strip()[:80],
                     "latency_ms": int((time.time() - started) * 1000)})
    except Exception as exc:  # noqa: BLE001
        info.update({"ok": False, "mock": False, "error": str(exc)[:500],
                     "latency_ms": int((time.time() - started) * 1000)})
    return info


def _probe_vision() -> dict[str, Any]:
    model = resolve_model("vision")
    base_url = settings.azure_openai_endpoint or "(azure endpoint missing)"
    has_key = bool(settings.azure_openai_api_key and settings.azure_openai_endpoint)
    info = {"provider": "azure_openai", "model": model,
            "deployment": settings.azure_openai_deployment,
            "api_version": settings.azure_openai_api_version,
            "base_url": base_url,
            "has_key": has_key, "network": _dns_check(base_url)}
    if not has_key:
        info.update({"ok": True, "mock": True,
                     "reply": "[mock] no AZURE_OPENAI_API_KEY / ENDPOINT"})
        return info
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAIAAACQkWg2AAAA"
        "FElEQVR4nGP4TyJgGNUwqmH4agAAr639H708R/EAAAAASUVORK5CYII="
    )
    started = time.time()
    try:
        client = get_vision_client()
        resp = client.with_options(timeout=15.0).chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{tiny_png_b64}"}},
                    {"type": "text", "text": "請回覆 'ok'。"},
                ],
            }],
            temperature=0,
            max_tokens=200,
        )
        info.update({"ok": True, "mock": False,
                     "reply": (resp.choices[0].message.content or "").strip()[:80],
                     "latency_ms": int((time.time() - started) * 1000)})
    except Exception as exc:  # noqa: BLE001
        info.update({"ok": False, "mock": False, "error": str(exc)[:500],
                     "latency_ms": int((time.time() - started) * 1000)})
    return info


def _probe_asr() -> dict[str, Any]:
    """ASR 探活 — 只檢查 DNS / key 存在；不真打 fun-asr 避免上傳大檔。"""
    model = resolve_model("asr")
    base_url = settings.dashscope_base_url
    has_key = bool(settings.dashscope_api_key)
    info = {"provider": "bailian", "model": model, "base_url": base_url,
            "has_key": has_key, "network": _dns_check(base_url)}
    if not has_key:
        info.update({"ok": True, "mock": True, "reply": "[mock] no DASHSCOPE_API_KEY"})
    else:
        # 不發送真的音訊；以「key 存在 + DNS 通」即視為 ok
        info.update({"ok": info["network"].get("ok", False), "mock": False,
                     "reply": "(DNS check only; ASR upload skipped)"})
    return info


@router.get("/diagnose")
def diagnose() -> dict[str, Any]:
    started = time.time()
    text = _probe_text()
    vision = _probe_vision()
    asr = _probe_asr()
    return {
        "ts": time.time(),
        # legacy 相容欄位
        "is_mock_mode": settings.is_mock_mode,
        "provider": "(rc6: 3-channel)",
        # rc6 主結構：三路獨立
        "channels": {"text": text, "vision": vision, "asr": asr},
        # legacy alias（保留前端舊欄位）
        "text": text,
        "vision": vision,
        "asr": asr,
        "total_ms": int((time.time() - started) * 1000),
    }
