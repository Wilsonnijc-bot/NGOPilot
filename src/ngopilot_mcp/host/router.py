"""Tool call validation, per-job serialization, and error projection."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from pydantic import ValidationError

from ..shared.errors import ToolError
from ..shared.runtime import Runtime
from ..shared.tool_api import ToolCall, ToolExecution
from .registry import RegisteredTool


class Router:
    def __init__(self, runtime: Runtime, tools: tuple[RegisteredTool, ...]):
        self.runtime = runtime
        self.tools = {item.manifest.name: item for item in tools}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def call(
        self,
        *,
        tool_name: str,
        operation: str,
        job_id: str | None,
        request_id: str | None,
        input_payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        registered = self.tools[tool_name]
        if operation not in registered.manifest.operations:
            return self._error(
                tool_name,
                operation,
                job_id,
                ToolError(
                    "UNKNOWN_OPERATION",
                    f"Unsupported operation '{operation}' for {tool_name}.",
                    details={"allowed": list(registered.manifest.operations)},
                ),
            )
        call = ToolCall(
            operation=operation,
            job_id=job_id,
            request_id=request_id,
            input=input_payload or {},
        )
        lock_key = job_id or f"{tool_name}:{request_id or 'new'}"
        async with self._locks[lock_key]:
            try:
                execution = await registered.controller.execute(call, self.runtime)
                if not isinstance(execution, ToolExecution):
                    raise TypeError(
                        f"{tool_name} controller returned {type(execution).__name__}"
                    )
                if not execution.tool:
                    execution.tool = tool_name
                return execution.as_dict()
            except ValidationError as exc:
                return self._error(
                    tool_name,
                    operation,
                    job_id,
                    ToolError(
                        "INVALID_REQUEST",
                        "The tool request failed schema validation.",
                        details={"errors": exc.errors(include_url=False)},
                    ),
                )
            except ToolError as exc:
                return self._error(tool_name, operation, job_id, exc)
            except Exception as exc:  # noqa: BLE001 - MCP boundary
                return self._error(
                    tool_name,
                    operation,
                    job_id,
                    ToolError(
                        "INTERNAL_ERROR",
                        str(exc) or type(exc).__name__,
                        native_message=str(exc),
                    ),
                )

    @staticmethod
    def _error(
        tool_name: str,
        operation: str,
        job_id: str | None,
        error: ToolError,
    ) -> dict[str, Any]:
        return ToolExecution(
            tool=tool_name,
            operation=operation,
            job_id=job_id,
            state="failed",
            error=error.as_dict(),
        ).as_dict()
