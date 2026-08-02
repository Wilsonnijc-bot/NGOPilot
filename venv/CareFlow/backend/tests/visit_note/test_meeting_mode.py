import importlib

from app.services.visit_note_agent import llm_client, service


def test_base_system_prompt_defaults_to_home_visit_and_can_load_internal_meeting(
    tmp_path, monkeypatch
):
    (tmp_path / "systemprompt_for_meetingnote.txt").write_text(
        "HOME VISIT PROMPT", encoding="utf-8"
    )
    (tmp_path / "systemprompt_for_internal_meetingnote.txt").write_text(
        "INTERNAL MEETING PROMPT", encoding="utf-8"
    )
    monkeypatch.setattr(llm_client, "PROMPT_DIR", tmp_path)

    assert llm_client.load_base_system_prompt() == "HOME VISIT PROMPT"
    assert llm_client.load_base_system_prompt("internal_meeting") == "INTERNAL MEETING PROMPT"


def test_generate_slot_content_uses_internal_meeting_prompt(tmp_path, monkeypatch):
    importlib.reload(llm_client)
    captured = {}
    (tmp_path / "systemprompt_for_meetingnote.txt").write_text(
        "HOME VISIT PROMPT", encoding="utf-8"
    )
    (tmp_path / "systemprompt_for_internal_meetingnote.txt").write_text(
        "INTERNAL MEETING PROMPT", encoding="utf-8"
    )
    monkeypatch.setattr(llm_client, "PROMPT_DIR", tmp_path)

    def fake_chat_json(messages, model):
        captured["messages"] = messages
        return '{"summary":"會議重點"}'

    monkeypatch.setattr(llm_client, "_chat_json", fake_chat_json)

    content = llm_client.generate_slot_content(
        "團隊討論下月服務安排。",
        {"dynamic_slots": [{"slot_id": "summary", "source_block_id": "p_002"}]},
        mode="internal_meeting",
    )

    assert content == {"summary": "會議重點"}
    assert captured["messages"][0]["content"].startswith("INTERNAL MEETING PROMPT")


def test_run_extraction_forwards_internal_meeting_mode_to_slot_generation(
    tmp_path, monkeypatch
):
    audio = tmp_path / "meeting.mp3"
    template = tmp_path / "template.docx"
    audio.write_bytes(b"audio")
    template.write_bytes(b"template")
    captured = {}

    monkeypatch.setattr(service, "_validate_input_files", lambda audio, template: None)
    monkeypatch.setattr(service, "_validate_supported_template_type", lambda template: None)
    monkeypatch.setattr(service, "transcribe_audio", lambda path: "逐字稿")
    monkeypatch.setattr(
        service,
        "_prepare_template_contract",
        lambda template_path, temp_dir, model: (
            str(tmp_path / "work" / "normalized_template.docx"),
            {"blocks": []},
            {"dynamic_slots": [{"slot_id": "summary"}]},
        ),
    )

    def fake_generate_slot_content(transcript, template_contract, model=None, mode="home_visit"):
        captured["mode"] = mode
        return {"summary": "會議摘要"}

    monkeypatch.setattr(service.llm_client, "generate_slot_content", fake_generate_slot_content)

    result = service.run_extraction(
        str(audio),
        str(template),
        str(tmp_path / "work"),
        mode="internal_meeting",
    )

    assert result["slot_content"] == {"summary": "會議摘要"}
    assert captured["mode"] == "internal_meeting"
