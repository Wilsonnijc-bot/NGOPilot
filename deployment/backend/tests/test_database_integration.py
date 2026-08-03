from __future__ import annotations

import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest

from ngopilot_gateway.config import Settings
from ngopilot_gateway.db import Database, apply_migrations

DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not set")
@pytest.mark.asyncio
async def test_migration_auth_ticket_and_chat_projection() -> None:
    assert DATABASE_URL is not None
    migrations = Path(__file__).resolve().parents[1] / "ngopilot_gateway" / "migrations"
    assert await apply_migrations(DATABASE_URL, migrations) == [1]
    assert await apply_migrations(DATABASE_URL, migrations) == []

    settings = Settings(
        app_env="test",
        database_url=DATABASE_URL,
        public_api_url="http://127.0.0.1:8080",
        allowed_origins="http://127.0.0.1:4173",
    )
    database = Database(settings)
    await database.connect()
    try:
        email = f"integration-{uuid4()}@example.test"
        user = await database.create_user(email, "x" * 32, "Integration User")
        auth_token = hashlib.sha256(b"auth-token").digest()
        auth_session = await database.create_auth_session(user["id"], auth_token, 1)
        context = await database.auth_context(auth_token)
        assert context is not None
        assert context["user_id"] == user["id"]

        ticket = hashlib.sha256(b"ws-ticket").digest()
        await database.create_ws_ticket(user["id"], auth_session["id"], ticket, 60)
        assert await database.consume_ws_ticket(ticket) is not None
        assert await database.consume_ws_ticket(ticket) is None

        await database.upsert_chat_session(user["id"], "agent-session-1", "openai/gpt-5.6-luna")
        await database.record_message(
            user["id"], "agent-session-1", "user", "prompt", [{"text": "Hello"}]
        )
        count = await database._pool().fetchval(
            "SELECT count(*) FROM messages WHERE user_id = $1", user["id"]
        )
        assert count == 1
    finally:
        await database.close()
