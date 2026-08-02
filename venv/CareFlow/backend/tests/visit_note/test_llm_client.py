import pytest

from app.services.visit_note_agent.llm_client import (
    LLMAPIError,
    LLMConfigError,
    _loads_json_object,
    generate_slot_content,
    load_base_system_prompt,
    load_template_analysis_prompt,
    normalize_prompt_mode,
)


def test_loads_prompts_from_packaged_prompt_dir():
    assert load_base_system_prompt("home_visit")
    assert load_base_system_prompt("internal_meeting")
    assert load_template_analysis_prompt()


def test_rejects_unknown_prompt_mode():
    with pytest.raises(LLMConfigError):
        normalize_prompt_mode("legacy_google_stt")


def test_rejects_invalid_json_response():
    with pytest.raises(LLMAPIError):
        _loads_json_object("not json")


def test_generate_slot_content_validates_missing_slot(monkeypatch):
    monkeypatch.setattr(
        "app.services.visit_note_agent.llm_client._chat_json",
        lambda messages, model: '{"summary":"胃口一般"}',
    )

    with pytest.raises(LLMAPIError) as exc:
        generate_slot_content(
            "受訪者話胃口一般。",
            {
                "dynamic_slots": [
                    {"slot_id": "summary", "source_block_id": "p_001"},
                    {"slot_id": "follow_up", "source_block_id": "p_002"},
                ]
            },
        )

    assert "follow_up" in str(exc.value)
