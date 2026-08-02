import pytest

from app.services.visit_note_agent import transcriber
from app.services.visit_note_agent.transcriber import TranscriptionError


def test_transcribe_audio_rejects_missing_file(tmp_path):
    with pytest.raises(TranscriptionError) as exc:
        transcriber.transcribe_audio(str(tmp_path / "missing.mp3"))

    assert "Audio file not found" in str(exc.value)


def test_transcribe_audio_rejects_unsupported_extension(tmp_path):
    audio = tmp_path / "visit.txt"
    audio.write_text("not audio", encoding="utf-8")

    with pytest.raises(TranscriptionError) as exc:
        transcriber.transcribe_audio(str(audio))

    assert "Unsupported audio type" in str(exc.value)


def test_parse_dashscope_transcription_payload_prefers_transcripts_text():
    payload = {
        "transcripts": [
            {"text": "第一段"},
            {"sentences": [{"text": "第二段"}, {"text": "第三段"}]},
        ]
    }

    assert transcriber._extract_text_from_transcription(payload) == "第一段\n第二段\n第三段"
