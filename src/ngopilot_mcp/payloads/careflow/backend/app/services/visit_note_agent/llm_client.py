"""LLM client for visit_note_agent.

Rewritten to use our unified Bailian OpenAI-compatible client
(`app.llm.client.get_client`). Two responsibilities preserved from the
original partner branch implementation:

1. `analyze_template_contract()` — turn a DOCX structural map into a
   `fixed_blocks / dynamic_slots / rules` JSON contract.
2. `generate_slot_content()` — given a transcript + the contract,
   produce a `{slot_id: text}` JSON.

The HTTP / streaming / retries scaffolding from the original
`requests`-based version is dropped because the OpenAI SDK already
handles all of that.
"""
from __future__ import annotations

import json
from pathlib import Path

from ...llm.client import get_text_client, resolve_model
from .errors import VisitNoteAgentError


class LLMConfigError(VisitNoteAgentError):
    pass


class LLMAPIError(VisitNoteAgentError):
    pass


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
PROMPT_FILES_BY_MODE = {
    "home_visit": "systemprompt_for_meetingnote.txt",
    "internal_meeting": "systemprompt_for_internal_meetingnote.txt",
}


def normalize_prompt_mode(mode: str | None = None) -> str:
    mode = (mode or "home_visit").strip()
    if mode not in PROMPT_FILES_BY_MODE:
        raise LLMConfigError(f"Unsupported visit note mode: {mode}")
    return mode


def load_base_system_prompt(mode: str | None = None) -> str:
    return _load_prompt(PROMPT_FILES_BY_MODE[normalize_prompt_mode(mode)])


def load_template_analysis_prompt() -> str:
    return _load_prompt("template_analysis_prompt.txt")


def _load_prompt(filename: str) -> str:
    path = PROMPT_DIR / filename
    if not path.exists():
        raise LLMConfigError(f"Missing prompt file: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise LLMConfigError(f"Prompt file is empty: {path}")
    return text


def analyze_template_contract(structural_map: dict, model: str | None = None) -> dict:
    """Phase A — LLM classifies fixed blocks vs dynamic slots in the template."""
    messages = [
        {"role": "system", "content": load_template_analysis_prompt()},
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    "Analyze this structural_text_map and produce the compact template contract JSON described in the system prompt.",
                    "structural_text_map (compact JSON, no indent):",
                    json.dumps(structural_map, ensure_ascii=False, separators=(",", ":")),
                ]
            ),
        },
    ]
    content = _chat_json(messages, model)
    contract = _loads_json_object(content)
    # v0.4.5: new slim schema returns `fixed_block_ids` (array of IDs) instead of
    # the verbose `fixed_blocks` (array of {block_id,text,role,reason}). Renderer
    # only consumes dynamic_slots, so we accept either form and synthesise the
    # other for backward compat with any downstream consumer.
    if isinstance(contract.get("fixed_block_ids"), list) and "fixed_blocks" not in contract:
        contract["fixed_blocks"] = [{"block_id": bid} for bid in contract["fixed_block_ids"]]
    elif isinstance(contract.get("fixed_blocks"), list) and "fixed_block_ids" not in contract:
        contract["fixed_block_ids"] = [
            b.get("block_id") for b in contract["fixed_blocks"] if b.get("block_id")
        ]
    if not isinstance(contract.get("fixed_blocks"), list):
        raise LLMAPIError("Template contract missing fixed_blocks list")
    if not isinstance(contract.get("dynamic_slots"), list):
        raise LLMAPIError("Template contract missing dynamic_slots list")
    if "rules" not in contract and isinstance(contract.get("rendering_rules"), list):
        contract["rules"] = contract["rendering_rules"]
    if not isinstance(contract.get("rules"), list):
        raise LLMAPIError("Template contract missing rendering_rules list")
    return contract


def generate_slot_content(
    transcript: str,
    template_contract: dict,
    model: str | None = None,
    *,
    mode: str | None = None,
) -> dict:
    """Phase B — fill in the dynamic_slots using the transcript."""
    slot_ids = [
        s.get("slot_id")
        for s in template_contract.get("dynamic_slots", [])
        if s.get("slot_id")
    ]
    messages = [
        {
            "role": "system",
            "content": "\n".join(
                [
                    load_base_system_prompt(mode),
                    "Return valid JSON only. No markdown, no explanation, no headings, no layout.",
                    "Only generate values for these slot_ids: " + ", ".join(slot_ids),
                    "Use pure Hong Kong Cantonese / Traditional Chinese. "
                    "Use only transcript content. Missing information must be 「未有明確提及」.",
                ]
            ),
        },
        {
            "role": "user",
            "content": "\n\n".join(
                [
                    "template_contract.json (compact):",
                    json.dumps(template_contract, ensure_ascii=False, separators=(",", ":")),
                    "transcript:",
                    transcript,
                ]
            ),
        },
    ]
    content = _chat_json(messages, model)
    data = _loads_json_object(content)
    missing = [sid for sid in slot_ids if sid not in data]
    if missing:
        raise LLMAPIError(f"Generated slot content missing slot_id: {missing[0]}")
    extra = [k for k in data if k not in slot_ids]
    if extra:
        raise LLMAPIError(f"Generated slot content contains unknown slot_id: {extra[0]}")
    return data


def _chat_json(messages: list[dict], model: str | None) -> str:
    """Single chat-completion call using the DeepSeek-official text client.

    v0.4.4: switched to **streaming mode**. DeepSeek-v4-pro is a reasoning model
    that can take 5-10 minutes on heavy structural prompts. In non-streaming
    mode the server actively closes idle TCP connections at ~60s, surfacing as
    ``APIConnectionError: Connection error``. Streaming keeps the connection
    alive via chunked SSE data, so long reasoning completes successfully.

    v0.4.3 outer retry loop preserved for genuine transient network blips
    (DNS / TLS handshake failures during peak hours).
    """
    import time
    try:
        from openai import APIConnectionError, APITimeoutError
    except ImportError:  # pragma: no cover
        APIConnectionError = APITimeoutError = Exception  # type: ignore

    client = get_text_client()
    selected = model or resolve_model("text")
    last_exc: Exception | None = None
    content = ""
    for attempt in range(3):
        try:
            stream = client.chat.completions.create(
                model=selected,
                messages=messages,
                temperature=0.1,
                response_format={"type": "json_object"},
                stream=True,
            )
            parts: list[str] = []
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    parts.append(delta)
            content = "".join(parts).strip()
            break
        except (APIConnectionError, APITimeoutError) as exc:  # transient network
            last_exc = exc
            if attempt == 2:
                raise LLMAPIError(f"LLM API call failed after 3 retries: {exc}") from exc
            time.sleep(2 ** attempt)  # 1s, 2s, 4s
        except Exception as exc:  # noqa: BLE001
            raise LLMAPIError(f"LLM API call failed: {exc}") from exc
    else:  # pragma: no cover
        raise LLMAPIError(f"LLM API call failed: {last_exc}")
    if not content:
        raise LLMAPIError("LLM API returned empty content")
    return content


def _loads_json_object(content: str) -> dict:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMAPIError("LLM response was not valid JSON") from exc
    if not isinstance(data, dict):
        raise LLMAPIError("LLM response JSON must be an object")
    return data
