"""One-shot subprocess worker client."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ...config import Settings
from ..errors import ToolError
from ..jsonutil import jsonable
from ..tool_api import WorkerName
from .protocol import WorkerRequest

_WORKER_LAUNCHER = (
    "import runpy, sys; "
    "sys.path.append(sys.argv[1]); "
    "runpy.run_module(sys.argv[2], run_name='__main__')"
)


class WorkerClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def call(
        self,
        *,
        worker: WorkerName,
        tool_name: str,
        operation: str,
        job_id: str,
        payload: dict[str, Any],
        job_root: Path,
    ) -> dict[str, Any]:
        if worker == "careflow":
            python = self.settings.careflow_python
            source = self.settings.careflow_source
            app_data = self.settings.careflow_data
            resources = self.settings.resources_root / "careflow"
            module = "ngopilot_mcp.workers.careflow_worker"
        else:
            python = self.settings.roster_python
            source = self.settings.roster_source
            app_data = self.settings.roster_data
            resources = self.settings.resources_root / "rostercopiilot"
            module = "ngopilot_mcp.workers.roster_worker"

        request = WorkerRequest(
            tool_name=tool_name,
            operation=operation,
            job_id=job_id,
            payload=jsonable(payload),
            job_root=str(job_root),
            app_data_root=str(app_data),
            resources_root=str(resources),
            application_source=str(source),
        )
        return await asyncio.to_thread(
            self._run,
            python,
            module,
            request,
            job_root / "logs" / f"{operation}.worker.log",
        )

    def _run(
        self,
        python: Path,
        module: str,
        request: WorkerRequest,
        log_path: Path,
    ) -> dict[str, Any]:
        if not python.exists():
            raise ToolError(
                "WORKER_UNAVAILABLE",
                f"The managed worker Python does not exist: {python}",
            )
        env = os.environ.copy()
        package_src = str(Path(__file__).resolve().parents[3])
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        try:
            completed = subprocess.run(
                [
                    str(python),
                    "-I",
                    "-c",
                    _WORKER_LAUNCHER,
                    package_src,
                    module,
                ],
                input=json.dumps(request.as_dict(), ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.settings.worker_timeout_seconds,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolError(
                "WORKER_TIMEOUT",
                "The application worker exceeded its managed timeout.",
                retryable=True,
            ) from exc

        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(completed.stderr[-1_000_000:], encoding="utf-8")
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ToolError(
                "WORKER_PROTOCOL_ERROR",
                "The worker did not return a valid JSON response.",
                details={
                    "returncode": completed.returncode,
                    "log_path": str(log_path),
                },
            ) from exc
        if completed.returncode != 0 or not response.get("ok"):
            error = response.get("error") or {}
            raise ToolError(
                error.get("code", "NATIVE_OPERATION_FAILED"),
                error.get("message", "The native application operation failed."),
                retryable=bool(error.get("retryable", False)),
                details=error.get("details") or {},
                native_code=error.get("native_code"),
                native_message=error.get("native_message"),
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise ToolError(
                "WORKER_PROTOCOL_ERROR",
                "The worker result must be a JSON object.",
            )
        return result
