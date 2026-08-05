---
name: roster-copilot
description: Use when the user wants to build, revise, review, export, or publish a weekly NGO roster from an HC timetable workbook and an escort-master workbook. Trigger when both workbook roles and the target week are known or can be clarified.
---

# Roster Copilot

Use the `roster_copilot` MCP tool. Treat both workbooks as opaque tool inputs: do not open, parse, or analyze them yourself. Use exact absolute paths from `Local attachment paths (JSON; use exact values):`. Ask one concise question if the HC and escort workbook roles are ambiguous.

## Workflow

1. Start the job with `operation: "start"`, `job_id: null`, and an `input` containing:
   - `hc_workbook_path`: the exact HC timetable path
   - `escort_workbook_path`: the exact escort-master path
   - `week_start`: `YYYY-MM-DD`
   - `changes`: requested changes, or omit it when none were requested
2. Preserve the returned `job_id` and follow the tool's `next_operations`.
3. For `review` and `revalidate`, reuse returned version, hash, idempotency, and audit fields exactly as provided. Never invent or recompute them.
4. `operation: "export"` creates a review draft only; it does not publish the roster.
5. Obtain explicit user confirmation before `operation: "publish"`.
6. For `operation: "get_published"`, provide the required `publication_id`.

The MCP tool schema and returned workflow fields are authoritative for every call.
