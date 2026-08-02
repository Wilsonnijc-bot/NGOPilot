"""Home-visit orchestrator — connects FastAPI handlers to visit_note_agent.

Workflow (state machine):
    UPLOADED → EXTRACTING → PENDING_REVIEW → (human edit) → RENDERING → CONFIRMED
                                                                        ↘ FAILED

Privacy:
    transcript text never lives in the DB or HTTP responses. It's
    encrypted at rest in `data/transcripts/session_<id>.enc`; only a
    snippet ≤ 200 chars is ever exposed (for review context). The
    `/api/home-visit/sessions/{id}/burn` endpoint shreds it.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session

from ..config import settings
from ..llm.client import resolve_model
from ..models import VisitSession, VisitSessionStatus
from .visit_note_agent import run_extraction, run_render
from .visit_note_agent import transcript_vault


def placeholder_status() -> dict:
    return {
        "feature": "home_visit_audio_to_report",
        "status": "active",
        "provider": "(rc6.1: 3-channel)",
        "models": {
            "asr": settings.bailian_asr_model,
            "text": settings.deepseek_text_model,
            "vision": settings.azure_openai_model,
        },
        "asr_model": settings.bailian_asr_model,
        "text_model": settings.deepseek_text_model,
        "vision_model": settings.azure_openai_model,
        "is_mock_mode": settings.is_mock_mode,
        "mock_mode": settings.is_mock_mode,
        "channels": {
            "text": {"provider": "deepseek_official", "model": settings.deepseek_text_model, "mock": settings.is_text_mock},
            "vision": {"provider": "azure_openai", "model": settings.azure_openai_model, "deployment": settings.azure_openai_deployment, "mock": settings.is_vision_mock},
            "asr": {"provider": "bailian", "model": settings.bailian_asr_model, "mock": settings.is_asr_mock},
        },
        "endpoints": [
            "POST /api/home-visit/sessions",
            "GET  /api/home-visit/sessions",
            "GET  /api/home-visit/sessions/{id}",
            "POST /api/home-visit/sessions/{id}/review",
            "POST /api/home-visit/sessions/{id}/burn",
        ],
    }


def create_session(
    db: Session,
    *,
    title: str,
    note: str | None,
    audio: tuple[str, bytes],
    template: tuple[str, bytes],
) -> VisitSession:
    s = VisitSession(title=title, note=note, status=VisitSessionStatus.UPLOADED)
    db.add(s); db.commit(); db.refresh(s)

    sess_dir = settings.data_path / "visit_sessions" / f"session_{s.id}"
    sess_dir.mkdir(parents=True, exist_ok=True)

    audio_name, audio_bytes = audio
    audio_safe = f"audio_{uuid.uuid4().hex[:8]}{Path(audio_name).suffix.lower()}"
    audio_full = sess_dir / audio_safe
    audio_full.write_bytes(audio_bytes)
    s.audio_path = str(audio_full.relative_to(settings.data_path))
    s.audio_filename = audio_name

    tpl_name, tpl_bytes = template
    tpl_safe = f"template_{uuid.uuid4().hex[:8]}{Path(tpl_name).suffix.lower()}"
    tpl_full = sess_dir / tpl_safe
    tpl_full.write_bytes(tpl_bytes)
    s.template_path = str(tpl_full.relative_to(settings.data_path))
    s.template_filename = tpl_name

    s.updated_at = datetime.utcnow()
    db.add(s); db.commit(); db.refresh(s)
    return s


def run_phase1(
    db: Session,
    session_id: int,
    *,
    force_mock: bool = False,
    mode: str | None = None,
) -> None:
    s = db.get(VisitSession, session_id)
    if not s:
        return
    s.status = VisitSessionStatus.EXTRACTING
    s.updated_at = datetime.utcnow()
    db.add(s); db.commit()

    sess_dir = settings.data_path / "visit_sessions" / f"session_{s.id}"
    sess_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    try:
        result = run_extraction(
            audio_path=str(settings.data_path / s.audio_path),
            template_path=str(settings.data_path / s.template_path),
            working_dir=str(sess_dir / "work"),
            force_mock=force_mock,
            mode=mode,
        )
    except Exception as exc:  # noqa: BLE001
        db.refresh(s)
        s.status = VisitSessionStatus.FAILED
        s.ai_error = str(exc)
        s.updated_at = datetime.utcnow()
        db.add(s); db.commit()
        return

    transcript: str = result["transcript"]
    db.refresh(s)
    s.transcript_vault_path = transcript_vault.write(s.id, transcript)
    s.transcript_burned = False
    s.working_docx_path = str(
        Path(result["working_docx"]).relative_to(settings.data_path)
    )
    s.template_contract = result["template_contract"]
    s.slot_content = result["slot_content"]
    s.slot_content_final = dict(result["slot_content"])
    s.ai_provider = "mock" if force_mock else "deepseek_official"
    s.ai_model = "offline-mock" if force_mock else resolve_model("text")
    s.ai_latency_ms = int((time.time() - t0) * 1000)
    s.ai_error = None
    s.status = VisitSessionStatus.PENDING_REVIEW
    s.updated_at = datetime.utcnow()
    db.add(s); db.commit()


def run_phase2(
    db: Session,
    session_id: int,
    *,
    slot_content_final: dict[str, Any],
    reviewer: str | None,
) -> VisitSession:
    s = db.get(VisitSession, session_id)
    if not s:
        raise ValueError("session not found")
    if s.status not in (
        VisitSessionStatus.PENDING_REVIEW,
        VisitSessionStatus.CONFIRMED,
    ):
        raise ValueError(f"cannot render from status {s.status}")
    if not s.working_docx_path or not s.template_contract:
        raise ValueError("missing working_docx or template_contract")

    s.slot_content_final = slot_content_final
    s.status = VisitSessionStatus.RENDERING
    s.updated_at = datetime.utcnow()
    db.add(s); db.commit()

    out_dir = settings.data_path / "exports" / "visit_notes"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_name = f"visit_note_{s.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
    out_path = out_dir / out_name
    try:
        run_render(
            working_docx=str(settings.data_path / s.working_docx_path),
            template_contract=s.template_contract,
            slot_content=slot_content_final,
            output_path=str(out_path),
        )
    except Exception as exc:  # noqa: BLE001
        s.status = VisitSessionStatus.FAILED
        s.ai_error = str(exc)
        s.updated_at = datetime.utcnow()
        db.add(s); db.commit()
        raise

    s.generated_file = str(out_path.relative_to(settings.data_path))
    s.reviewer = reviewer
    s.reviewed_at = datetime.utcnow()
    s.status = VisitSessionStatus.CONFIRMED
    s.ai_error = None
    s.updated_at = datetime.utcnow()
    db.add(s); db.commit(); db.refresh(s)
    return s


def read_transcript_snippet(s: VisitSession, max_chars: int = 200) -> str | None:
    if not s.transcript_vault_path or s.transcript_burned:
        return None
    try:
        text = transcript_vault.read(s.transcript_vault_path)
    except Exception:  # noqa: BLE001
        return None
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + " …（已截斷，社工可請示主管查閱全文）"


def burn_transcript(db: Session, session_id: int) -> bool:
    s = db.get(VisitSession, session_id)
    if not s or not s.transcript_vault_path:
        return False
    ok = transcript_vault.burn(s.transcript_vault_path)
    s.transcript_burned = True
    s.transcript_vault_path = None
    s.updated_at = datetime.utcnow()
    db.add(s); db.commit()
    return ok
