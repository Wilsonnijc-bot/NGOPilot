from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ngopilot_mcp.tools.careflow_government_forms import native_adapter

SUMMARY = {
    "id": "oala",
    "display_name": "OALA",
    "fill_strategy": "coord_anchor",
    "pdf_pages": 1,
    "field_count": 1,
    "status": "ready",
}


class Extractor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def extract_elder_profile_from_text(
        self, text: str, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append(("text", {"text": text, **kwargs}))
        return {"elder_id": "E-1", "name_zh": {"full": "李女士"}}

    def extract_elder_profile_from_image(
        self,
        image_bytes: bytes,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append(("image", {"image_bytes": image_bytes, **kwargs}))
        return {"elder_id": "E-2"}


class Mapper:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def map_elder_to_template(
        self,
        template: dict[str, Any],
        elder: dict[str, Any],
        *,
        use_llm: bool,
    ) -> dict[str, Any]:
        self.calls.append({"template": template, "elder": elder, "use_llm": use_llm})
        return {
            "mappings": [
                {
                    "key": "name",
                    "label_zh": "姓名",
                    "value": "李女士",
                    "source": "direct",
                    "confidence": 1.0,
                }
            ],
            "summary": {"total": 1, "direct": 1, "missing": 0},
            "used_llm": use_llm,
        }


def _start_dependencies() -> tuple[dict[str, Any], Extractor, Mapper]:
    extractor = Extractor()
    mapper = Mapper()
    template = {"id": "oala", "fields": [{"key": "name"}]}
    dependencies = {
        "extractor": extractor,
        "mapper": mapper,
        "load_template": lambda template_id: template,
    }
    return dependencies, extractor, mapper


def test_text_start_calls_native_extractor_then_mapper(monkeypatch: Any) -> None:
    dependencies, extractor, mapper = _start_dependencies()
    monkeypatch.setattr(native_adapter, "_ready_template", lambda *args: SUMMARY)

    response = native_adapter._start(
        dependencies,
        {
            "template_id": "oala",
            "use_llm": True,
            "source_hint": "social worker note",
            "source": {"kind": "text", "text": "source text"},
        },
    )

    assert extractor.calls == [
        (
            "text",
            {"text": "source text", "source_hint": "social worker note"},
        )
    ]
    assert mapper.calls[0]["use_llm"] is True
    assert mapper.calls[0]["elder"]["today"]["iso"]
    assert response["result"]["preview"]["mappings"][0]["source"] == "direct"


def test_image_start_passes_staged_bytes_and_extension_to_native_extractor(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    image = tmp_path / "elder.jpeg"
    image.write_bytes(b"image bytes")
    dependencies, extractor, _ = _start_dependencies()
    monkeypatch.setattr(native_adapter, "_ready_template", lambda *args: SUMMARY)

    native_adapter._start(
        dependencies,
        {
            "template_id": "oala",
            "use_llm": False,
            "source_hint": None,
            "source": {"kind": "image", "image_path": str(image.resolve())},
        },
    )

    assert extractor.calls == [
        (
            "image",
            {
                "image_bytes": b"image bytes",
                "ext": "jpeg",
                "source_hint": None,
            },
        )
    ]


def test_structured_profile_bypasses_both_extractors(monkeypatch: Any) -> None:
    dependencies, extractor, mapper = _start_dependencies()
    monkeypatch.setattr(native_adapter, "_ready_template", lambda *args: SUMMARY)
    profile = {"elder_id": "E-3", "name_zh": {"full": "陳女士"}}

    native_adapter._start(
        dependencies,
        {
            "template_id": "oala",
            "use_llm": False,
            "source_hint": None,
            "source": {"kind": "elder_profile", "elder_profile": profile},
        },
    )

    assert extractor.calls == []
    assert mapper.calls[0]["elder"]["name_zh"] == {"full": "陳女士"}
    assert "today" not in profile


def test_export_passes_exact_reviewed_values_to_native_filler(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    output_root = tmp_path / "welfare_outputs"
    output_root.mkdir()
    output = output_root / "E-1_oala_timestamp.pdf"
    output.write_bytes(b"%PDF-1.7\n%%EOF")
    calls: list[dict[str, Any]] = []

    class Filler:
        @staticmethod
        def fill_form(template_id: str, **kwargs: Any) -> dict[str, Any]:
            calls.append({"template_id": template_id, **kwargs})
            return {
                "ok": True,
                "template_id": template_id,
                "output_file": output.name,
                "stats": {"strategy": "coord_anchor", "filled": 1},
            }

    class Document:
        page_count = 1

        def __enter__(self) -> "Document":
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    dependencies = {
        "filler": Filler,
        "settings": SimpleNamespace(data_path=tmp_path.resolve()),
        "fitz": SimpleNamespace(open=lambda path: Document()),
    }
    monkeypatch.setattr(native_adapter, "_ready_template", lambda *args: SUMMARY)
    profile = {"elder_id": "E-1", "name_zh": {"full": "李女士"}}
    reviewed = {"name": "人工確認姓名"}

    response = native_adapter._export(
        dependencies,
        {
            "template_id": "oala",
            "elder_profile": profile,
            "field_values": reviewed,
        },
    )

    assert calls == [
        {
            "template_id": "oala",
            "elder_profile": profile,
            "field_values": reviewed,
        }
    ]
    assert response["result"]["stats"]["strategy"] == "coord_anchor"
    assert response["artifact_path"] == str(output.resolve())


def test_discovery_calls_original_listing_and_filters_with_readiness_probe(
    monkeypatch: Any,
) -> None:
    class WelfareForm:
        @staticmethod
        def list_form_templates() -> dict[str, Any]:
            return {
                "version": "v0.4.0-alpha",
                "count": 2,
                "templates": [{"id": "oala"}, {"id": "theta_1"}],
                "has_mock_elder": False,
            }

    def ready(dependencies: Any, template_id: str, summary: Any) -> dict[str, Any]:
        if template_id.startswith("theta"):
            raise ValueError("template source PDF is unavailable")
        return SUMMARY

    monkeypatch.setattr(native_adapter, "_ready_template", ready)
    monkeypatch.setattr(native_adapter, "_supports_heic", lambda: False)
    result = native_adapter._list_templates({"welfare_form": WelfareForm})

    assert result["templates"] == [SUMMARY]
    assert result["hidden_template_count"] == 1
    assert result["source_capabilities"]["image_extensions"] == [
        ".jpg",
        ".jpeg",
        ".png",
    ]
