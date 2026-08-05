"""Host-safe manifest for the RosterCopiilot workflow."""

from ngopilot_mcp.shared.tool_api import ToolManifest

MANIFEST = ToolManifest(
    name="roster_copilot",
    description=(
        "Build one weekly roster from absolute HC-timetable and escort-master "
        "workbook paths. Continue the same job through review, revalidation, "
        "draft export, and confirmed publish. Excludes generic spreadsheets and "
        "CareFlow exports; export never publishes."
    ),
    worker="rostercopiilot",
    operations=(
        "start",
        "status",
        "review",
        "revalidate",
        "export",
        "publish",
        "get_published",
    ),
)
