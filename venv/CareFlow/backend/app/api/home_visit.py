"""家訪語音 → 結構化報告 API."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import settings
from ..db import engine, get_session
from ..models import VisitSession, VisitSessionStatus
from ..services import home_visit


def _bg_run_phase1(
    session_id: int,
    *,
    force_mock: bool = False,
    mode: str = "home_visit",
) -> None:
    """Background wrapper: open a fresh DB session because the request-scoped
    `db` dependency is closed by the time the BackgroundTask runs."""
    with Session(engine) as s:
        home_visit.run_phase1(s, session_id, force_mock=force_mock, mode=mode)


router = APIRouter(prefix="/api/home-visit", tags=["home-visit"])


# ── DTOs ───────────────────────────────────────────────────────────────

class SessionOut(BaseModel):
    id: int
    title: str
    note: Optional[str]
    status: str
    audio_filename: Optional[str]
    template_filename: Optional[str]
    template_contract: Optional[dict]
    slot_content: Optional[dict]
    slot_content_final: Optional[dict]
    generated_file: Optional[str]
    download_url: Optional[str]
    transcript_snippet: Optional[str]
    transcript_burned: bool
    ai_provider: Optional[str]
    ai_model: Optional[str]
    ai_latency_ms: Optional[int]
    ai_error: Optional[str]
    reviewer: Optional[str]
    reviewed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ReviewPayload(BaseModel):
    slot_content_final: dict
    reviewer: Optional[str] = None


def _to_out(s: VisitSession, include_transcript: bool = False) -> SessionOut:
    snippet = home_visit.read_transcript_snippet(s) if include_transcript else None
    return SessionOut(
        id=s.id,
        title=s.title,
        note=s.note,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        audio_filename=s.audio_filename,
        template_filename=s.template_filename,
        template_contract=s.template_contract,
        slot_content=s.slot_content,
        slot_content_final=s.slot_content_final,
        generated_file=s.generated_file,
        download_url=f"/api/files/{s.generated_file}" if s.generated_file else None,
        transcript_snippet=snippet,
        transcript_burned=bool(s.transcript_burned),
        ai_provider=s.ai_provider,
        ai_model=s.ai_model,
        ai_latency_ms=s.ai_latency_ms,
        ai_error=s.ai_error,
        reviewer=s.reviewer,
        reviewed_at=s.reviewed_at,
        created_at=s.created_at,
        updated_at=s.updated_at,
    )


# ── Routes ─────────────────────────────────────────────────────────────

@router.get("/status")
def status():
    return home_visit.placeholder_status()


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def create_visit_session(
    background: BackgroundTasks,
    title: str = Form(...),
    note: Optional[str] = Form(None),
    mode: str = Form("home_visit"),
    audio: UploadFile = File(...),
    template: UploadFile = File(...),
    db: Session = Depends(get_session),
):
    if mode not in {"home_visit", "internal_meeting"}:
        raise HTTPException(400, "mode must be home_visit or internal_meeting")
    audio_bytes = await audio.read()
    template_bytes = await template.read()
    if not audio_bytes:
        raise HTTPException(400, "audio is empty")
    if not template_bytes:
        raise HTTPException(400, "template is empty")

    s = home_visit.create_session(
        db,
        title=title,
        note=note,
        audio=(audio.filename or "audio.mp3", audio_bytes),
        template=(template.filename or "template.docx", template_bytes),
    )
    background.add_task(_bg_run_phase1, s.id, mode=mode)
    return _to_out(s)


@router.get("/sessions")
def list_sessions(db: Session = Depends(get_session)):
    rows = db.exec(select(VisitSession).order_by(VisitSession.created_at.desc())).all()
    return {"sessions": [_to_out(r).model_dump() for r in rows]}


@router.get("/sessions/{session_id}", response_model=SessionOut)
def get_session_detail(session_id: int, db: Session = Depends(get_session)):
    s = db.get(VisitSession, session_id)
    if not s:
        raise HTTPException(404, "session not found")
    return _to_out(s, include_transcript=True)


@router.post("/sessions/{session_id}/review", response_model=SessionOut)
def review_and_render(
    session_id: int,
    payload: ReviewPayload,
    db: Session = Depends(get_session),
):
    try:
        s = home_visit.run_phase2(
            db,
            session_id,
            slot_content_final=payload.slot_content_final,
            reviewer=payload.reviewer,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _to_out(s, include_transcript=True)


@router.post("/sessions/{session_id}/burn")
def burn_transcript(session_id: int, db: Session = Depends(get_session)):
    ok = home_visit.burn_transcript(db, session_id)
    return {"burned": ok}


# ── Mock demo (offline full-pipeline showcase) ────────────────────────



@router.get("/mock-demo/available")
def mock_demo_available():
    """Probe whether the mock-demo fixtures are present on disk."""
    base = settings.data_path / "samples" / "visit_note"
    audio = base / "mock_visit.mp3"
    template = base / "mock_template.docx"
    return {
        "available": audio.exists() and template.exists(),
        "is_mock_mode": settings.is_mock_mode,
        "audio_filename": audio.name if audio.exists() else None,
        "template_filename": template.name if template.exists() else None,
    }


@router.post("/sessions/mock-demo", response_model=SessionOut)
def create_mock_demo_session(
    background: BackgroundTasks,
    title: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_session),
):
    """One-click offline demo: load bundled mp3 + docx fixtures and run phase 1.

    The fixtures live in `data/samples/visit_note/`. The transcriber's mock
    fallback (active whenever `dashscope_api_key` is empty) supplies the
    Cantonese transcript, so the entire pipeline — extraction → contract →
    slot content — runs without any network call.
    """
    base = settings.data_path / "samples" / "visit_note"
    audio_path = base / "mock_visit.mp3"
    template_path = base / "mock_template.docx"
    if not audio_path.exists() or not template_path.exists():
        raise HTTPException(
            404,
            "mock-demo fixtures missing — expected "
            f"{audio_path.name} 與 {template_path.name} 於 {base}",
        )

    final_title = (title or "").strip() or f"Mock 示範 · 陳婆婆 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    final_note = (note or "").strip() or "由系統一鍵載入的離線 mock 示範案（無真實長者資料）"

    s = home_visit.create_session(
        db,
        title=final_title,
        note=final_note,
        audio=(audio_path.name, audio_path.read_bytes()),
        template=(template_path.name, template_path.read_bytes()),
    )
    background.add_task(_bg_run_phase1, s.id, force_mock=True)
    return _to_out(s)
