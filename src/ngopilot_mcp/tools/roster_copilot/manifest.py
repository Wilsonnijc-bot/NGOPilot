"""Host-safe manifest for the RosterCopiilot workflow."""

from ngopilot_mcp.shared.tool_api import ToolManifest

MANIFEST = ToolManifest(
    name="roster_copilot",
    description=(
        "Build and review one weekly RosterCopiilot roster from exactly two named "
        "local workbook roles: hc_workbook_path and escort_workbook_path. Both "
        "must be absolute .xlsx or .xlsm paths in the native HC timetable and "
        "escort-master formats; generic spreadsheets and CareFlow exports do not "
        "belong here. Continue the returned job_id with status, review, "
        "revalidate, export (review draft), publish (ready-only final), or "
        "get_published. Export never publishes or distributes the workbook."
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
