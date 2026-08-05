"""Host-safe manifest for the CareFlow meeting-notes MCP tool."""

from ngopilot_mcp.shared.tool_api import ToolManifest

MANIFEST = ToolManifest(
    name="careflow_meeting_notes",
    description=(
        "Create reviewed meeting or home-visit notes from one absolute audio "
        "path and one absolute CareFlow DOCX template path. Continue the same "
        "job through status, review, export, or burn. Excludes PDFs, images, and "
        "spreadsheets."
    ),
    worker="careflow",
    operations=("start", "status", "review", "export", "burn"),
)
