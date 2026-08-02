"""Worker-only adapter to CareFlow 0.4.8's welfare-form services.

The adapter translates transport values and calls CareFlow's original template
loader, extractors, mapper, and filler. It contains no extraction, mapping, or
PDF-filling algorithm.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import date
from pathlib import Path
from typing import Any

_SAFE_TEMPLATE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_FILL_STRATEGIES = frozenset({"acroform", "coord_anchor"})
_GUARANTEED_EXTENSIONS = [".jpg", ".jpeg", ".png"]
_OPTIONAL_EXTENSIONS = [".heic", ".heif"]


def handle(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation == "list_templates":
        return _list_templates(_dependencies())
    if operation == "start":
        return _start(_dependencies(), payload)
    if operation == "export":
        return _export(_dependencies(), payload)
    raise ValueError(f"unsupported careflow_government_forms operation: {operation}")


def _dependencies() -> dict[str, Any]:
    import fitz
    from app.config import settings
    from app.services import (
        welfare_form,
        welfare_form_extractor,
        welfare_form_filler,
        welfare_form_mapping,
    )
    from app.services.welfare_form_templates import load_template

    return {
        "fitz": fitz,
        "settings": settings,
        "welfare_form": welfare_form,
        "extractor": welfare_form_extractor,
        "filler": welfare_form_filler,
        "mapper": welfare_form_mapping,
        "load_template": load_template,
    }


def _list_templates(dependencies: Mapping[str, Any]) -> dict[str, Any]:
    native = dependencies["welfare_form"].list_form_templates()
    if not isinstance(native, dict) or not isinstance(native.get("templates"), list):
        raise ValueError("CareFlow returned an invalid template listing")

    ready: list[dict[str, Any]] = []
    hidden: list[dict[str, str]] = []
    for summary in native["templates"]:
        template_id = summary.get("id") if isinstance(summary, dict) else None
        if not isinstance(template_id, str):
            hidden.append({"template_id": "<invalid>", "reason": "invalid identifier"})
            continue
        try:
            ready.append(_ready_template(dependencies, template_id, summary))
        except Exception as exc:  # noqa: BLE001 - discovery hides unfillable entries
            hidden.append({"template_id": template_id, "reason": str(exc)})

    optional = _OPTIONAL_EXTENSIONS if _supports_heic() else []
    return {
        "version": native.get("version"),
        "native_count": native.get("count"),
        "count": len(ready),
        "templates": ready,
        "has_mock_elder": native.get("has_mock_elder"),
        "source_capabilities": {
            "text": True,
            "elder_profile": True,
            "image_extensions": _GUARANTEED_EXTENSIONS + optional,
        },
        "hidden_template_count": len(hidden),
        "warnings": hidden,
    }


def _ready_template(
    dependencies: Mapping[str, Any],
    template_id: str,
    native_summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    _require_safe_template_id(template_id)
    template = dependencies["load_template"](template_id)
    if not isinstance(template, dict) or template.get("id") != template_id:
        raise ValueError("template definition ID does not match its filename")
    status = template.get(
        "status",
        native_summary.get("status", "ready") if native_summary else "ready",
    )
    if status != "ready":
        raise ValueError(f"template status is {status!r}, not 'ready'")
    strategy = template.get("fill_strategy")
    if strategy not in _FILL_STRATEGIES:
        raise ValueError(f"unsupported fill strategy: {strategy!r}")
    fields = template.get("fields")
    if not isinstance(fields, list) or not fields:
        raise ValueError("template has no fillable fields")
    if any(not isinstance(field, dict) or not field.get("key") for field in fields):
        raise ValueError("template contains an invalid field definition")

    source_pdf = template.get("source_pdf")
    if not isinstance(source_pdf, str) or Path(source_pdf).name != source_pdf:
        raise ValueError("template has an unsafe source PDF name")
    pdf_root = (dependencies["settings"].data_path / "templates").resolve()
    pdf_path = (pdf_root / source_pdf).resolve()
    if not pdf_path.is_relative_to(pdf_root) or not pdf_path.is_file():
        raise ValueError("template source PDF is unavailable")

    fitz = dependencies["fitz"]
    with fitz.open(pdf_path) as document:
        actual_pages = int(document.page_count)
        if actual_pages <= 0:
            raise ValueError("template source PDF has no pages")
    declared_pages = template.get("pdf_pages")
    if isinstance(declared_pages, int) and declared_pages != actual_pages:
        raise ValueError(
            f"template page count mismatch: declared {declared_pages}, found {actual_pages}"
        )

    result = deepcopy(dict(native_summary or {}))
    result.update(
        {
            "id": template_id,
            "display_name": template.get("display_name"),
            "display_name_en": template.get("display_name_en"),
            "source_pdf": source_pdf,
            "pdf_pages": actual_pages,
            "fill_strategy": strategy,
            "field_count": len(fields),
            "status": "ready",
        }
    )
    return result


def _start(
    dependencies: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    template_id = _required_string(payload, "template_id")
    summary = _ready_template(dependencies, template_id)
    use_llm = payload.get("use_llm")
    if not isinstance(use_llm, bool):
        raise ValueError("use_llm must be a boolean")
    source_hint = payload.get("source_hint")
    if source_hint is not None and not isinstance(source_hint, str):
        raise ValueError("source_hint must be a string or null")
    source = payload.get("source")
    if not isinstance(source, dict):
        raise ValueError("source must be an object")

    source_kind = source.get("kind")
    extractor = dependencies["extractor"]
    if source_kind == "text":
        text = _required_string(source, "text")
        elder = extractor.extract_elder_profile_from_text(
            text,
            source_hint=source_hint,
        )
    elif source_kind == "image":
        image_path = Path(_required_string(source, "image_path"))
        if not image_path.is_absolute() or not image_path.is_file():
            raise ValueError("staged image_path must be an existing absolute file")
        extension = image_path.suffix.lower()
        allowed = _GUARANTEED_EXTENSIONS + (
            _OPTIONAL_EXTENSIONS if _supports_heic() else []
        )
        if extension not in allowed:
            raise ValueError(
                "staged image format is unavailable; supported: " + ", ".join(allowed)
            )
        elder = extractor.extract_elder_profile_from_image(
            image_path.read_bytes(),
            ext=extension.lstrip("."),
            source_hint=source_hint,
        )
    elif source_kind == "elder_profile":
        profile = source.get("elder_profile")
        if not isinstance(profile, dict):
            raise ValueError("elder_profile source must contain an object")
        elder = deepcopy(profile)
    else:
        raise ValueError("source.kind must be text, image, or elder_profile")
    if not isinstance(elder, dict):
        raise ValueError("CareFlow extractor returned a non-object elder profile")

    elder = deepcopy(elder)
    if "today" not in elder:
        today = date.today()
        elder["today"] = {
            "iso": today.isoformat(),
            "year": str(today.year),
            "month": f"{today.month:02d}",
            "day": f"{today.day:02d}",
        }
    template = dependencies["load_template"](template_id)
    preview = dependencies["mapper"].map_elder_to_template(
        template,
        elder,
        use_llm=use_llm,
    )
    if not isinstance(preview, dict):
        raise ValueError("CareFlow mapper returned a non-object preview")

    return {
        "native_status": "pending_review",
        "native_refs": {
            "template_id": template_id,
            "fill_strategy": summary["fill_strategy"],
            "pdf_pages": summary["pdf_pages"],
        },
        "result": {
            "template_id": template_id,
            "template": summary,
            "elder_profile": elder,
            "preview": preview,
            "reviewed_values": None,
            "review": None,
        },
        "warnings": [],
    }


def _export(
    dependencies: Mapping[str, Any], payload: Mapping[str, Any]
) -> dict[str, Any]:
    template_id = _required_string(payload, "template_id")
    summary = _ready_template(dependencies, template_id)
    elder_profile = payload.get("elder_profile")
    field_values = payload.get("field_values")
    if not isinstance(elder_profile, dict):
        raise ValueError("elder_profile must be an object")
    if not isinstance(field_values, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in field_values.items()
    ):
        raise ValueError("field_values must be an object of strings")
    _require_safe_native_elder_id(elder_profile.get("elder_id"))

    native_result = dependencies["filler"].fill_form(
        template_id,
        elder_profile=deepcopy(elder_profile),
        field_values=deepcopy(field_values),
    )
    if not isinstance(native_result, dict):
        raise ValueError("CareFlow filler returned a non-object result")
    output_file = native_result.get("output_file")
    if not isinstance(output_file, str) or Path(output_file).name != output_file:
        raise ValueError("CareFlow filler returned an unsafe output filename")
    output_root = (dependencies["settings"].data_path / "welfare_outputs").resolve()
    output_path = (output_root / output_file).resolve()
    if not output_path.is_relative_to(output_root) or not output_path.is_file():
        raise ValueError("CareFlow filled PDF is outside its managed output directory")
    with dependencies["fitz"].open(output_path) as document:
        page_count = int(document.page_count)
        if page_count != summary["pdf_pages"]:
            raise ValueError(
                "CareFlow filled PDF page count differs from its template definition"
            )

    return {
        "native_status": "filled",
        "native_refs": {
            "template_id": template_id,
            "fill_strategy": summary["fill_strategy"],
            "pdf_pages": summary["pdf_pages"],
            "native_output_file": output_file,
            "native_output_path": str(output_path),
            "fill_stats": deepcopy(native_result.get("stats")),
        },
        "result": deepcopy(native_result),
        "artifact_path": str(output_path),
        "artifact_page_count": page_count,
        "warnings": [],
    }


def _supports_heic() -> bool:
    try:
        from PIL import Image

        Image.init()
        registered = {extension.lower() for extension in Image.registered_extensions()}
        return all(extension in registered for extension in _OPTIONAL_EXTENSIONS)
    except Exception:  # noqa: BLE001 - optional runtime capability probe
        return False


def _require_safe_template_id(template_id: str) -> None:
    if not _SAFE_TEMPLATE_ID.fullmatch(template_id):
        raise ValueError("template_id contains unsafe characters")


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _require_safe_native_elder_id(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise ValueError("elder_profile.elder_id must be a string when supplied")
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("elder_profile.elder_id is unsafe for CareFlow output naming")
