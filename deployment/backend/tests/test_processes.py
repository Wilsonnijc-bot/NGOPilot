from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ngopilot_gateway.processes import (
    DISABLED_CLOUD_EXTENSIONS,
    ManagedProcess,
    TenantProcessManager,
    _redact,
)


def _shared_runtime(root: Path, name: str) -> None:
    python = root / "runtimes" / name / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", encoding="utf-8")
    python.chmod(0o755)


def test_tenant_environment_is_isolated_and_uses_shared_runtimes(settings) -> None:
    for runtime in ("careflow", "rostercopiilot"):
        _shared_runtime(settings.ngopilot_mcp_shared_state_dir, runtime)
    for resource in ("form_templates", "templates"):
        path = settings.ngopilot_mcp_shared_state_dir / "app-data" / "careflow" / resource
        path.mkdir(parents=True)
        (path / "seed.txt").write_text("seed", encoding="utf-8")
    (settings.ngopilot_mcp_shared_state_dir / "resources").mkdir()

    manager = TenantProcessManager(settings)
    user_id = uuid4()
    tenant = manager.tenant_root(user_id)
    env = manager._prepare_tenant(tenant)

    workflow = tenant / "workflow"
    assert (workflow / "runtimes" / "careflow" / ".venv").is_symlink()
    assert (workflow / "runtimes" / "rostercopiilot" / ".venv").is_symlink()
    assert (workflow / "app-data" / "careflow" / "templates" / "seed.txt").is_file()
    assert env["GOOSE_PATH_ROOT"] == str(tenant / "goose")
    assert env["NGOPILOT_MCP_STATE_DIR"] == str(workflow)
    assert env["NGOPILOT_MCP_ALLOWED_INPUT_ROOTS"] == str(tenant / "uploads")

    config = json.loads((tenant / "goose" / "config" / "config.yaml").read_text())
    assert config["GOOSE_MODEL"] == "moonshotai/kimi-k2.6"
    assert config["extensions"]["ngopilot"]["cmd"] == "ngopilot-mcp"
    assert all(
        config["extensions"][name] == {"enabled": False}
        for name in DISABLED_CLOUD_EXTENSIONS
    )
    assert settings.openrouter_api_key not in json.dumps(config)


def test_redaction_removes_runtime_secrets() -> None:
    assert _redact("key=secret token=internal", "secret", "internal") == (
        "key=[REDACTED] token=[REDACTED]"
    )


@pytest.mark.asyncio
async def test_release_stops_disconnected_tenant_immediately(settings) -> None:
    manager = TenantProcessManager(settings)
    user_id = uuid4()
    managed = ManagedProcess(
        user_id=user_id,
        process=SimpleNamespace(returncode=None),
        port=1234,
        secret="secret",
        tenant_root=manager.tenant_root(user_id),
        refs=1,
    )
    manager._processes[user_id] = managed
    manager._stop = AsyncMock()

    assert settings.ngopilot_process_idle_seconds == 0
    await manager.release(user_id)

    manager._stop.assert_awaited_once_with(managed)
    assert user_id not in manager._processes
