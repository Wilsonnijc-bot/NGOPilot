"""visit_note_agent — 家訪語音轉結構化報告 sub-package.

Originally authored by partner branch (`branch/CareFlow/visit_note_agent/`).
Adapted to:
  - Unified Bailian OpenAI-compatible client (no requests / OpenRouter direct).
  - Bailian fun-asr instead of Google Cloud Speech-to-Text.
  - Two-phase flow (extract → human review → render) to satisfy the
    CareFlow mandatory-review rule.
  - Encrypted transcript vault (no plaintext on disk).
"""
from __future__ import annotations

from . import mock as _mock
from .service import generate_visit_case_note, run_extraction, run_render
from ...config import settings


def _install_mock_patch() -> None:
    """When in mock mode patch llm_client to short-circuit network calls."""
    if settings.dashscope_api_key:
        return
    from . import llm_client

    llm_client.analyze_template_contract = (  # type: ignore[assignment]
        lambda structural_map, model=None: _mock.mock_template_contract(structural_map)
    )
    llm_client.generate_slot_content = (  # type: ignore[assignment]
        lambda transcript, contract, model=None, mode=None: _mock.mock_slot_content(transcript, contract)
    )


_install_mock_patch()

__all__ = ["generate_visit_case_note", "run_extraction", "run_render"]
