"""LLM client factory — v0.4.0-rc6.2 三路獨立架構。

三個 OpenAI-相容 client，各自綁定獨立的供應商，互不干擾：

    get_text_client()    → DeepSeek 官方 (OpenAI SDK)              · model deepseek-v4-pro
    get_vision_client()  → Azure AI Foundry (azure-ai-inference)  · deployment careflow-gpt-5-mini
    get_asr_client()     → Bailian / DashScope (OpenAI SDK)        · model fun-asr

任一路缺 key 即各自退回 mock，不影響其餘兩路。

rc6.2 變更：視覺從 OpenAI 官方 → Azure AI Foundry（`*.services.ai.azure.com`），
使用 Microsoft 官方 `azure-ai-inference` SDK；為了不改 vision.py / diagnose.py 的
`client.chat.completions.create(...)` 寫法，本檔提供一個薄 wrapper。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal, Optional, Union

import httpx
from openai import OpenAI

from ..config import settings


def _make_client(api_key: str, base_url: str, read_timeout: float = 60.0, max_retries: int = 4) -> OpenAI:
    """Build an OpenAI-compat client with sensible per-channel timeouts."""
    timeout = httpx.Timeout(
        connect=15.0,
        read=read_timeout,
        write=60.0,
        pool=10.0,
    )
    return OpenAI(
        api_key=api_key or "EMPTY",
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )


# ── Azure AI Foundry wrapper（rc6.2） ─────────────────────────────────

class _FoundryCompletions:
    def __init__(self, inner, default_model: str):
        self._inner = inner
        self._default_model = default_model

    def create(self, *, model: Optional[str] = None, messages, **kwargs) -> Any:
        # 過濾掉 azure-ai-inference 不認得的 OpenAI 參數
        allowed = {
            "temperature", "top_p", "max_tokens", "stop",
            "presence_penalty", "frequency_penalty", "seed",
            "tool_choice", "tools", "response_format",
            # v0.4.6-foundry-reasoning: reasoning model 必須能透傳這兩個
            "max_completion_tokens", "extra_body",
        }
        kw = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        # gpt-5-mini 不支援 `temperature` 非預設值（只接受 1）；直接丟棄以走預設
        kw.pop("temperature", None)
        # Azure AI Foundry 的 gpt-4o-mini / gpt-5-mini deployment 不支援
        # `response_format`（會回 "Unsupported response_format ..."）。一律丟棄；
        # caller 必須在 system prompt 內強制 JSON + 用 loose parser 容錯。
        kw.pop("response_format", None)
        # gpt-5-mini / gpt-5.1 等新模型不接受 `max_tokens`，需改為 `max_completion_tokens`
        # 透過 azure-ai-inference 的 `model_extras` 把欄位塞進 HTTP body。
        # v0.4.6-foundry-reasoning：caller 也可以直接傳 `max_completion_tokens`
        # 與 `extra_body`（如 `reasoning_effort`），一律經 `model_extras` 透傳；
        # 過去版本白名單漏這兩項 → reasoning 階段無預算上限 → Foundry 等不到 reply 就 RST。
        extras: dict[str, Any] = {}
        if "max_tokens" in kw:
            extras["max_completion_tokens"] = kw.pop("max_tokens")
        if "max_completion_tokens" in kw:
            extras["max_completion_tokens"] = kw.pop("max_completion_tokens")
        if "extra_body" in kw:
            eb = kw.pop("extra_body") or {}
            if isinstance(eb, dict):
                extras.update(eb)
        if extras:
            kw["model_extras"] = extras
        return self._inner.complete(
            messages=messages,
            model=model or self._default_model,
            **kw,
        )


class _FoundryChat:
    def __init__(self, inner, default_model: str):
        self.completions = _FoundryCompletions(inner, default_model)


class _FoundryWrapper:
    """OpenAI-compat shim 包裝 azure-ai-inference ChatCompletionsClient。

    暴露 `.chat.completions.create(...)` 與 `.with_options(...)`，使既有
    `vision.py` / `diagnose.py` 的 call site 不必改。
    """

    def __init__(self, endpoint: str, api_key: str, deployment: str):
        from azure.ai.inference import ChatCompletionsClient
        from azure.core.credentials import AzureKeyCredential

        # 容錯：使用者可能貼 Responses API 或舊 /models 路徑的完整 URL，
        # 先剝掉 query string 與已知尾段，再依 host 推斷正確路徑。
        ep = endpoint.split("?")[0].rstrip("/")
        for suffix in (
            "/openai/responses", "/openai/deployments", "/openai",
            "/models", "/chat/completions",
        ):
            if ep.endswith(suffix):
                ep = ep[: -len(suffix)].rstrip("/")
                break
        # Azure AI Foundry 新版「projects」endpoint
        # (https://<resource>.services.ai.azure.com/api/projects/<project>)
        # 在 /api/projects/... 路徑下並不支援 azure-ai-inference 的 /models call；
        # 必須降到 resource root 再加 /models。
        if "/api/projects/" in ep:
            ep = ep.split("/api/projects/", 1)[0].rstrip("/")
        host = ep.lower()
        if "cognitiveservices.azure.com" in host or "openai.azure.com" in host:
            # Azure OpenAI 路徑：/openai/deployments/<deployment>
            ep = f"{ep}/openai/deployments/{deployment}"
            default_api_version = "2024-12-01-preview"
            # 允許 .env 覆寫（新 deployment 如 gpt-5.1 需 2025-11-13）。
            api_version = (settings.azure_openai_api_version or default_api_version).strip() or default_api_version
        else:
            # Azure AI Foundry：/models — 此路徑只接受 2024-05-01-preview；
            # 新版 api_version（2024-12-01-preview / 2025-11-13）會回 404。
            # 故強制覆寫，無視 .env 設定。
            ep = f"{ep}/models"
            api_version = "2024-05-01-preview"
        self._inner = ChatCompletionsClient(
            endpoint=ep,
            credential=AzureKeyCredential(api_key),
            api_version=api_version,
            # v0.4.6-foundry-reasoning: gpt-5.1 reasoning + 32k completion tokens
            # 在複雜全頁 PDF 上常超過 5 分鐘；舊預設 read_response_timeout=300s 會在
            # 還沒收到 reply 就 RST，使用者前端看到 RemoteDisconnected。拉到 900s。
            connection_timeout=30,
            read_response_timeout=900,
        )
        self._deployment = deployment
        self._endpoint = ep

    @property
    def chat(self):
        return _FoundryChat(self._inner, self._deployment)

    def with_options(self, **_):
        return self


# ── 三路專用 client（rc6.2 主介面） ───────────────────────────────────

@lru_cache(maxsize=1)
def get_text_client() -> OpenAI:
    """DeepSeek 官方 · OpenAI 相容介面。

    v0.4.4: read_timeout 提升到 900s，配合 streaming 模式應對 deepseek-v4-pro
    推理模型長思考時長（實測 7+ 分鐘）。非串流模式下 DeepSeek 伺服器會在 60s
    主動丟連線（Connection error），故 caller 必須用 ``stream=True``。
    """
    return _make_client(
        settings.deepseek_api_key,
        settings.deepseek_base_url,
        read_timeout=900.0,
        max_retries=0,
    )


@lru_cache(maxsize=1)
def get_vision_client() -> Union[_FoundryWrapper, OpenAI]:
    """Azure 視覺路徑（rc6.6 起：gpt-4.1-mini @ Azure OpenAI v1 surface）。

    新一代 Azure OpenAI `/openai/v1` 端點直接相容 OpenAI SDK，所以走標準
    `OpenAI(base_url=..., api_key=...)`；不需 Foundry wrapper、不需 api-version、
    不需 pop temperature/response_format。

    舊 Foundry endpoint（`*.services.ai.azure.com/models`）仍用 `_FoundryWrapper`。
    若 key/endpoint 缺，回傳 dummy（caller 先檢 `settings.is_vision_mock`）。
    """
    ep = (settings.azure_openai_endpoint or "").strip().rstrip("/")
    key = settings.azure_openai_api_key
    deployment = settings.azure_openai_deployment or settings.azure_openai_model
    if not (key and ep):
        return OpenAI(api_key="EMPTY", base_url="https://api.openai.com/v1")
    # 偵測 OpenAI-相容 v1 surface（路徑結尾為 /openai/v1）
    if ep.endswith("/openai/v1"):
        timeout = httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=10.0)
        return OpenAI(api_key=key, base_url=ep, timeout=timeout)
    # 退回舊 Foundry / Azure OpenAI cognitiveservices endpoint
    return _FoundryWrapper(endpoint=ep, api_key=key, deployment=deployment)


@lru_cache(maxsize=1)
def get_asr_client() -> OpenAI:
    """Bailian DashScope · fun-asr 語音路徑。"""
    return _make_client(
        settings.dashscope_api_key,
        settings.dashscope_base_url,
        read_timeout=120.0,  # ASR 上傳大檔
    )


# ── Legacy shim（保留給尚未遷移的 caller） ────────────────────────────

@lru_cache(maxsize=4)
def get_client(provider: Optional[str] = None) -> OpenAI:
    """⚠ Deprecated — 請改用 get_text_client / get_vision_client / get_asr_client。

    為了不立即 break 任何 caller，仍接受字串 provider 參數並做轉派：
    - None / "auto" / "deepseek_official" / "bailian"(text) → text client
    - "bailian"(asr) 不容易判斷 → 預設轉文字；ASR caller 必須改用 get_asr_client
    """
    # 無 provider 或自動 → 文字（DeepSeek）作為預設
    return get_text_client()


# ── 模型 resolver ─────────────────────────────────────────────────────

ModelKind = Literal["text", "vision", "asr"]


def resolve_model(kind: ModelKind) -> str:
    if kind == "text":
        return settings.deepseek_text_model
    if kind == "vision":
        # Azure 的 chat.completions.create() 接受的是 deployment name
        return settings.azure_openai_deployment or settings.azure_openai_model
    if kind == "asr":
        return settings.bailian_asr_model
    raise ValueError(f"Unknown model kind: {kind}")
