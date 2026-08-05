"""Static, host-safe manifest for the government-forms workflow."""

from ngopilot_mcp.shared.tool_api import ToolManifest

MANIFEST = ToolManifest(
    name="careflow_government_forms",
    description=(
        "Fill a supported Hong Kong welfare form from text, one absolute image "
        "path, or an elder profile. List templates when needed, then continue "
        "the same job through complete review and export. Excludes blank PDFs, "
        "volunteer visit forms, audio, Word, and Excel files."
    ),
    worker="careflow",
    operations=("list_templates", "start", "status", "review", "export"),
)
