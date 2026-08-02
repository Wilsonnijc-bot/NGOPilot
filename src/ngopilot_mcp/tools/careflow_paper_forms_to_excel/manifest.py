"""Static, host-safe manifest for the paper-forms workflow."""

from ngopilot_mcp.shared.tool_api import ToolManifest

MANIFEST = ToolManifest(
    name="careflow_paper_forms_to_excel",
    description=(
        "Convert photos or scans of completed CareFlow volunteer visit forms "
        "into reviewed records and a CareFlow-generated Excel workbook. For "
        "start, provide one or more absolute .jpg, .jpeg, or .png paths in "
        "image_paths. Do not route Excel files, audio recordings, or blank "
        "government PDF forms to this tool. Continue the same job with status, "
        "review, and export; every review must submit all 13 fields."
    ),
    worker="careflow",
    operations=("start", "status", "review", "export"),
)
