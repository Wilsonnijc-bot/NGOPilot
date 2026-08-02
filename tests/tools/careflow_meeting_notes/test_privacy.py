from __future__ import annotations

import ast
import json
from pathlib import Path

from ngopilot_mcp.tools.careflow_meeting_notes.state import public_session


def test_public_projection_never_persists_raw_transcript_or_vault_reference() -> None:
    secret = "raw transcript that belongs only in the encrypted CareFlow vault"
    result = public_session(
        {
            "native_session_id": 42,
            "session": {
                "id": 42,
                "status": "pending_review",
                "template_contract": {"dynamic_slots": []},
                "slot_content": {},
                "transcript_snippet": "permitted snippet",
                "transcript": secret,
                "raw_transcript": secret,
                "transcript_vault_path": "transcripts/session_42.enc",
                "working_docx_path": "visit_sessions/session_42/work/template.docx",
            },
        },
        mode="internal_meeting",
    )
    encoded = json.dumps(result)
    assert result["transcript_snippet"] == "permitted snippet"
    assert result["mode"] == "internal_meeting"
    assert secret not in encoded
    assert "session_42.enc" not in encoded
    assert "working_docx_path" not in result


def test_only_native_adapter_may_import_careflow_and_no_tool_cross_imports() -> None:
    package = (
        Path(__file__).parents[3] / "src/ngopilot_mcp/tools/careflow_meeting_notes"
    )
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            assert "ngopilot_mcp.tools.careflow_" not in module
            assert "ngopilot_mcp.tools.roster_copilot" not in module
            if module == "app" or module.startswith("app."):
                assert path.name == "native_adapter.py"
