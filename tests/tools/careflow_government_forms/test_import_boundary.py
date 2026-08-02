from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN_TOOL_MODULES = {
    "careflow_paper_forms_to_excel",
    "careflow_meeting_notes",
    "roster_copilot",
}


def test_tool_has_no_cross_tool_imports() -> None:
    tool_root = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "ngopilot_mcp"
        / "tools"
        / "careflow_government_forms"
    )
    for path in tool_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any(
            forbidden in module
            for forbidden in FORBIDDEN_TOOL_MODULES
            for module in imported
        ), path


def test_host_import_does_not_load_careflow_app_package() -> None:
    before = set(sys.modules)
    __import__("ngopilot_mcp.tools.careflow_government_forms")
    newly_loaded = set(sys.modules) - before
    assert "app" not in newly_loaded
    assert not any(module.startswith("app.") for module in newly_loaded)
