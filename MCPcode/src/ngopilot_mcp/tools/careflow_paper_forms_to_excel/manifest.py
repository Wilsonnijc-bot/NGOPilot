"""Static, host-safe manifest for the paper-forms workflow."""

from ngopilot_mcp.shared.tool_api import ToolManifest

MANIFEST = ToolManifest(
    name="careflow_paper_forms_to_excel",
    description=(
        "Convert completed CareFlow volunteer-form JPG or PNG images to reviewed "
        "records and Excel. Start with absolute image_paths; continue the same "
        "job through status, complete review, and export. Excludes government "
        "forms, audio, and existing spreadsheets."
    ),
    worker="careflow",
    operations=("start", "status", "review", "export"),
)
