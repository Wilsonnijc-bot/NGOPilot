from __future__ import annotations

import os
from pathlib import Path

from ngopilot_mcp.config import load_settings


def test_managed_python_path_preserves_venv_symlink(
    tmp_path: Path, monkeypatch
) -> None:
    state = tmp_path / "state"
    managed = state / "runtimes" / "careflow" / ".venv" / "bin" / "python"
    managed.parent.mkdir(parents=True)
    target = tmp_path / "base-python"
    target.write_text("", encoding="utf-8")
    managed.symlink_to(target)
    monkeypatch.setenv("NGOPILOT_MCP_STATE_DIR", str(state))
    monkeypatch.delenv("NGOPILOT_MCP_CAREFLOW_PYTHON", raising=False)

    settings = load_settings()

    assert settings.careflow_python == Path(os.path.abspath(managed))
    assert settings.careflow_python != target.resolve()


def test_unbootstrapped_settings_target_managed_workers(
    tmp_path: Path, monkeypatch
) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("NGOPILOT_MCP_STATE_DIR", str(state))
    monkeypatch.delenv("NGOPILOT_MCP_CAREFLOW_PYTHON", raising=False)
    monkeypatch.delenv("NGOPILOT_MCP_ROSTER_PYTHON", raising=False)

    settings = load_settings()

    assert settings.careflow_python == (
        state / "runtimes" / "careflow" / ".venv" / "bin" / "python"
    )
    assert settings.roster_python == (
        state / "runtimes" / "rostercopiilot" / ".venv" / "bin" / "python"
    )
