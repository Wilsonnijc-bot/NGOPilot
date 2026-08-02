"""Common worker runner that isolates native stdout from MCP protocol output."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from ngopilot_mcp.shared.jsonutil import jsonable
from ngopilot_mcp.shared.workers.protocol import PROTOCOL_VERSION


def run_worker(worker_name: str, allowed_tools: set[str]) -> None:
    try:
        request = json.loads(sys.stdin.read())
        _validate_request(request, allowed_tools)
        _configure_application(worker_name, request)
        result, native_log = _invoke(request)
        _append_log(request, native_log)
        response = {"ok": True, "result": jsonable(result)}
        sys.stdout.write(json.dumps(response, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - worker boundary
        response = {
            "ok": False,
            "error": {
                "code": getattr(exc, "code", "NATIVE_OPERATION_FAILED"),
                "message": str(exc) or type(exc).__name__,
                "retryable": bool(getattr(exc, "retryable", False)),
                "native_code": getattr(exc, "native_code", None),
                "native_message": str(exc),
                "details": jsonable(getattr(exc, "details", {})),
            },
        }
        try:
            _append_log(
                locals().get("request", {}),
                traceback.format_exc(),
            )
        except Exception:
            pass
        sys.stdout.write(json.dumps(response, ensure_ascii=False))
        raise SystemExit(1)


def _validate_request(request: dict[str, Any], allowed_tools: set[str]) -> None:
    if request.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("Unsupported worker protocol version.")
    if request.get("tool_name") not in allowed_tools:
        raise ValueError("This worker does not serve the requested tool.")
    if not isinstance(request.get("payload"), dict):
        raise ValueError("Worker payload must be an object.")


def _configure_application(worker_name: str, request: dict[str, Any]) -> None:
    source = Path(request["application_source"]).resolve()
    app_data = Path(request["app_data_root"]).resolve()
    app_data.mkdir(parents=True, exist_ok=True)
    if worker_name == "careflow":
        import_root = source
        os.environ["DATA_DIR"] = str(app_data)
        os.environ["DATABASE_URL"] = f"sqlite:///{app_data / 'careflow.db'}"
        os.environ.setdefault("ASSET_DIR", str(app_data / "assets"))
    else:
        import_root = source / "backend"
        os.environ["ROSTER_DB_PATH"] = str(app_data / "roster.db")
        os.environ["ROSTER_EXPORT_DIR"] = str(app_data / "exports")
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))
    os.chdir(source)


def _invoke(request: dict[str, Any]) -> tuple[dict[str, Any], str]:
    module = importlib.import_module(
        f"ngopilot_mcp.tools.{request['tool_name']}.native_adapter"
    )
    handler = getattr(module, "handle")
    output = io.StringIO()
    errors = io.StringIO()
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
        result = handler(request["operation"], request["payload"])
    if not isinstance(result, dict):
        raise TypeError("Native adapter handle() must return a dictionary.")
    return result, output.getvalue() + errors.getvalue()


def _append_log(request: dict[str, Any], content: str) -> None:
    if not request or not content:
        return
    root = Path(request["job_root"]).resolve()
    log = root / "logs" / f"{request.get('operation', 'worker')}.native.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        stream.write(content[-1_000_000:])
