from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ngopilot_mcp.config import Settings
from ngopilot_mcp.shared.workers.client import WorkerClient
from ngopilot_mcp.shared.workers.protocol import WorkerRequest


def test_worker_uses_managed_site_packages_before_host_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        state_root=tmp_path / "state",
        careflow_source=tmp_path,
        roster_source=tmp_path,
        careflow_python=Path(sys.executable),
        roster_python=Path(sys.executable),
        allowed_input_roots=(),
        worker_timeout_seconds=5,
    )
    settings.initialize_directories()
    request = WorkerRequest(
        tool_name="careflow_government_forms",
        operation="list_templates",
        job_id="discovery",
        payload={},
        job_root=str(tmp_path / "job"),
        app_data_root=str(settings.careflow_data),
        resources_root=str(settings.resources_root / "careflow"),
        application_source=str(settings.careflow_source),
    )
    observed: dict[str, object] = {}

    def fake_run(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        observed["command"] = command
        observed["env"] = kwargs["env"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"ok": True, "result": {"templates": []}}),
            stderr="",
        )

    monkeypatch.setenv("PYTHONPATH", "/host/site-packages")
    monkeypatch.setenv("PYTHONHOME", "/host/python")
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = WorkerClient(settings)._run(
        Path(sys.executable),
        "ngopilot_mcp.workers.careflow_worker",
        request,
        tmp_path / "job" / "logs" / "worker.log",
    )

    command = observed["command"]
    assert isinstance(command, list)
    assert command[1:3] == ["-I", "-c"]
    assert "sys.path.append" in command[3]
    assert command[-1] == "ngopilot_mcp.workers.careflow_worker"
    env = observed["env"]
    assert isinstance(env, dict)
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert result == {"templates": []}
