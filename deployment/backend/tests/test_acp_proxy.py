from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from ngopilot_gateway.acp_proxy import (
    AcpRecorder,
    browser_message,
    extract_jobs,
    isolate_client_request,
)


class RecordingDatabase:
    def __init__(self):
        self.calls: list[tuple[object, ...]] = []

    def __getattr__(self, name: str):
        async def record(*args, **kwargs):
            self.calls.append((name, *args, kwargs))

        return record


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "params", "expected"),
    [
        (
            "_goose/unstable/session/rename",
            {"sessionId": "session-1", "title": "Renamed"},
            "rename_chat_session",
        ),
        (
            "_goose/unstable/session/archive",
            {"sessionId": "session-1"},
            "archive_chat_session",
        ),
        ("session/delete", {"sessionId": "session-1"}, "delete_chat_session"),
    ],
)
async def test_successful_session_mutations_are_projected(
    settings, method: str, params: dict[str, str], expected: str
) -> None:
    database = RecordingDatabase()
    recorder = AcpRecorder(database, settings, uuid4())

    await recorder.client_message({"jsonrpc": "2.0", "id": 7, "method": method, "params": params})
    await recorder.agent_message({"jsonrpc": "2.0", "id": 7, "result": {}})

    assert expected in [str(call[0]) for call in database.calls]


def test_extract_jobs_finds_nested_tool_payload() -> None:
    value = {"content": '{"job_id":"job-123","tool_name":"roster_copilot","state":"ready"}'}

    assert extract_jobs(value) == [
        (
            "job-123",
            "roster_copilot",
            {"job_id": "job-123", "tool_name": "roster_copilot", "state": "ready"},
        )
    ]


def test_oversized_tool_output_is_compacted_for_browser() -> None:
    message = {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "session-1",
            "update": {
                "sessionUpdate": "tool_call_update",
                "toolCallId": "call-1",
                "status": "completed",
                "content": [{"type": "content", "content": {"type": "text", "text": "Done"}}],
                "rawOutput": {"result": "x" * (2 * 1024 * 1024)},
            },
        },
    }
    raw = json.dumps(message)

    compacted = json.loads(browser_message(raw, message))

    assert compacted["params"]["update"]["content"] == message["params"]["update"]["content"]
    assert compacted["params"]["update"]["rawOutput"] == {
        "truncated": True,
        "message": "Oversized tool output omitted from the browser stream.",
    }
    assert len(json.dumps(compacted).encode("utf-8")) < 1024 * 1024


def test_small_agent_message_is_forwarded_unchanged() -> None:
    message = {"jsonrpc": "2.0", "method": "session/update", "params": {"update": {}}}
    raw = json.dumps(message)

    assert browser_message(raw, message) is raw


@pytest.mark.parametrize("method", ["session/new", "session/load"])
def test_session_requests_are_confined_to_tenant_root(method: str) -> None:
    original = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            "cwd": "/data/tenants/another-user",
            "mcpServers": [{"name": "untrusted"}],
            "sessionId": "session-1",
        },
    }

    isolated = isolate_client_request(original, Path("/data/tenants/current-user"))

    assert isolated["params"] == {
        "cwd": "/data/tenants/current-user",
        "mcpServers": [],
        "sessionId": "session-1",
    }
    assert original["params"]["cwd"] == "/data/tenants/another-user"


def test_working_directory_updates_are_confined_to_tenant_root() -> None:
    message = {
        "method": "_goose/unstable/session/working-dir/update",
        "params": {"sessionId": "session-1", "workingDir": "/tmp"},
    }

    isolated = isolate_client_request(message, Path("/data/tenants/current-user"))

    assert isolated["params"]["workingDir"] == "/data/tenants/current-user"
