from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = (
    Path(__file__).parents[3] / "src" / "ngopilot_mcp" / "tools" / "roster_copilot"
)


def test_no_tool_to_tool_imports() -> None:
    for source_path in PACKAGE.glob("*.py"):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not (
                    node.module.startswith("ngopilot_mcp.tools.")
                    and ".roster_copilot" not in node.module
                ), f"cross-tool import in {source_path.name}: {node.module}"


def test_only_native_adapter_imports_roster_app() -> None:
    offenders = []
    for source_path in PACKAGE.glob("*.py"):
        if source_path.name == "native_adapter.py":
            continue
        source = source_path.read_text(encoding="utf-8")
        if "from app" in source or "import app" in source:
            offenders.append(source_path.name)
    assert offenders == []
