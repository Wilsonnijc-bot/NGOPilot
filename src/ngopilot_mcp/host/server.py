"""FastMCP stdio server exposing exactly four stateful tools."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..config import Settings, load_settings
from ..shared.runtime import Runtime
from .registry import load_tools
from .router import Router


def create_server(settings: Settings | None = None) -> FastMCP:
    resolved = settings or load_settings()
    tools = load_tools()
    router = Router(Runtime(resolved), tools)
    server = FastMCP(
        "NGOPilotMCP",
        instructions=(
            "Use the tool matching the file role. Start a job, then call the "
            "same tool with its returned job_id for status, review, export, "
            "or publication operations."
        ),
        log_level="ERROR",
    )

    def make_invoker(tool_name: str):
        async def invoke(
            operation: str,
            job_id: str | None = None,
            request_id: str | None = None,
            input: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
            return await router.call(
                tool_name=tool_name,
                operation=operation,
                job_id=job_id,
                request_id=request_id,
                input_payload=input,
            )

        return invoke

    for registered in tools:
        manifest = registered.manifest
        invoke = make_invoker(manifest.name)

        invoke.__name__ = manifest.name
        invoke.__doc__ = manifest.description
        server.add_tool(
            invoke,
            name=manifest.name,
            description=manifest.description,
            structured_output=True,
        )
    return server
