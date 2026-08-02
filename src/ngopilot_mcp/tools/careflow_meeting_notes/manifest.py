"""Host-safe manifest for the CareFlow meeting-notes MCP tool."""

from ngopilot_mcp.shared.tool_api import ToolManifest

MANIFEST = ToolManifest(
    name="careflow_meeting_notes",
    description=(
        "Convert one local audio recording and one CareFlow report template into "
        "reviewed meeting or home-visit notes. Attach audio_path as an absolute "
        ".mp3, .wav, .m4a, .aac, .flac, or .ogg path and template_path as an "
        "absolute .docx path (or .doc only when "
        "the managed CareFlow worker reports legacy conversion support). Use the "
        "same tool with operation=start, status, review, export, or burn and the "
        "returned job_id. PDF templates, images, and spreadsheets do not belong "
        "to this tool."
    ),
    worker="careflow",
    operations=("start", "status", "review", "export", "burn"),
)
