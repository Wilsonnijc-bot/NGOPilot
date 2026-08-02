"""Static registry for four independent tool packages."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from ..shared.tool_api import ToolManifest

TOOL_MODULES = (
    "careflow_paper_forms_to_excel",
    "careflow_meeting_notes",
    "careflow_government_forms",
    "roster_copilot",
)


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    manifest: ToolManifest
    controller: Any


def load_tools() -> tuple[RegisteredTool, ...]:
    registered: list[RegisteredTool] = []
    for name in TOOL_MODULES:
        module = importlib.import_module(f"ngopilot_mcp.tools.{name}")
        manifest = getattr(module, "MANIFEST")
        controller = getattr(module, "CONTROLLER")
        if not isinstance(manifest, ToolManifest):
            raise TypeError(f"{name}.MANIFEST must be a ToolManifest")
        if manifest.name != name:
            raise ValueError(
                f"Tool manifest name mismatch: expected {name}, got {manifest.name}"
            )
        if not callable(getattr(controller, "execute", None)):
            raise TypeError(f"{name}.CONTROLLER must define async execute()")
        registered.append(RegisteredTool(manifest, controller))
    return tuple(registered)
