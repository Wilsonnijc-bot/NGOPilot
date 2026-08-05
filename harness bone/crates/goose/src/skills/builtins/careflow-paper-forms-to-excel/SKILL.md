---
name: careflow-paper-forms-to-excel
description: Use when the user wants to convert photos or scans of completed CareFlow volunteer-visit forms into a reviewed Excel workbook. Trigger for attached JPG, JPEG, or PNG paper forms; do not use for government forms, audio, or existing spreadsheets.
---

# CareFlow Paper Forms to Excel

Use the `careflow_paper_forms_to_excel` MCP tool. Treat every attached image as opaque tool input: never inspect it, OCR it, or refuse because the language model lacks vision. Read its exact absolute path from `Local attachment paths (JSON; use exact values):`. If no local path exists, ask the user to attach the original image file.

## Workflow

1. Start the job with:
   - `operation: "start"`
   - `job_id: null`
   - `input.title`: the user's title, or a short descriptive title
   - `input.image_paths`: all relevant absolute image paths, unchanged
2. Preserve the returned `job_id` and follow the tool's `next_operations` for status and review.
3. Present the returned records to the user. A review call must include every returned record and all 13 fields in `final_fields`: `elder_name`, `elder_age`, `elder_gender`, `elder_phone`, `elder_address`, `living_alone`, `visit_date`, `volunteer_name`, `duration_minutes`, `mood`, `health_concerns`, `follow_up_needed`, and `follow_up_note`.
4. Obtain explicit user confirmation before calling `operation: "export"`.

Do not send government-form images, audio recordings, or spreadsheet files to this tool. The MCP tool schema is authoritative for every call.
