import subprocess

import pytest

from app.services.visit_note_agent.errors import VisitNoteAgentError
from app.services.visit_note_agent.template_normalizer import normalize_template_to_docx


def test_docx_template_is_copied_to_working_dir(tmp_path):
    template = tmp_path / "example.docx"
    working_dir = tmp_path / "work"
    template.write_bytes(b"docx bytes")

    normalized = normalize_template_to_docx(str(template), str(working_dir))

    assert normalized == str(working_dir / "normalized_template.docx")
    assert (working_dir / "normalized_template.docx").read_bytes() == b"docx bytes"
    assert template.read_bytes() == b"docx bytes"


def test_doc_template_is_converted_to_docx_with_textutil(tmp_path, monkeypatch):
    template = tmp_path / "example.doc"
    working_dir = tmp_path / "work"
    template.write_bytes(b"doc bytes")
    calls = {}

    monkeypatch.setattr("app.services.visit_note_agent.template_normalizer.shutil.which", lambda name: "/usr/bin/textutil")

    def fake_run(command, check, capture_output, text):
        calls["command"] = command
        output_path = command[command.index("-output") + 1]
        with open(output_path, "wb") as handle:
            handle.write(b"converted docx")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("app.services.visit_note_agent.template_normalizer.subprocess.run", fake_run)

    normalized = normalize_template_to_docx(str(template), str(working_dir))

    assert normalized == str(working_dir / "normalized_template.docx")
    assert calls["command"][:3] == ["textutil", "-convert", "docx"]
    assert (working_dir / "normalized_template.docx").read_bytes() == b"converted docx"


def test_doc_conversion_failure_has_clear_error(tmp_path, monkeypatch):
    template = tmp_path / "example.doc"
    template.write_bytes(b"doc bytes")
    monkeypatch.setattr("app.services.visit_note_agent.template_normalizer.shutil.which", lambda name: None)

    with pytest.raises(VisitNoteAgentError) as exc:
        normalize_template_to_docx(str(template), str(tmp_path / "work"))

    assert str(exc.value) == "Failed to convert .doc template to .docx. Please provide a .docx template."


def test_pdf_template_is_rejected_without_conversion(tmp_path):
    template = tmp_path / "example.pdf"
    template.write_bytes(b"%PDF")

    with pytest.raises(VisitNoteAgentError) as exc:
        normalize_template_to_docx(str(template), str(tmp_path / "work"))

    assert str(exc.value) == (
        "PDF templates are no longer supported. Please provide a .docx or .doc template."
    )


def test_unknown_template_type_is_rejected(tmp_path):
    template = tmp_path / "example.txt"
    template.write_text("hello", encoding="utf-8")

    with pytest.raises(VisitNoteAgentError) as exc:
        normalize_template_to_docx(str(template), str(tmp_path / "work"))

    assert str(exc.value) == "Unsupported template type. Please provide a .docx or .doc template."
