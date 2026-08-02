"""Static, host-safe manifest for the government-forms workflow."""

from ngopilot_mcp.shared.tool_api import ToolManifest

MANIFEST = ToolManifest(
    name="careflow_government_forms",
    description=(
        "Fill a bundled Hong Kong government welfare-form PDF from elder "
        "information, with mandatory human review before export. Call "
        "list_templates first or start with a template_id and exactly one "
        "source: non-empty text, one absolute .jpg/.jpeg/.png path (HEIC/HEIF "
        "only when discovery reports support), or an elder_profile object. "
        "This tool does not accept a blank government PDF, completed volunteer "
        "visit forms, audio, Word, or Excel files. Continue the same job with "
        "status, review using every preview field, then export."
    ),
    worker="careflow",
    operations=("list_templates", "start", "status", "review", "export"),
)
