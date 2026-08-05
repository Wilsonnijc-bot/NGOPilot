---
name: careflow-government-forms
description: Use when the user wants to fill a supported Hong Kong welfare or government form from text, an elder profile, or an attached source image. Trigger for form filling, template discovery, review, and export; do not use for arbitrary blank PDFs.
---

# CareFlow Government Forms

Use the `careflow_government_forms` MCP tool. Never inspect or OCR an attached source image yourself. Use its exact absolute path from `Local attachment paths (JSON; use exact values):`; CareFlow performs the extraction. If no local path exists, ask the user to attach the original image file.

## Workflow

1. If a supported `template_id` is missing or unclear, call `operation: "list_templates"` with `job_id: null` first.
2. Start with `operation: "start"`, `job_id: null`, the selected `template_id`, the required `use_llm` boolean, and exactly one `source`:
   - Text: `{ "kind": "text", "text": "..." }`
   - Image: `{ "kind": "image", "image_path": "/exact/attachment/path" }`
   - Structured profile: `{ "kind": "elder_profile", "elder_profile": { ... } }`
3. Preserve the returned `job_id` and follow `next_operations`. Present the preview to the user.
4. For `operation: "review"`, submit every field from the preview in `input.field_values`, including unchanged fields.
5. Obtain explicit user confirmation before calling `operation: "export"`.

Do not pass an arbitrary blank PDF as a template. The MCP tool schema and the returned template list are authoritative.
