"""Interpret CareFlow visit-session state without exposing vault internals."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

_PUBLIC_SESSION_FIELDS = (
    "id",
    "title",
    "note",
    "status",
    "audio_filename",
    "template_filename",
    "template_contract",
    "slot_content",
    "slot_content_final",
    "generated_file",
    "download_url",
    "transcript_snippet",
    "transcript_burned",
    "ai_provider",
    "ai_model",
    "ai_latency_ms",
    "ai_error",
    "reviewer",
    "reviewed_at",
    "created_at",
    "updated_at",
)


def public_session(native_payload: Mapping[str, Any], *, mode: str) -> dict[str, Any]:
    raw_session = native_payload.get("session", native_payload)
    if not isinstance(raw_session, Mapping):
        raise ValueError("CareFlow worker returned no visit session payload")
    session = {
        key: deepcopy(raw_session[key])
        for key in _PUBLIC_SESSION_FIELDS
        if key in raw_session
    }
    session["mode"] = mode
    return session


def native_reference(native_payload: Mapping[str, Any]) -> int:
    raw = native_payload.get("native_session_id")
    if raw is None and isinstance(native_payload.get("session"), Mapping):
        raw = native_payload["session"].get("id")
    if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
        raise ValueError("CareFlow worker returned an invalid native session ID")
    return raw


def native_status(session: Mapping[str, Any]) -> str:
    value = session.get("status")
    if not isinstance(value, str) or not value:
        raise ValueError("CareFlow worker returned an invalid visit-session status")
    return value


def normalized_state(session: Mapping[str, Any]) -> str:
    status = native_status(session)
    if status in {"uploaded", "extracting", "rendering"}:
        return "running"
    if status == "pending_review":
        return "pending_review"
    if status == "confirmed":
        return "confirmed"
    if status == "failed":
        return "failed"
    return status


def next_operations(session: Mapping[str, Any], *, exported: bool = False) -> list[str]:
    status = native_status(session)
    burned = bool(session.get("transcript_burned"))
    operations = ["status"]
    if status in {"pending_review", "confirmed"}:
        operations.append("review")
    if status == "confirmed":
        operations.append("export")
    if not burned:
        operations.append("burn")
    return operations
