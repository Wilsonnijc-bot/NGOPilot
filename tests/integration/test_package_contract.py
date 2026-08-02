from __future__ import annotations

import ast
import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest

from ngopilot_mcp.config import Settings
from ngopilot_mcp.host.registry import TOOL_MODULES, load_tools
from ngopilot_mcp.host.server import create_server

EXPECTED_TOOLS = (
    "careflow_paper_forms_to_excel",
    "careflow_meeting_notes",
    "careflow_government_forms",
    "roster_copilot",
)


def _settings(tmp_path: Path) -> Settings:
    package = Path(__file__).resolve().parents[2] / "src" / "ngopilot_mcp"
    settings = Settings(
        state_root=tmp_path / "state",
        careflow_source=package / "payloads" / "careflow" / "backend",
        roster_source=package / "payloads" / "rostercopiilot",
        careflow_python=Path(sys.executable),
        roster_python=Path(sys.executable),
        allowed_input_roots=(),
        worker_timeout_seconds=5,
    )
    settings.initialize_directories()
    return settings


def test_static_registry_exposes_exactly_four_independent_tools() -> None:
    registered = load_tools()

    assert TOOL_MODULES == EXPECTED_TOOLS
    assert tuple(item.manifest.name for item in registered) == EXPECTED_TOOLS
    assert len({id(item.controller) for item in registered}) == 4


@pytest.mark.asyncio
async def test_fastmcp_advertises_exactly_four_tools(tmp_path: Path) -> None:
    server = create_server(_settings(tmp_path))

    tools = await server.list_tools()

    assert tuple(tool.name for tool in tools) == EXPECTED_TOOLS
    for tool in tools:
        assert set(tool.inputSchema["properties"]) == {
            "operation",
            "job_id",
            "request_id",
            "input",
        }
        assert "absolute" in (tool.description or "").lower() or tool.name == (
            "careflow_government_forms"
        )


def test_tool_sources_have_no_cross_tool_or_host_native_imports() -> None:
    tools_root = Path(__file__).resolve().parents[2] / "src" / "ngopilot_mcp" / "tools"
    violations: list[str] = []

    for tool_name in EXPECTED_TOOLS:
        tool_root = tools_root / tool_name
        for source in tool_root.rglob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
            for node in ast.walk(tree):
                imported = _imported_modules(
                    node,
                    package=f"ngopilot_mcp.tools.{tool_name}",
                )
                for module in imported:
                    if module.startswith(
                        "ngopilot_mcp.tools."
                    ) and not module.startswith(f"ngopilot_mcp.tools.{tool_name}"):
                        violations.append(f"{source}:{node.lineno}: {module}")
                    if source.name != "native_adapter.py" and (
                        module == "app" or module.startswith("app.")
                    ):
                        violations.append(f"{source}:{node.lineno}: {module}")

    assert violations == []


def test_vendor_payload_contains_only_pinned_source_and_required_assets() -> None:
    package_root = Path(__file__).resolve().parents[2] / "src" / "ngopilot_mcp"
    manifest = tomllib.loads(
        (package_root / "vendor.lock.toml").read_text(encoding="utf-8")
    )
    allowed_non_python = {
        Path("payloads/careflow/LICENSE"),
    }
    app_roots: list[Path] = []
    expected_counts: dict[Path, int] = {}
    for application in manifest["applications"]:
        payload_root = Path(application["payload_path"])
        install_root = Path(application["install_root"])
        app_roots.append(payload_root / application["import_root"])
        allowed_non_python.add(install_root / "pyproject.toml")
        allowed_non_python.update(
            install_root / resource["path"]
            for resource in application["required_resources"]
        )
        expected_counts[payload_root] = application["payload_file_count"]

    unexpected: list[str] = []
    for payload_root, expected_count in expected_counts.items():
        root = package_root / payload_root
        files = sorted(path for path in root.rglob("*") if path.is_file())
        source_files = [
            path
            for path in files
            if not any(
                part in {"__pycache__", "build", "logs"} or part.endswith(".egg-info")
                for part in path.relative_to(root).parts
            )
            and path.suffix.lower() not in {".pyc", ".pyo"}
        ]
        assert len(source_files) == expected_count
        for path in source_files:
            relative = path.relative_to(package_root)
            if relative in allowed_non_python:
                continue
            if path.suffix == ".py" and any(
                relative.is_relative_to(app_root) for app_root in app_roots
            ):
                continue
            unexpected.append(relative.as_posix())

    assert unexpected == []


def _imported_modules(node: ast.AST, *, package: str) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        if node.level == 0:
            return [node.module] if node.module else []
        relative = "." * node.level + (node.module or "")
        return [importlib.util.resolve_name(relative, package)]
    return []
