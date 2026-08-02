from __future__ import annotations

from pathlib import Path

import pytest

from ngopilot_mcp.config import Settings
from ngopilot_mcp.host.registry import RegisteredTool
from ngopilot_mcp.host.router import Router
from ngopilot_mcp.shared.runtime import Runtime
from ngopilot_mcp.shared.tool_api import (
    ToolCall,
    ToolExecution,
    ToolManifest,
)


class Controller:
    async def execute(self, call: ToolCall, runtime: Runtime) -> ToolExecution:
        return ToolExecution(
            tool="example",
            operation=call.operation,
            job_id=call.job_id,
            state="done",
            result={"input": call.input},
        )


@pytest.fixture
def router(tmp_path: Path) -> Router:
    settings = Settings(
        state_root=tmp_path,
        careflow_source=tmp_path,
        roster_source=tmp_path,
        careflow_python=Path("/bin/false"),
        roster_python=Path("/bin/false"),
        allowed_input_roots=(),
        worker_timeout_seconds=1,
    )
    settings.initialize_directories()
    registered = RegisteredTool(
        ToolManifest(
            name="example",
            description="Example",
            worker="careflow",
            operations=("start",),
        ),
        Controller(),
    )
    return Router(Runtime(settings), (registered,))


@pytest.mark.asyncio
async def test_router_returns_structured_execution(router: Router) -> None:
    response = await router.call(
        tool_name="example",
        operation="start",
        job_id=None,
        request_id=None,
        input_payload={"x": 1},
    )
    assert response["tool"] == "example"
    assert response["state"] == "done"
    assert response["result"] == {"input": {"x": 1}}


@pytest.mark.asyncio
async def test_router_rejects_unknown_operation(router: Router) -> None:
    response = await router.call(
        tool_name="example",
        operation="publish",
        job_id=None,
        request_id=None,
        input_payload={},
    )
    assert response["error"]["code"] == "UNKNOWN_OPERATION"
