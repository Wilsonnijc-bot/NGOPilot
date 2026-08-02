# NGOPilotMCP

NGOPilotMCP is one local stdio MCP server exposing four stateful NGO workflow
tools. The package owns file intake, immutable staging, review snapshots, job
state, and delivered artifacts. Its bundled CareFlow and RosterCopiilot
dependencies run in separate managed virtual environments and retain ownership
of extraction, transcription, mapping, scheduling, rendering, export, and
publication logic.

## Requirements

- macOS or Linux with Python 3.11 or newer
- local absolute paths for every file passed over MCP
- network access during the initial bootstrap, unless dependencies are supplied
  through a managed package mirror or offline wheelhouse
- application provider/API configuration already present in the MCP server
  environment

## Install

Build or obtain the `ngopilot_mcp-0.1.0-py3-none-any.whl`, then install it in the
environment used by the private agent:

```bash
python3 -m venv /absolute/path/to/ngopilot-host
/absolute/path/to/ngopilot-host/bin/pip install /absolute/path/to/ngopilot_mcp-0.1.0-py3-none-any.whl
/absolute/path/to/ngopilot-host/bin/ngopilot-mcp bootstrap
```

`bootstrap` creates two application environments under the private state root,
installs their hash-locked dependencies, installs the bundled application
sources, seeds required CareFlow forms/templates, and verifies that each worker
imports the intended application.

The default state root is `~/.ngopilot-mcp`. Set
`NGOPILOT_MCP_STATE_DIR` before bootstrap and server startup to use another
absolute location.

## Private-Agent Configuration

Configure one stdio server. Use absolute executable and state paths:

```json
{
  "mcpServers": {
    "ngopilot": {
      "command": "/absolute/path/to/ngopilot-host/bin/ngopilot-mcp",
      "args": ["serve", "--transport", "stdio"],
      "env": {
        "NGOPILOT_MCP_STATE_DIR": "/absolute/private/ngopilot-state",
        "NGOPILOT_MCP_ALLOWED_INPUT_ROOTS": "/absolute/approved/uploads"
      }
    }
  }
}
```

On macOS/Linux, separate multiple allowed input roots with `:`. If the variable
is omitted, any readable absolute path outside NGOPilotMCP's private job tree is
accepted. Provider credentials and endpoints are inherited from the configured
server environment and are not MCP tool arguments.

Run `ngopilot-mcp list-tools` to inspect the installed tool names, operations,
worker assignments, and routing descriptions.

## Tool Routing

| Tool | Send these inputs | Operations | Delivered output |
|---|---|---|---|
| `careflow_paper_forms_to_excel` | One or more completed volunteer-form scans as `.jpg`, `.jpeg`, or `.png` in `image_paths` | `start`, `status`, `review`, `export` | Reviewed `.xlsx` workbook |
| `careflow_meeting_notes` | One recording in `audio_path` (`.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, `.ogg`) and one report template in `template_path` (`.docx`, or capability-gated `.doc`) | `start`, `status`, `review`, `export`, `burn` | Reviewed `.docx` note |
| `careflow_government_forms` | Exactly one text, structured elder profile, or elder-source image (`.jpg`, `.jpeg`, `.png`; capability-gated `.heic`/`.heif`) plus a listed `template_id` | `list_templates`, `start`, `status`, `review`, `export` | Filled `.pdf` form |
| `roster_copilot` | Named `hc_workbook_path` and `escort_workbook_path` inputs, each `.xlsx` or `.xlsm`, plus `week_start` | `start`, `status`, `review`, `revalidate`, `export`, `publish`, `get_published` | Review and published `.xlsx` workbooks |

Do not route a file by extension alone. In particular, the two Roster workbooks
are distinct named roles, a meeting template is not a government PDF, and the
government workflow accepts a template ID rather than an arbitrary blank PDF.

## Stateful Calls

Every tool uses the same outer call shape:

```json
{
  "operation": "start",
  "job_id": null,
  "request_id": "optional-idempotency-key",
  "input": {}
}
```

Only `start` and read-only discovery omit `job_id`. Continue review, export, and
publication stages by calling the same tool with the returned opaque `job_id`.
Use a stable `request_id` when retrying a mutation. Responses always include the
normalized state, native status/references, review result, valid next
operations, warnings, errors, and verified artifacts. Artifact `path` values
are absolute MCP-owned local paths; the tools do not return binary files or use
HTTP as their primary file transport.

The detailed ownership and runtime design is in
[MCP-pre-build algorithm design plan.md](MCP-pre-build%20algorithm%20design%20plan.md). Tool-specific
contracts and parity criteria are under [docs/implementation](docs/implementation).
