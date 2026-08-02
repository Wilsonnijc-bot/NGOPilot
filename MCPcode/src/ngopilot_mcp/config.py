"""Deployment paths and managed runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _absolute_env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    path = Path(value).expanduser() if value else default
    return path.resolve()


def _executable_env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    path = Path(value).expanduser() if value else default
    # A venv Python is commonly a symlink. Resolving it would select the base
    # interpreter and lose the venv's site-packages.
    return Path(os.path.abspath(path))


def _source_default(relative: str) -> Path:
    package_root = Path(__file__).resolve().parent
    bundled = package_root / "payloads" / relative
    if bundled.exists():
        return bundled

    workspace = Path(__file__).resolve().parents[3]
    if relative == "careflow/backend":
        return workspace / "venv" / "CareFlow" / "backend"
    return workspace / "venv" / "RosterCopiilot"


def _managed_python(state_root: Path, runtime: str) -> Path:
    executable = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return state_root / "runtimes" / runtime / ".venv" / executable


@dataclass(frozen=True, slots=True)
class Settings:
    state_root: Path
    careflow_source: Path
    roster_source: Path
    careflow_python: Path
    roster_python: Path
    allowed_input_roots: tuple[Path, ...]
    worker_timeout_seconds: float

    @property
    def database_path(self) -> Path:
        return self.state_root / "jobs.sqlite3"

    @property
    def jobs_root(self) -> Path:
        return self.state_root / "jobs"

    @property
    def careflow_data(self) -> Path:
        return self.state_root / "app-data" / "careflow"

    @property
    def roster_data(self) -> Path:
        return self.state_root / "app-data" / "rostercopiilot"

    @property
    def resources_root(self) -> Path:
        return self.state_root / "resources"

    def initialize_directories(self) -> None:
        directories = (
            self.state_root,
            self.jobs_root,
            self.careflow_data,
            self.roster_data,
            self.resources_root / "careflow",
            self.resources_root / "rostercopiilot",
        )
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            try:
                directory.chmod(0o700)
            except OSError:
                pass


def load_settings() -> Settings:
    state_default = Path.home() / ".ngopilot-mcp"
    state_root = _absolute_env_path("NGOPILOT_MCP_STATE_DIR", state_default)
    roots_value = os.getenv("NGOPILOT_MCP_ALLOWED_INPUT_ROOTS", "")
    roots = tuple(
        Path(item).expanduser().resolve()
        for item in roots_value.split(os.pathsep)
        if item.strip()
    )
    settings = Settings(
        state_root=state_root,
        careflow_source=_absolute_env_path(
            "NGOPILOT_MCP_CAREFLOW_SOURCE",
            _source_default("careflow/backend"),
        ),
        roster_source=_absolute_env_path(
            "NGOPILOT_MCP_ROSTER_SOURCE",
            _source_default("rostercopiilot"),
        ),
        careflow_python=_executable_env_path(
            "NGOPILOT_MCP_CAREFLOW_PYTHON",
            _managed_python(state_root, "careflow"),
        ),
        roster_python=_executable_env_path(
            "NGOPILOT_MCP_ROSTER_PYTHON",
            _managed_python(state_root, "rostercopiilot"),
        ),
        allowed_input_roots=roots,
        worker_timeout_seconds=float(
            os.getenv("NGOPILOT_MCP_WORKER_TIMEOUT_SECONDS", "1800")
        ),
    )
    settings.initialize_directories()
    return settings
