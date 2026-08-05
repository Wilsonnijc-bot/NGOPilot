---
name: roster-copilot
description: Build, revise, review, export, or publish a weekly NGO roster from an HC timetable workbook and an escort-master workbook. Use when both roles and the target week are known or can be clarified.
---

# Roster Copilot

Call `roster_copilot` once the workbook roles and target week are known. Map the paths from `Attachments:` directly to `hc_workbook_path` and `escort_workbook_path`; ask only if a role or week is ambiguous.

## Workflow

1. Start with `operation: "start"`, `job_id: null`, both mapped paths, `week_start`, and any requested changes.
2. Continue the returned `job_id` according to `next_operations`.
3. For `review` and `revalidate`, reuse returned version, hash, idempotency, and audit fields exactly as provided. Never invent or recompute them.
4. `operation: "export"` creates a review draft only; it does not publish the roster.
5. Obtain explicit user confirmation before `operation: "publish"`.
6. For `operation: "get_published"`, provide the required `publication_id`.

Follow the MCP schema and returned workflow fields.
