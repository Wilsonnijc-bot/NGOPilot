"""Authenticated WebSocket relay with lightweight ACP metadata interception."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .config import Settings
from .db import Database
from .processes import TenantProcessManager
from .storage import PlaceholderError, StorageService, iter_mappings

logger = logging.getLogger(__name__)
MAX_ACP_MESSAGE_BYTES = 64 * 1024 * 1024
TENANT_CWD_METHODS = {"session/new", "session/load"}
UPDATE_CWD_METHOD = "_goose/unstable/session/working-dir/update"


def isolate_client_request(message: dict[str, Any], tenant_root: Path) -> dict[str, Any]:
    method = message.get("method")
    if method not in TENANT_CWD_METHODS and method != UPDATE_CWD_METHOD:
        return message

    params = message.get("params")
    isolated_params = dict(params) if isinstance(params, dict) else {}
    if method in TENANT_CWD_METHODS:
        isolated_params["cwd"] = str(tenant_root)
        isolated_params["mcpServers"] = []
    else:
        isolated_params["workingDir"] = str(tenant_root)
    return {**message, "params": isolated_params}


def request_key(value: Any) -> str:
    if isinstance(value, (str, int)):
        return str(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def session_id_from(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    session_id = value.get("sessionId") or value.get("session_id")
    if isinstance(session_id, str) and 0 < len(session_id) <= 256:
        return session_id
    return None


def external_id_from(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for mapping in iter_mappings(value, parse_json_strings=False):
        for key in ("messageId", "message_id", "toolCallId", "tool_call_id"):
            item = mapping.get(key)
            if isinstance(item, (str, int)) and item != "":
                return str(item)[:256]
    return None


def extract_jobs(value: Any) -> list[tuple[str, str, dict[str, Any]]]:
    jobs: dict[str, tuple[str, dict[str, Any]]] = {}
    for mapping in iter_mappings(value):
        job_id = mapping.get("job_id")
        if not isinstance(job_id, str) or not 0 < len(job_id) <= 96:
            continue
        tool_name = mapping.get("tool_name") or mapping.get("tool") or "ngopilot"
        if not isinstance(tool_name, str) or not tool_name:
            tool_name = "ngopilot"
        jobs[job_id] = (tool_name[:96], mapping)
    return [(job_id, tool, payload) for job_id, (tool, payload) in jobs.items()]


@dataclass(slots=True)
class PendingRequest:
    method: str
    session_id: str | None
    params: dict[str, Any]


class AcpRecorder:
    def __init__(self, db: Database, settings: Settings, user_id: UUID):
        self.db = db
        self.settings = settings
        self.user_id = user_id
        self.pending: dict[str, PendingRequest] = {}

    async def client_message(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        session_id = session_id_from(params)
        if "id" in message:
            self.pending[request_key(message["id"])] = PendingRequest(method, session_id, params)
        if session_id is not None:
            await self.db.upsert_chat_session(self.user_id, session_id, self.settings.goose_model)
        if method == "session/prompt" and session_id is not None:
            external_id = f"request:{request_key(message.get('id'))}" if "id" in message else None
            await self.db.record_message(
                self.user_id,
                session_id,
                "user",
                "prompt",
                params.get("prompt") or [],
                external_id=external_id,
            )
        await self._record_jobs(session_id, message)

    async def agent_message(self, message: dict[str, Any]) -> None:
        if "id" in message and "method" not in message:
            pending = self.pending.pop(request_key(message["id"]), None)
            if pending is not None:
                await self._record_response(pending, message)

        method = message.get("method")
        params = message.get("params")
        session_id = session_id_from(params)
        if isinstance(method, str) and isinstance(params, dict) and session_id is not None:
            if method in {"session/update", "_goose/unstable/session/update"}:
                update = params.get("update") or params
                kind = "update"
                role = "assistant"
                if isinstance(update, dict):
                    update_kind = update.get("sessionUpdate") or update.get("session_update")
                    if isinstance(update_kind, str):
                        kind = update_kind[:64]
                        if update_kind.startswith("tool_call"):
                            role = "tool"
                        elif update_kind.startswith("user_message"):
                            role = "user"
                    title = update.get("title")
                    if isinstance(title, str) and title.strip():
                        await self.db.upsert_chat_session(
                            self.user_id,
                            session_id,
                            self.settings.goose_model,
                            title=title,
                        )
                await self.db.record_message(
                    self.user_id,
                    session_id,
                    role,
                    kind,
                    update,
                    external_id=external_id_from(update),
                    metadata={"notification": method},
                )
        await self._record_jobs(session_id, message)

    async def _record_response(self, pending: PendingRequest, message: dict[str, Any]) -> None:
        if "error" in message:
            return
        result = message.get("result")
        if pending.method == "session/new":
            session_id = session_id_from(result)
            if session_id is not None:
                await self.db.upsert_chat_session(
                    self.user_id, session_id, self.settings.goose_model
                )
        elif pending.method == "session/load" and pending.session_id is not None:
            await self.db.upsert_chat_session(
                self.user_id, pending.session_id, self.settings.goose_model
            )
        elif pending.method == "session/list" and isinstance(result, dict):
            sessions = result.get("sessions")
            if isinstance(sessions, list):
                for item in sessions:
                    session_id = session_id_from(item)
                    if session_id is None:
                        continue
                    title = item.get("title") if isinstance(item, dict) else None
                    metadata = item.get("_meta") if isinstance(item, dict) else None
                    await self.db.upsert_chat_session(
                        self.user_id,
                        session_id,
                        self.settings.goose_model,
                        title=title if isinstance(title, str) else None,
                        metadata=metadata if isinstance(metadata, dict) else None,
                    )
        elif pending.session_id is not None:
            if pending.method == "_goose/unstable/session/rename":
                title = pending.params.get("title")
                if isinstance(title, str):
                    await self.db.rename_chat_session(self.user_id, pending.session_id, title)
            elif pending.method == "_goose/unstable/session/archive":
                await self.db.archive_chat_session(self.user_id, pending.session_id, True)
            elif pending.method == "_goose/unstable/session/unarchive":
                await self.db.archive_chat_session(self.user_id, pending.session_id, False)
            elif pending.method == "session/delete":
                await self.db.delete_chat_session(self.user_id, pending.session_id)
        await self._record_jobs(pending.session_id or session_id_from(result), message)

    async def _record_jobs(self, session_id: str | None, value: Any) -> None:
        if session_id is None:
            return
        for job_id, tool_name, payload in extract_jobs(value):
            await self.db.upsert_job(self.user_id, session_id, job_id, tool_name, payload)


async def proxy_websocket(
    websocket: WebSocket,
    user_id: UUID,
    settings: Settings,
    db: Database,
    processes: TenantProcessManager,
    storage: StorageService,
) -> None:
    managed = await processes.acquire(user_id)
    recorder = AcpRecorder(db, settings, user_id)
    try:
        async with connect(
            managed.websocket_url,
            additional_headers={"X-Secret-Key": managed.secret},
            max_size=MAX_ACP_MESSAGE_BYTES,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        ) as upstream:
            await websocket.accept()

            async def client_to_agent() -> None:
                while True:
                    raw = await websocket.receive_text()
                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(message, dict):
                        continue
                    message = isolate_client_request(message, managed.tenant_root)
                    try:
                        await recorder.client_message(message)
                        rewritten = await storage.resolve_payload(user_id, message)
                    except PlaceholderError as error:
                        if "id" in message:
                            await websocket.send_json(
                                {
                                    "jsonrpc": "2.0",
                                    "id": message["id"],
                                    "error": {"code": -32602, "message": str(error)},
                                }
                            )
                            continue
                        raise
                    await upstream.send(json.dumps(rewritten, separators=(",", ":")))

            async def agent_to_client() -> None:
                async for raw in upstream:
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="strict")
                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(message, dict):
                        continue
                    try:
                        await recorder.agent_message(message)
                    except Exception:
                        logger.exception("Failed to persist ACP metadata for user %s", user_id)
                    storage.schedule_artifact_mirror(user_id, message)
                    await websocket.send_text(raw)

            relays = {
                asyncio.create_task(client_to_agent(), name=f"acp-client-{user_id}"),
                asyncio.create_task(agent_to_client(), name=f"acp-agent-{user_id}"),
            }
            done, pending = await asyncio.wait(relays, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                exception = task.exception()
                if exception is not None:
                    raise exception
    except (WebSocketDisconnect, ConnectionClosed):
        pass
    finally:
        await processes.release(user_id)
