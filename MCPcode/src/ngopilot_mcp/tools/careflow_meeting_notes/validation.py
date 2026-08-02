"""Meeting-note-specific validation beyond shared path-safety checks."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Mapping

from .schemas import StartInput

AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"})
TEMPLATE_EXTENSIONS = frozenset({".docx", ".doc"})


def validate_start_files(value: StartInput) -> tuple[Path, Path]:
    audio = _validate_local_file(
        value.audio_path,
        role="audio_path",
        extensions=AUDIO_EXTENSIONS,
    )
    template = _validate_local_file(
        value.template_path,
        role="template_path",
        extensions=TEMPLATE_EXTENSIONS,
    )
    return audio, template


def require_legacy_doc_capability(template_path: str | Path) -> None:
    """Fail before session creation when CareFlow cannot normalize legacy DOC."""

    if (
        Path(template_path).suffix.lower() == ".doc"
        and shutil.which("textutil") is None
    ):
        raise ValueError(
            "template_path uses .doc, but this CareFlow worker has no macOS "
            "textutil converter; attach a .docx report template instead"
        )


def validate_complete_slot_content(
    template_contract: Mapping[str, Any] | None,
    slot_content_final: Mapping[str, Any],
) -> None:
    if not isinstance(template_contract, Mapping):
        raise ValueError("the CareFlow session has no reviewable template contract")

    dynamic_slots = template_contract.get("dynamic_slots")
    if not isinstance(dynamic_slots, list):
        raise ValueError("the CareFlow template contract has no dynamic_slots list")

    expected: list[str] = []
    for index, slot in enumerate(dynamic_slots):
        if not isinstance(slot, Mapping) or not isinstance(slot.get("slot_id"), str):
            raise ValueError(f"dynamic_slots[{index}] has no valid slot_id")
        slot_id = slot["slot_id"]
        if not slot_id:
            raise ValueError(f"dynamic_slots[{index}] has an empty slot_id")
        if slot_id in expected:
            raise ValueError(
                f"the CareFlow template contract repeats slot_id {slot_id!r}"
            )
        expected.append(slot_id)

    supplied = set(slot_content_final)
    expected_set = set(expected)
    missing = [slot_id for slot_id in expected if slot_id not in supplied]
    extra = sorted(supplied - expected_set)
    if missing:
        raise ValueError(
            "slot_content_final must contain every template slot; missing: "
            + ", ".join(missing)
        )
    if extra:
        raise ValueError(
            "slot_content_final contains unknown template slots: " + ", ".join(extra)
        )


def _validate_local_file(
    raw_path: str,
    *,
    role: str,
    extensions: frozenset[str],
) -> Path:
    path = Path(raw_path)
    expected = ", ".join(sorted(extensions))
    if not path.is_absolute():
        raise ValueError(f"{role} must be an absolute local path; expected {expected}")
    if path.suffix.lower() not in extensions:
        raise ValueError(f"{role} has an unsupported format; expected {expected}")
    if not path.exists():
        raise ValueError(f"{role} does not exist: {path}")
    if not path.is_file():
        raise ValueError(f"{role} must identify a regular file: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"{role} is empty: {path}")
    return path.resolve(strict=True)
