"""Small asyncpg repository for gateway-owned cloud metadata."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from .config import Settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def bounded_json(value: Any, limit: int = 900_000) -> Any:
    """Keep untrusted agent payloads below PostgreSQL schema limits."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return {"unserializable": True, "type": type(value).__name__}
    if len(encoded.encode("utf-8")) <= limit:
        return value
    return {
        "truncated": True,
        "original_bytes": len(encoded.encode("utf-8")),
        "preview": encoded[: min(4096, len(encoded))],
    }


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if not self.settings.database_url:
            raise RuntimeError("DATABASE_URL is required")
        self.pool = await asyncpg.create_pool(
            self.settings.database_url,
            min_size=self.settings.database_pool_min_size,
            max_size=self.settings.database_pool_max_size,
            command_timeout=30,
        )

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()
            self.pool = None

    def _pool(self) -> asyncpg.Pool:
        if self.pool is None:
            raise RuntimeError("database is not connected")
        return self.pool

    async def ping(self) -> bool:
        return await self._pool().fetchval("SELECT 1") == 1

    async def create_user(
        self, email: str, password_hash: str, display_name: str | None
    ) -> asyncpg.Record:
        return await self._pool().fetchrow(
            """
            INSERT INTO users (email_normalized, password_hash, display_name)
            VALUES ($1, $2, $3)
            RETURNING id, email_normalized, display_name, created_at
            """,
            email,
            password_hash,
            display_name,
        )

    async def user_for_login(self, email: str) -> asyncpg.Record | None:
        return await self._pool().fetchrow(
            """
            SELECT id, email_normalized, password_hash, display_name, created_at
            FROM users
            WHERE email_normalized = $1 AND disabled_at IS NULL
            """,
            email,
        )

    async def create_auth_session(
        self, user_id: UUID, token_hash: bytes, ttl_hours: int
    ) -> asyncpg.Record:
        expires_at = utcnow() + timedelta(hours=ttl_hours)
        return await self._pool().fetchrow(
            """
            INSERT INTO auth_sessions (user_id, token_hash, expires_at)
            VALUES ($1, $2, $3)
            RETURNING id, expires_at
            """,
            user_id,
            token_hash,
            expires_at,
        )

    async def auth_context(self, token_hash: bytes) -> asyncpg.Record | None:
        async with self._pool().acquire() as connection:
            async with connection.transaction():
                row = await connection.fetchrow(
                    """
                    SELECT
                        u.id AS user_id,
                        u.email_normalized,
                        u.display_name,
                        u.created_at,
                        s.id AS auth_session_id,
                        s.expires_at
                    FROM auth_sessions AS s
                    JOIN users AS u ON u.id = s.user_id
                    WHERE s.token_hash = $1
                      AND s.revoked_at IS NULL
                      AND s.expires_at > now()
                      AND u.disabled_at IS NULL
                    """,
                    token_hash,
                )
                if row is not None:
                    await connection.execute(
                        "UPDATE auth_sessions SET last_seen_at = now() WHERE id = $1",
                        row["auth_session_id"],
                    )
                return row

    async def revoke_auth_session(self, auth_session_id: UUID) -> None:
        await self._pool().execute(
            """
            UPDATE auth_sessions
            SET revoked_at = COALESCE(revoked_at, now())
            WHERE id = $1
            """,
            auth_session_id,
        )

    async def create_ws_ticket(
        self,
        user_id: UUID,
        auth_session_id: UUID,
        ticket_hash: bytes,
        ttl_seconds: int,
    ) -> datetime:
        expires_at = utcnow() + timedelta(seconds=ttl_seconds)
        await self._pool().execute(
            """
            INSERT INTO ws_tickets (
                user_id, auth_session_id, ticket_hash, expires_at
            ) VALUES ($1, $2, $3, $4)
            """,
            user_id,
            auth_session_id,
            ticket_hash,
            expires_at,
        )
        return expires_at

    async def consume_ws_ticket(self, ticket_hash: bytes) -> asyncpg.Record | None:
        return await self._pool().fetchrow(
            """
            UPDATE ws_tickets AS ticket
            SET used_at = now()
            FROM auth_sessions AS auth
            JOIN users AS owner ON owner.id = auth.user_id
            WHERE ticket.ticket_hash = $1
              AND ticket.used_at IS NULL
              AND ticket.expires_at > now()
              AND auth.id = ticket.auth_session_id
              AND auth.user_id = ticket.user_id
              AND auth.revoked_at IS NULL
              AND auth.expires_at > now()
              AND owner.disabled_at IS NULL
            RETURNING ticket.user_id, ticket.auth_session_id
            """,
            ticket_hash,
        )

    async def upsert_chat_session(
        self,
        user_id: UUID,
        agent_session_id: str,
        model: str,
        *,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> asyncpg.Record:
        safe_title = (title or "New chat").strip()[:200] or "New chat"
        return await self._pool().fetchrow(
            """
            INSERT INTO chat_sessions (
                user_id, agent_session_id, title, model, metadata
            ) VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (user_id, agent_session_id) DO UPDATE SET
                title = CASE
                    WHEN EXCLUDED.title <> 'New chat' THEN EXCLUDED.title
                    ELSE chat_sessions.title
                END,
                model = EXCLUDED.model,
                metadata = chat_sessions.metadata || EXCLUDED.metadata,
                updated_at = now(),
                deleted_at = NULL
            RETURNING id, agent_session_id
            """,
            user_id,
            agent_session_id[:256],
            safe_title,
            model[:200],
            json.dumps(bounded_json(metadata or {}, 14_000)),
        )

    async def rename_chat_session(self, user_id: UUID, agent_session_id: str, title: str) -> None:
        safe_title = title.strip()[:200]
        if not safe_title:
            return
        await self._pool().execute(
            """
            UPDATE chat_sessions
            SET title = $3, updated_at = now()
            WHERE user_id = $1 AND agent_session_id = $2 AND deleted_at IS NULL
            """,
            user_id,
            agent_session_id[:256],
            safe_title,
        )

    async def archive_chat_session(
        self, user_id: UUID, agent_session_id: str, archived: bool
    ) -> None:
        await self._pool().execute(
            """
            UPDATE chat_sessions
            SET archived_at = CASE WHEN $3 THEN now() ELSE NULL END,
                status = CASE WHEN $3 THEN 'archived' ELSE 'active' END,
                updated_at = now()
            WHERE user_id = $1 AND agent_session_id = $2 AND deleted_at IS NULL
            """,
            user_id,
            agent_session_id[:256],
            archived,
        )

    async def delete_chat_session(self, user_id: UUID, agent_session_id: str) -> None:
        await self._pool().execute(
            """
            UPDATE chat_sessions
            SET deleted_at = COALESCE(deleted_at, now()),
                status = 'deleted',
                updated_at = now()
            WHERE user_id = $1 AND agent_session_id = $2
            """,
            user_id,
            agent_session_id[:256],
        )

    async def record_message(
        self,
        user_id: UUID,
        agent_session_id: str,
        role: str,
        kind: str,
        content: Any,
        *,
        external_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        session = await self.upsert_chat_session(
            user_id, agent_session_id, self.settings.goose_model
        )
        await self._pool().execute(
            """
            INSERT INTO messages (
                user_id, session_id, agent_session_id, external_id,
                role, kind, content, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb)
            ON CONFLICT (user_id, agent_session_id, external_id)
                WHERE external_id IS NOT NULL
            DO UPDATE SET
                content = EXCLUDED.content,
                metadata = messages.metadata || EXCLUDED.metadata
            """,
            user_id,
            session["id"],
            agent_session_id[:256],
            external_id[:256] if external_id else None,
            role,
            kind[:64],
            json.dumps(bounded_json(content)),
            json.dumps(bounded_json(metadata or {}, 14_000)),
        )

    async def upsert_job(
        self,
        user_id: UUID,
        agent_session_id: str,
        job_id: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> None:
        session = await self.upsert_chat_session(
            user_id, agent_session_id, self.settings.goose_model
        )
        state = str(payload.get("state") or payload.get("status") or "accepted")[:64]
        native_status = payload.get("native_status")
        if native_status is not None:
            native_status = str(native_status)[:64]
        result = payload.get("result")
        result_summary = result if isinstance(result, dict) else {}
        native_refs = payload.get("native_refs")
        if not isinstance(native_refs, dict):
            native_refs = {}
        await self._pool().execute(
            """
            INSERT INTO jobs (
                job_id, user_id, session_id, agent_session_id, tool_name,
                state, native_status, payload, result_summary, native_refs
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10::jsonb
            )
            ON CONFLICT (job_id) DO UPDATE SET
                state = EXCLUDED.state,
                native_status = EXCLUDED.native_status,
                payload = EXCLUDED.payload,
                result_summary = EXCLUDED.result_summary,
                native_refs = EXCLUDED.native_refs,
                updated_at = now()
            WHERE jobs.user_id = EXCLUDED.user_id
            """,
            job_id[:96],
            user_id,
            session["id"],
            agent_session_id[:256],
            tool_name[:96] or "unknown",
            state or "accepted",
            native_status,
            json.dumps(bounded_json(payload)),
            json.dumps(bounded_json(result_summary)),
            json.dumps(bounded_json(native_refs, 60_000)),
        )

    async def create_upload(
        self,
        upload_id: UUID,
        user_id: UUID,
        filename: str,
        content_type: str,
        placeholder: str,
    ) -> None:
        await self._pool().execute(
            """
            INSERT INTO storage_objects (
                id, user_id, kind, filename, content_type, status, metadata
            ) VALUES ($1, $2, 'upload', $3, $4, 'pending', $5::jsonb)
            """,
            upload_id,
            user_id,
            filename[:255],
            content_type[:255],
            json.dumps({"placeholder": placeholder}),
        )

    async def finish_upload(
        self,
        upload_id: UUID,
        user_id: UUID,
        *,
        size_bytes: int,
        sha256: str,
        local_path: str,
        object_key: str,
    ) -> None:
        await self._pool().execute(
            """
            UPDATE storage_objects
            SET size_bytes = $3,
                sha256 = $4,
                local_path = $5,
                object_key = $6,
                status = 'ready',
                verified_at = now()
            WHERE id = $1 AND user_id = $2 AND status = 'pending'
            """,
            upload_id,
            user_id,
            size_bytes,
            sha256,
            local_path,
            object_key,
        )

    async def fail_upload(self, upload_id: UUID, user_id: UUID, reason: str) -> None:
        await self._pool().execute(
            """
            UPDATE storage_objects
            SET status = 'failed',
                metadata = metadata || jsonb_build_object('error', $3::text)
            WHERE id = $1 AND user_id = $2 AND status = 'pending'
            """,
            upload_id,
            user_id,
            reason[:500],
        )

    async def upload_for_placeholder(
        self, user_id: UUID, placeholder: str
    ) -> asyncpg.Record | None:
        return await self._pool().fetchrow(
            """
            SELECT id, local_path, object_key, size_bytes, sha256, status
            FROM storage_objects
            WHERE user_id = $1
              AND kind = 'upload'
              AND metadata->>'placeholder' = $2
              AND deleted_at IS NULL
            """,
            user_id,
            placeholder,
        )

    async def ready_uploads_for_user(self, user_id: UUID) -> list[asyncpg.Record]:
        return await self._pool().fetch(
            """
            SELECT id, local_path, object_key, size_bytes, sha256
            FROM storage_objects
            WHERE user_id = $1
              AND kind = 'upload'
              AND status = 'ready'
              AND deleted_at IS NULL
            ORDER BY created_at, id
            """,
            user_id,
        )

    async def upsert_artifact(
        self,
        *,
        artifact_id: UUID,
        user_id: UUID,
        job_id: str | None,
        filename: str,
        content_type: str,
        size_bytes: int,
        sha256: str,
        local_path: str,
        object_key: str,
    ) -> None:
        await self._pool().execute(
            """
            INSERT INTO storage_objects (
                id, user_id, job_id, kind, filename, content_type, size_bytes,
                sha256, local_path, object_key, status, verified_at
            ) VALUES (
                $1, $2, $3, 'artifact', $4, $5, $6, $7, $8, $9, 'ready', now()
            )
            ON CONFLICT (user_id, local_path)
                WHERE local_path IS NOT NULL AND deleted_at IS NULL
            DO UPDATE SET
                job_id = COALESCE(EXCLUDED.job_id, storage_objects.job_id),
                size_bytes = EXCLUDED.size_bytes,
                sha256 = EXCLUDED.sha256,
                object_key = EXCLUDED.object_key,
                status = 'ready',
                verified_at = now()
            """,
            artifact_id,
            user_id,
            job_id[:96] if job_id else None,
            filename[:255],
            content_type[:255],
            size_bytes,
            sha256,
            local_path,
            object_key,
        )

    async def artifact_for_local_path(
        self, user_id: UUID, local_path: str
    ) -> asyncpg.Record | None:
        return await self._pool().fetchrow(
            """
            SELECT id, filename, content_type, object_key, size_bytes, sha256
            FROM storage_objects
            WHERE user_id = $1
              AND local_path = $2
              AND kind = 'artifact'
              AND status = 'ready'
              AND deleted_at IS NULL
            """,
            user_id,
            local_path,
        )


async def apply_migrations(database_url: str, migrations_dir: Path) -> list[int]:
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    connection = await asyncpg.connect(database_url, command_timeout=60)
    applied: list[int] = []
    lock_name = "ngopilot_schema_migrations"
    try:
        await connection.execute("SELECT pg_advisory_lock(hashtext($1))", lock_name)
        exists = await connection.fetchval(
            "SELECT to_regclass('public.schema_migrations') IS NOT NULL"
        )
        known: set[int] = set()
        if exists:
            rows = await connection.fetch("SELECT version FROM schema_migrations")
            known = {row["version"] for row in rows}
        for path in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
            version = int(path.name.split("_", 1)[0])
            if version in known:
                continue
            await connection.execute(path.read_text(encoding="utf-8"))
            applied.append(version)
    finally:
        try:
            await connection.execute("SELECT pg_advisory_unlock(hashtext($1))", lock_name)
        finally:
            await connection.close()
    return applied
