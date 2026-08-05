---
name: careflow-meeting-notes
description: Use when the user wants to turn an audio recording plus a DOCX template into reviewed CareFlow home-visit or internal-meeting notes. Trigger only when the audio and template roles are available or can be clarified.
---

# CareFlow Meeting Notes

Use the `careflow_meeting_notes` MCP tool. Treat the audio recording and DOCX template as opaque tool inputs: do not transcribe the audio or inspect the template yourself. Use exact absolute paths from `Local attachment paths (JSON; use exact values):`; ask one concise question if their roles are ambiguous.

## Workflow

1. Start the job with `operation: "start"`, `job_id: null`, and an `input` containing:
   - `title`: the user's title, or a short descriptive title
   - `mode`: exactly `home_visit` or `internal_meeting`
   - `audio_path`: the exact audio path
   - `template_path`: the exact DOCX template path
2. Preserve the returned `job_id` and follow the tool's `next_operations`.
3. Present the returned review data to the user before submitting `slot_content_final` with `operation: "review"`.
4. Obtain explicit user confirmation before either `operation: "export"` or `operation: "burn"`.

Do not route images, PDFs, or spreadsheets to this workflow. The MCP tool schema is authoritative for every call.
