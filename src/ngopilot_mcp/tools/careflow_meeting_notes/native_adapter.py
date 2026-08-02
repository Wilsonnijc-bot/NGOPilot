"""Worker-only adapter to CareFlow 0.4.8's native visit-note services.

This module is intentionally never imported by the MCP host. It orchestrates
the existing service boundaries and contains no transcription, template,
rendering, encryption, or burn algorithm.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .validation import require_legacy_doc_capability


def handle(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    if operation == "start":
        return _start(payload)
    if operation == "status":
        return _status(payload)
    if operation == "review":
        return _review(payload)
    if operation == "export":
        return _export(payload)
    if operation == "burn":
        return _burn(payload)
    raise ValueError(f"unsupported careflow_meeting_notes operation: {operation}")


def _start(payload: dict[str, Any]) -> dict[str, Any]:
    mode = payload.get("mode")
    if mode not in {"home_visit", "internal_meeting"}:
        raise ValueError("mode must be home_visit or internal_meeting")

    audio_path = Path(_required_string(payload, "audio_path"))
    template_path = Path(_required_string(payload, "template_path"))
    require_legacy_doc_capability(template_path)
    if not audio_path.is_file() or not template_path.is_file():
        raise ValueError("staged audio_path and template_path must both exist")

    dependencies = _dependencies()
    dependencies["init_db"]()
    with dependencies["Session"](dependencies["engine"]) as db:
        session = dependencies["home_visit"].create_session(
            db,
            title=_required_string(payload, "title"),
            note=payload.get("note"),
            audio=(audio_path.name, audio_path.read_bytes()),
            template=(template_path.name, template_path.read_bytes()),
        )
        native_session_id = _session_id(session)
        dependencies["home_visit"].run_phase1(
            db,
            native_session_id,
            mode=mode,
        )
        session = _load_session(db, dependencies["VisitSession"], native_session_id)
        return _response(session, dependencies, include_transcript=True)


def _status(payload: dict[str, Any]) -> dict[str, Any]:
    dependencies = _dependencies()
    dependencies["init_db"]()
    native_session_id = _native_session_id(payload)
    with dependencies["Session"](dependencies["engine"]) as db:
        session = _load_session(db, dependencies["VisitSession"], native_session_id)
        return _response(session, dependencies, include_transcript=True)


def _review(payload: dict[str, Any]) -> dict[str, Any]:
    slot_content_final = payload.get("slot_content_final")
    if not isinstance(slot_content_final, dict):
        raise ValueError("slot_content_final must be an object")

    dependencies = _dependencies()
    dependencies["init_db"]()
    native_session_id = _native_session_id(payload)
    with dependencies["Session"](dependencies["engine"]) as db:
        session = dependencies["home_visit"].run_phase2(
            db,
            native_session_id,
            slot_content_final=slot_content_final,
            reviewer=payload.get("reviewer"),
        )
        return _response(session, dependencies, include_transcript=True)


def _export(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the native render reference without invoking a renderer."""

    dependencies = _dependencies()
    dependencies["init_db"]()
    native_session_id = _native_session_id(payload)
    with dependencies["Session"](dependencies["engine"]) as db:
        session = _load_session(db, dependencies["VisitSession"], native_session_id)
        if not session.generated_file:
            raise ValueError("the CareFlow session has no rendered meeting note")
        return _response(session, dependencies, include_transcript=True)


def _burn(payload: dict[str, Any]) -> dict[str, Any]:
    dependencies = _dependencies()
    dependencies["init_db"]()
    native_session_id = _native_session_id(payload)
    with dependencies["Session"](dependencies["engine"]) as db:
        burned = dependencies["home_visit"].burn_transcript(db, native_session_id)
        session = _load_session(db, dependencies["VisitSession"], native_session_id)
        response = _response(session, dependencies, include_transcript=True)
        response["burned"] = bool(burned)
        return response


def _dependencies() -> dict[str, Any]:
    # CareFlow deliberately remains behind the worker-only module boundary.
    from app.config import settings
    from app.db import engine, init_db
    from app.models import VisitSession
    from app.services import home_visit
    from sqlmodel import Session

    return {
        "Session": Session,
        "VisitSession": VisitSession,
        "engine": engine,
        "home_visit": home_visit,
        "init_db": init_db,
        "settings": settings,
    }


def _response(
    session: Any,
    dependencies: dict[str, Any],
    *,
    include_transcript: bool,
) -> dict[str, Any]:
    home_visit = dependencies["home_visit"]
    settings = dependencies["settings"]
    generated_file = session.generated_file
    response: dict[str, Any] = {
        "native_session_id": _session_id(session),
        "session": {
            "id": _session_id(session),
            "title": session.title,
            "note": session.note,
            "status": _enum_value(session.status),
            "audio_filename": session.audio_filename,
            "template_filename": session.template_filename,
            "template_contract": session.template_contract,
            "slot_content": session.slot_content,
            "slot_content_final": session.slot_content_final,
            "generated_file": generated_file,
            "download_url": f"/api/files/{generated_file}" if generated_file else None,
            "transcript_snippet": (
                home_visit.read_transcript_snippet(session)
                if include_transcript
                else None
            ),
            "transcript_burned": bool(session.transcript_burned),
            "ai_provider": session.ai_provider,
            "ai_model": session.ai_model,
            "ai_latency_ms": session.ai_latency_ms,
            "ai_error": session.ai_error,
            "reviewer": session.reviewer,
            "reviewed_at": _json_scalar(session.reviewed_at),
            "created_at": _json_scalar(session.created_at),
            "updated_at": _json_scalar(session.updated_at),
        },
    }
    if generated_file:
        native_path = (settings.data_path / generated_file).resolve()
        try:
            native_path.relative_to(settings.data_path.resolve())
        except ValueError as exc:
            raise ValueError(
                "CareFlow generated_file escapes its managed data root"
            ) from exc
        response["native_artifact_path"] = str(native_path)
    return response


def _load_session(db: Any, model: Any, native_session_id: int) -> Any:
    session = db.get(model, native_session_id)
    if session is None:
        raise ValueError(f"CareFlow visit session {native_session_id} was not found")
    return session


def _session_id(session: Any) -> int:
    value = session.id
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("CareFlow returned an invalid visit session ID")
    return value


def _native_session_id(payload: dict[str, Any]) -> int:
    value = payload.get("native_session_id")
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("native_session_id must be a positive integer")
    return value


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _json_scalar(value: Any) -> Any:
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else value
