"""Visit-note service orchestration.

Rewritten from the partner branch's single-shot
`generate_visit_case_note()` into a **two-phase** flow so we can enforce
CareFlow's mandatory human-review gate between AI extraction and final
DOCX rendering:

    Phase 1 — `run_extraction()`:
        audio → transcript
        template → normalized .docx + structural map + contract
        (transcript + contract) → slot_content
        ⇒ status = pending_review

    Phase 2 — `run_render()`  (after human edits slot_content):
        (working_docx + contract + final slot_content) → final .docx
        ⇒ status = confirmed
"""
from __future__ import annotations

import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from .docx_structural_extractor import extract_docx_structural_map
from .docx_template_renderer import render_docx_from_template
from .errors import VisitNoteAgentError
from . import llm_client  # late binding so mock monkey-patch in __init__ applies
from . import mock as _mock
from .template_normalizer import (
    PDF_UNSUPPORTED_MESSAGE,
    UNSUPPORTED_TEMPLATE_MESSAGE,
    normalize_template_to_docx,
)
from .transcriber import transcribe_audio, _MOCK_TRANSCRIPT_FALLBACK

# Backward-compatible hook points for partner tests and CLI-era callers.
def analyze_template_contract(structural_map: dict, model: str | None = None) -> dict:
    return llm_client.analyze_template_contract(structural_map, model=model)


def generate_slot_content(
    transcript: str,
    template_contract: dict,
    model: str | None = None,
    *,
    mode: str | None = None,
) -> dict:
    return llm_client.generate_slot_content(
        transcript,
        template_contract,
        model=model,
        mode=mode,
    )


# ─── Phase 1 ────────────────────────────────────────────────────────────

def run_extraction(
    audio_path: str,
    template_path: str,
    working_dir: str,
    model: str | None = None,
    *,
    force_mock: bool = False,
    mode: str | None = None,
) -> dict[str, Any]:
    """Extract everything needed for human review.

    Persists the normalized working .docx into `working_dir` so phase 2
    can reuse it without re-normalizing.

    When `force_mock=True` the transcriber and LLM client are bypassed
    entirely — the bundled mock transcript + heuristic mock contract +
    mock slot content are used. This guarantees offline behaviour for
    the `/api/home-visit/sessions/mock-demo` endpoint regardless of
    whether a real DashScope API key is configured.

    Returns
    -------
    dict with keys:
        transcript (str)            — raw STT output (caller must persist via vault)
        working_docx (str)          — path to normalized .docx
        structural_map (dict)
        template_contract (dict)
        slot_content (dict)
    """
    mode = llm_client.normalize_prompt_mode(mode)
    audio = Path(audio_path)
    template = Path(template_path)
    work = Path(working_dir)
    work.mkdir(parents=True, exist_ok=True)

    _validate_input_files(audio, template)
    _validate_supported_template_type(template)

    if force_mock:
        # Bypass network entirely — use bundled fixtures + mock helpers.
        sample_transcript_path = (
            Path(__file__).resolve().parents[3]
            / "data" / "samples" / "visit_note" / "mock_transcript.txt"
        )
        if sample_transcript_path.exists():
            transcript = sample_transcript_path.read_text(encoding="utf-8").strip()
        else:
            transcript = _MOCK_TRANSCRIPT_FALLBACK
        working_docx, structural_map, template_contract = _prepare_template_contract(
            str(template), str(work), model, force_mock=True
        )
        slot_content = _mock.mock_slot_content(transcript, template_contract)
        return {
            "transcript": transcript,
            "working_docx": working_docx,
            "structural_map": structural_map,
            "template_contract": template_contract,
            "slot_content": slot_content,
        }

    with ThreadPoolExecutor(max_workers=2) as ex:
        transcript_future = ex.submit(transcribe_audio, str(audio))
        template_future = ex.submit(
            _prepare_template_contract, str(template), str(work), model
        )
        transcript = transcript_future.result()
        working_docx, structural_map, template_contract = template_future.result()

    slot_content = generate_slot_content(
        transcript,
        template_contract,
        model=model,
        mode=mode,
    )

    return {
        "transcript": transcript,
        "working_docx": working_docx,
        "structural_map": structural_map,
        "template_contract": template_contract,
        "slot_content": slot_content,
    }


# ─── Phase 2 ────────────────────────────────────────────────────────────

def run_render(
    working_docx: str,
    template_contract: dict,
    slot_content: dict,
    output_path: str,
) -> str:
    """Render the final reviewed .docx.

    `slot_content` may have been edited by a social worker between
    phase 1 and phase 2.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        render_docx_from_template(
            working_docx, template_contract, slot_content, str(out)
        )
    except VisitNoteAgentError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VisitNoteAgentError("Visit note rendering failed") from exc
    return str(out)


# ─── Legacy single-shot (kept for CLI / tests) ──────────────────────────

def generate_visit_case_note(
    audio_path: str,
    template_path: str,
    output_dir: str,
    model: str | None = None,
) -> str:
    """One-shot generation — ONLY for CLI / partner tests.

    The production web flow MUST use `run_extraction()` + human review +
    `run_render()` instead. Kept here so partner's existing pytest
    suite (`tests/visit_note/`) still passes unchanged.
    """
    out_dir = Path(output_dir)
    _ensure_output_dir(out_dir)
    try:
        out_path = out_dir / f"visit_note_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        with tempfile.TemporaryDirectory(prefix="visit_note_template_") as temp_dir:
            result = run_extraction(audio_path, template_path, temp_dir, model)
            run_render(
                result["working_docx"],
                result["template_contract"],
                result["slot_content"],
                str(out_path),
            )
    except VisitNoteAgentError:
        raise
    except ValueError as exc:
        raise VisitNoteAgentError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise VisitNoteAgentError("Visit note generation failed") from exc
    return str(out_path)


# ─── helpers (lifted from partner branch) ───────────────────────────────

def _validate_input_files(audio: Path, template: Path) -> None:
    if not audio.exists() or not audio.is_file():
        raise VisitNoteAgentError(f"Audio file not found: {audio}")
    if not template.exists() or not template.is_file():
        raise VisitNoteAgentError(f"Template file not found: {template}")


def _validate_supported_template_type(template: Path) -> None:
    suffix = template.suffix.lower()
    if suffix == ".pdf":
        raise VisitNoteAgentError(PDF_UNSUPPORTED_MESSAGE)
    if suffix not in {".docx", ".doc"}:
        raise VisitNoteAgentError(UNSUPPORTED_TEMPLATE_MESSAGE)


def _ensure_output_dir(output_dir: Path) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output_dir, prefix=".write_test_", delete=True):
            pass
    except OSError as exc:
        raise VisitNoteAgentError(f"Output directory is not writable: {output_dir}") from exc


def _prepare_template_contract(
    template_path: str, temp_dir: str, model: str | None,
    *, force_mock: bool = False,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    working = normalize_template_to_docx(template_path, temp_dir)
    structural_map = extract_docx_structural_map(working)
    if force_mock:
        contract = _mock.mock_template_contract(structural_map)
    else:
        contract = analyze_template_contract(structural_map, model=model)
    return working, structural_map, contract


# expose used symbol for backwards compat with partner tests
__all__ = [
    "run_extraction",
    "run_render",
    "generate_visit_case_note",
    "shutil",
]
