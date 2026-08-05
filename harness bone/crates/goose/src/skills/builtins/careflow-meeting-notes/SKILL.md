---
name: careflow-meeting-notes
description: Turn an audio recording and DOCX template into reviewed CareFlow home-visit or internal-meeting notes. Use when both file roles are known or can be clarified.
---

# CareFlow Meeting Notes

Call `careflow_meeting_notes` once the file roles and mode are known. Map the paths from `Attachments:` directly to `audio_path` and `template_path`; ask only if a role or mode is ambiguous.

## Workflow

1. Start with `operation: "start"`, `job_id: null`, a short title, mode, and both paths.
2. Continue the returned `job_id` according to `next_operations`.
3. Show the review data before submitting `slot_content_final`.
4. Obtain explicit user confirmation before either `operation: "export"` or `operation: "burn"`.

Follow the MCP schema for every call.
