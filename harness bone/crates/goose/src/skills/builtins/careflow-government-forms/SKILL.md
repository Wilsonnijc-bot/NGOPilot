---
name: careflow-government-forms
description: Fill a supported Hong Kong welfare or government form from text, an elder profile, or an attached source image. Use for template discovery, review, and export; exclude arbitrary blank PDFs.
---

# CareFlow Government Forms

Call `careflow_government_forms` directly. For an image source, pass the relevant path from `Attachments:` unchanged as `source.image_path`; never ask the user for that path.

## Workflow

1. If `template_id` is unclear, call `list_templates`; otherwise start directly with exactly one text, image, or elder-profile source.
2. Continue the returned `job_id` according to `next_operations` and show the preview.
3. A review must return every preview field in `input.field_values`.
4. Obtain explicit user confirmation before calling `operation: "export"`.

Follow the MCP schema and returned template list.
