---
name: careflow-paper-forms-to-excel
description: Convert attached JPG, JPEG, or PNG images of completed CareFlow volunteer-visit forms into a reviewed Excel workbook. Use for paper-form extraction, review, and export; exclude government forms, audio, and existing spreadsheets.
---

# CareFlow Paper Forms to Excel

Call `careflow_paper_forms_to_excel` immediately. Pass every relevant path from `Attachments:` unchanged in `input.image_paths`; never ask the user for those paths.

## Workflow

1. Start with `operation: "start"`, `job_id: null`, a short `input.title`, and the paths in `input.image_paths`.
2. Continue the returned `job_id` according to `next_operations`.
3. Show the returned records. A review must return every record and every `final_fields` value.
4. Obtain explicit user confirmation before calling `operation: "export"`.

Follow the MCP schema for every call.
