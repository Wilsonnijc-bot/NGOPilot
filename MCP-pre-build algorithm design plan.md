# NGOPilotMCP Architecture Design Plan

Status: implemented and verified for private deployment; redistribution permission open  
Date: 2026-08-02  
Target: one installable local MCP package, served over stdio  
Source baselines:

- CareFlow `0.4.8`, revision `50e0d2d3efa0662c5452fb5d6038f489fcd2bc7d`
- RosterCopiilot `0.6.0`, revision `312ac9a84968aef71a7180c3ea132fe628275177`

NGOPilotMCP owns every workflow's accepted input, immutable staged files,
intermediate and review results, delivered output artifacts, durable job state,
and recovery. CareFlow and RosterCopiilot are pinned application dependencies
installed inside their managed virtual environments; they own all internal
domain logic, including extraction, transcription, mapping, scheduling,
rendering, review effects, export, and publication. The MCP code controls the
workflow boundary and transport without copying or replacing those algorithms.

Implementation verification at this revision:

- the host and FastMCP discovery expose exactly the four named tools;
- every tool has its own complete eight-module implementation directory and no
  tool imports another tool;
- the two hash-locked managed runtimes bootstrap successfully and an immediate
  second bootstrap is idempotent;
- the authored MCP suite passes with `125 passed` (one expected CareFlow 0.4.8
  `datetime.utcnow()` deprecation warning);
- real-worker lifecycle smokes completed for Paper Forms to Excel, Meeting
  Notes, both Government Forms PDF strategies, and the Roster start/status,
  review-export, and blocked-publication paths.

The remaining release gates are distribution checks, not tool implementation:
run the Paper Forms, Meeting Notes, and Roster lifecycles from the fresh wheel
installation and resolve RosterCopiilot redistribution permission because its
source tree contains no license file.

## 1. Executive Decision

`NGOPilotMCP` is one standalone installable product exposing exactly four
MCP tools:

1. `careflow_paper_forms_to_excel`
2. `careflow_meeting_notes`
3. `careflow_government_forms`
4. `roster_copilot`

The first three tools adapt three CareFlow workflows. The fourth adapts the
complete user-facing weekly workflow in RosterCopiilot. CareFlow's Theta custom
PDF-template authoring remains an internal supporting workflow and does not
become a fifth MCP tool.

Each tool uses the same workflow shape: the caller invokes the same tool with an
`operation` and, after creation, an opaque `job_id`. Repeated calls preserve
the native review, export, and publication stages. Only a start or discovery
operation may omit `job_id`.

The four tool implementations are separate source-code units. Each owns its own
schemas, operation controller, role-specific validation, native adapter, result
interpretation, and tests. A tool implementation may use domain-neutral MCP
infrastructure, but it must not import or call another tool implementation.

Implementation independence does not require four copies of the applications:

- the three CareFlow tools share one managed CareFlow virtual environment,
  worker runtime, and native CareFlow data store;
- the Roster tool uses one separate managed RosterCopiilot virtual environment,
  worker runtime, and native data store;
- all four tools may use the same MCP job database, with every record scoped by
  tool name and job ID.

## 2. Goals and Non-Goals

### 2.1 Goals

- Ship one installable `ngopilot-mcp` package for a private general agent.
- Register exactly four tools over MCP stdio.
- Keep each tool implementation cleanly independent from the other three.
- Preserve the input, output, state transitions, validation behavior, and side
  effects of the corresponding current application workflow.
- Call the original application code directly inside an isolated worker; do not
  call a second web service and do not duplicate its algorithms.
- Accept local absolute paths and return absolute paths for delivered `.xlsx`,
  `.docx`, and `.pdf` artifacts.
- Keep AI-produced drafts behind the same human-review gates as the apps.
- Preserve RosterCopiilot's immutable version/hash checks and ready-only final
  publication.
- Keep jobs, intermediate results, and artifacts durable across MCP restarts.
- Bundle all runtime code, prompts, templates, PDFs, and the fixed roster base
  required by the original implementations.

### 2.2 Non-Goals

- API-key, endpoint, model, or private-agent secret management. The installed
  environment is assumed to provide managed configuration.
- Rebuilding either frontend or exposing FastAPI/Uvicorn ports.
- Changing AI prompts, extraction quality, scheduling rules, mapping logic, or
  document-rendering behavior.
- Remote upload, URL download, object storage, or HTTP MCP transport in the
  first release.
- Automatic distribution of exported or published files to staff.
- CareFlow Theta template authoring in the first release.
- RosterCopiilot support routes such as generic workbook imports, compatibility
  schedulers, benchmarks, and generic exports.
- Roster master-data administration as an MCP surface. The existing persisted
  master data remains an internal dependency of the roster workflow.

## 3. Source-of-Truth Workflows

The adapters are based on active service code, not historical README claims or
frontend labels.

| MCP tool | Original orchestration boundary | Native persistence | Final artifact |
|---|---|---|---|
| `careflow_paper_forms_to_excel` | `volunteer_form.create_batch`, `add_photos`, `run_extraction`, `review_record`; `excel_export.export_batch` | `VolunteerBatch`, `VolunteerRecord`, `FieldCorrection` | `.xlsx` |
| `careflow_meeting_notes` | `home_visit.create_session`, `run_phase1`, `run_phase2`, `burn_transcript` | `VisitSession` plus encrypted transcript vault | `.docx` |
| `careflow_government_forms` | welfare profile extractor, `map_elder_to_template`, `fill_form` | no native job record; MCP owns the durable job | `.pdf` |
| `roster_copilot` | weekly demo builder, scheduler, export preflight, durable review services, review export, publication services | `WeeklyRunRecord` and immutable versions in `RosterStore` | review/final `.xlsx` |

The Roster tool targets the durable user-facing workflow under
`backend/app/api/demo.py`, not the older support endpoints under
`/api/import`, `/api/schedule`, or generic `/api/export`.

The two managed application runtimes use different native boundaries:

- CareFlow tool adapters call the relevant original service functions directly.
  Its FastAPI handlers delegate long work to in-process
  `BackgroundTasks`, which are not a durable execution boundary for stdio
  jobs.
- The Roster adapter reuses the existing `app.api.demo` facade and its
  service calls directly, without ASGI or an HTTP request. This preserves
  upload validation, canonical response assembly, compare-and-swap decisions,
  and publication compensation.

If route-only code must be separated, it may be extracted into a
packaging-neutral facade only when parity tests show that domain behavior has
not changed.

## 4. Runtime Topology and Packaging Constraint

Both current projects install a top-level Python package named `app`:

- CareFlow: `backend/pyproject.toml` includes `app*`.
- RosterCopiilot: `pyproject.toml` includes `app*` from `backend/`.

Installing both backend wheels into one interpreter would collide on modules
such as `app.main`, `app.models`, and
`app.services.excel_export`. Checked-in virtual environments are not
distributable because they contain machine-specific links and do not represent
a portable locked dependency set.

The process topology is therefore:

```text
General agent
    |
    | MCP stdio
    v
NGOPilotMCP host
    +- tool registry and request routing
    +- shared MCP job store, staging, and artifact registry
    |
    +- CareFlow worker / managed CareFlow venv
    |    +- careflow_paper_forms_to_excel adapter
    |    +- careflow_meeting_notes adapter
    |    +- careflow_government_forms adapter
    |
    +- RosterCopiilot worker / managed Roster venv
         +- roster_copilot adapter
```

The worker boxes represent worker types and managed environments, not persistent
daemons. The host starts one subprocess for each native call and that process
loads only the requested adapter.

The outer host never imports either dependency's `app` package. Each worker
starts with the correct Python executable, import root, application data root,
and resource root before it imports its assigned application.

No HTTP request is made between components. The host sends a versioned private
JSON request to the appropriate worker. The worker loads only the requested
tool's native adapter, calls the original orchestration, and returns a JSON
response. Worker stdout and stderr are captured into job logs and can never
corrupt MCP's stdout protocol stream.

The CareFlow worker entry point can dispatch any of the three CareFlow adapters
because they depend on the same application and import namespace. Their source
modules remain independent even though the worker type, managed venv, and native
database are shared.

## 5. Standalone Package Layout

The package is organized around four complete tool implementation directories.
Tool-specific contracts and adapters are kept beside their controllers instead
of being split across shared `contracts/` and `tools/` trees.

```text
NGOPilotMCP/
  pyproject.toml
  README.md

  src/ngopilot_mcp/
    __init__.py
    __main__.py
    config.py
    bootstrap.py
    vendor.lock.toml

    vendor_wheels/
      careflow_backend-0.4.8-py3-none-any.whl
      roster_copiilot-0.6.0-py3-none-any.whl

    host/
      server.py
      registry.py
      router.py

    shared/
      errors.py
      jsonutil.py
      runtime.py
      tool_api.py
      jobs/
        store.py
      files/
        staging.py
        validation.py
        artifacts.py
      workers/
        protocol.py
        client.py

    tools/
      careflow_paper_forms_to_excel/
        __init__.py
        manifest.py
        schemas.py
        controller.py
        validation.py
        native_adapter.py
        state.py
        artifacts.py

      careflow_meeting_notes/
        __init__.py
        manifest.py
        schemas.py
        controller.py
        validation.py
        native_adapter.py
        state.py
        artifacts.py

      careflow_government_forms/
        __init__.py
        manifest.py
        schemas.py
        controller.py
        validation.py
        native_adapter.py
        state.py
        artifacts.py

      roster_copilot/
        __init__.py
        manifest.py
        schemas.py
        controller.py
        validation.py
        native_adapter.py
        state.py
        artifacts.py

    workers/
      base.py
      careflow_worker.py
      roster_worker.py

    runtime_locks/
      careflow.lock
      rostercopiilot.lock

    payloads/
      careflow/
        backend/
      rostercopiilot/
        backend/
        docs/

  docs/implementation/
    CareFlow_Paper_Forms_To_Excel_MCP_Implementation_Plan.md
    CareFlow_Meeting_Notes_MCP_Implementation_Plan.md
    CareFlow_Government_Forms_MCP_Implementation_Plan.md
    Roster_Copilot_MCP_Implementation_Plan.md

  tests/
    shared/
    tools/
      careflow_paper_forms_to_excel/
      careflow_meeting_notes/
      careflow_government_forms/
      roster_copilot/
    integration/
```

This is the implemented source layout. The payload manifest, locally bundled
application wheels, generated-source cleanup, and package-data allowlist are in
place. The rebuilt outer wheel contains the mandatory assets/locks and no
generated build, egg-info, bytecode, or cache entries. Installed-wheel
representative tool lifecycles remain a release-close item.

The verified rebuilt wheel SHA-256 is
`f11ead41ef81515395297d04e296e1383e38a5e5e56b59652e9ecdf14e561036`.

### 5.1 Tool-Code Independence Rules

1. A directory under `src/ngopilot_mcp/tools/` may not import another tool
   directory.
2. Each tool owns its public schemas, operation dispatch, file-role rules,
   native-call adapter, native-state interpretation, artifact semantics, and
   tool-specific tests.
3. `native_adapter.py` is worker-only. Host registration and schema
   discovery must not import CareFlow or RosterCopiilot.
4. Shared code must be domain-neutral. It may implement envelopes, job and
   operation rows, idempotent replay, per-job locks, staging, hashing, artifact
   records, worker transport, and failure checkpointing. It may not contain CareFlow field lists, Roster review
   rules, tool operation matrices, or native call chains.
5. A change to one tool's contract or algorithm adapter must not require edits
   to another tool directory.
6. Similar tool-specific wrapper code may remain duplicated when extracting it
   would create coupling or hide the native workflow boundary.
7. Tests enforce the dependency rule with an import-boundary check and by
   running every tool suite independently.

The implemented host loads a host-safe `ToolManifest` and a controller exposing
`async execute(call, runtime)`. Each controller owns its schema validation and
response projection while the shared `ToolRuntime` supplies jobs, staging,
worker dispatch, operation replay, and artifact promotion. This interface
standardizes transport only; it does not standardize domain payloads.

### 5.2 Dependency and Asset Manifests

The packaged `runtime_locks/*.lock` files pin every installed dependency with
hashes. Their verified SHA-256 values at this revision are
`128caf8ac5c3ed069195aaf2668f12af6ccab065b384f294e26d5300d46f6142`
for `careflow.lock` and
`830a09446b0ea349b888b1d6455785758976b23e087810e55ec84e55b6590d84`
for `rostercopiilot.lock`. The implemented `vendor.lock.toml` payload manifest
records, for each embedded application:

- application version and exact source revision;
- hashes of bundled source and runtime assets;
- locked Python dependency versions and wheel hashes;
- expected import root and required resource paths;
- patch inventory, which must remain empty for algorithms and explicit for any
  packaging-only compatibility shim.

CareFlow's current wheel configuration omits runtime data, so the package must
explicitly include:

- visit-note prompt text files;
- the default volunteer Excel template;
- five welfare-form JSON definitions;
- five matching source PDFs;
- any font/resource required by the current PDF implementation.

RosterCopiilot resolves its fixed division template outside its Python package
at `docs/照顧員工作分工表2026(HKU).xlsx`. The source-tree geometry must be
preserved, or the worker must inject a packaging-only resource path before
calling the original orchestration. The workbook is mandatory runtime data.

The release wheel must exclude nested `.git` directories, frontend code, local
databases, uploaded files, exports, caches, logs, vendored `build/lib` trees,
and `*.egg-info` metadata. Those generated files have been removed from the
source payload, package data is allowlisted, and the rebuilt wheel inspection
passes. Licenses and notices must be retained; CareFlow includes a license,
while the RosterCopiilot payload currently has no source license file to retain.

## 6. Installation and Runtime State

### 6.1 Distribution and Bootstrap

The deliverable is one package named `ngopilot-mcp` with this console entry
point:

```text
ngopilot-mcp serve --transport stdio
```

The host pins the official Python MCP SDK at `mcp==1.29.0` and Pydantic at
`pydantic==2.13.4`.
FastMCP advertises the common envelope, while each controller applies its strict
operation-specific Pydantic union before any native call. The host registers
tools only and starts no HTTP server.

The package owns two managed runtime environments beneath its private state
root:

```text
<state>/runtimes/careflow/.venv/
<state>/runtimes/rostercopiilot/.venv/
```

The source repositories' existing `.venv` directories are never copied. On
bootstrap, NGOPilotMCP creates fresh environments using the supported Python
3.11+ interpreter and installs:

- the pinned CareFlow application dependency and CareFlow dependency lock into
  the CareFlow venv;
- the pinned RosterCopiilot application dependency and Roster dependency lock
  into the Roster venv.

The worker-side MCP modules are loaded from the installed outer package by an
isolated Python launcher that appends the outer package path after the managed
venv's site-packages. `PYTHONPATH` and `PYTHONHOME` are removed at this boundary,
so host dependencies cannot shadow either runtime's hash-locked dependencies;
the MCP modules are not copied into either application venv.
The implemented bootstrap verifies application versions, hashed locks,
mandatory assets, `app` import provenance, and writable managed roots. Source
tree and lock fingerprints make a second bootstrap idempotent and force
reinstallation after a payload change. Optional-format capability reporting and
per-tool readiness advertisement are controller/validation concerns rather
than bootstrap registration states.

The current locks still install from package indexes. A fully offline build
therefore remains a later distribution variant requiring platform-specific
wheelhouses in addition to the outer wheel and embedded application payloads.
The first supported target is the private agent's macOS environment.

### 6.2 Runtime State

NGOPilotMCP owns the state root and all caller-visible workflow records. The
shared database and directories are strictly namespaced, so sharing
infrastructure does not couple the four tool implementations.

```text
<state>/
  jobs.sqlite3

  jobs/
    careflow_paper_forms_to_excel/<job_id>/
      manifest.json
      inputs/
      intermediate/
      outputs/
      logs/
    careflow_meeting_notes/<job_id>/
      manifest.json
      inputs/
      intermediate/
      outputs/
      logs/
    careflow_government_forms/<job_id>/
      manifest.json
      inputs/
      intermediate/
      outputs/
      logs/
    roster_copilot/<job_id>/
      manifest.json
      inputs/
      intermediate/
      outputs/
      logs/

  app-data/
    careflow/
      careflow.db
      uploads/
      exports/
      transcripts/
      templates/
      form_templates/
      welfare_outputs/
    rostercopiilot/
      roster.db
      exports/

  runtimes/
    careflow/.venv/
    rostercopiilot/.venv/

  resources/
    careflow/
    rostercopiilot/
```

Ownership is divided as follows:

| State | Owner and rule |
|---|---|
| Source path metadata and staged copies | MCP; source files are never mutated |
| Intermediate extraction/mapping/schedule/review snapshots | MCP; persisted in namespaced job state for review and recovery |
| Native database rows and encrypted transcript vault | Original application dependency; stored under MCP-managed `app-data/` |
| Delivered artifacts and their hashes | MCP; verified and snapshotted under the job's `outputs/` directory |
| Native working/export files | Original dependency while its operation runs; retained only as native references or internal app data |
| Job lifecycle, operation replay, in-process locks, and failure checkpointing | MCP; cross-process leases and automatic crash recovery are not implemented |

When a native application generates a file, the tool adapter validates it and
copies or atomically promotes an immutable delivered copy into the job's
`outputs/` directory. MCP returns that absolute path. Any original native
path remains in native metadata for traceability, not as the transport contract.

`jobs.sqlite3` is shared infrastructure. Each job row contains `tool_name` and
`job_id`; operation and artifact rows reference that job by foreign key.
Intermediate tool results live in the namespaced job result or job directory.
Tool-specific state interpretation stays in that tool's `state.py` module, and
controllers always resolve jobs with both public tool name and job ID.

Before importing CareFlow, the worker sets absolute `DATA_DIR` and
`DATABASE_URL` values and seeds required resources into the managed
CareFlow root. Before importing RosterCopiilot, its worker sets absolute
`ROSTER_DB_PATH` and `ROSTER_EXPORT_DIR` values. These values are
fixed for the worker lifetime.

Bundled defaults are copied on first initialization using versioned resource
manifests. Upgrades never overwrite user-created templates, databases, jobs, or
artifacts without an explicitly designed and tested migration.

## 7. Shared MCP Contract

### 7.1 Request Envelope

Each registered tool uses the same outer request shape and a tool-specific
payload:

```json
{
  "operation": "start",
  "job_id": null,
  "request_id": "optional-caller-idempotency-key",
  "input": {}
}
```

Rules:

- `operation` is required.
- `job_id` is omitted or null only for `start` and non-mutating
  discovery calls.
- The server generates job IDs; callers do not choose filesystem names.
- `request_id` is optional for reads and required or strongly recommended
  for retryable mutations.
- Unknown fields are rejected and operation payloads use strict schemas.
- File roles use explicit names such as `audio_path`,
  `template_path`, `hc_workbook_path`, and
  `escort_workbook_path`. There is no ambiguous generic `files` input.

Each schema is a discriminated union on `operation`. If a client renders
unions poorly, the implementation may expose the same strict semantic contract
with flat operation-specific validation; it must not loosen validation.

Tool descriptions make file routing clear before a call:

| Tool | Files the agent should attach | Files it must not route here |
|---|---|---|
| `careflow_paper_forms_to_excel` | one or more photos/scans of completed volunteer visit forms | Excel workbooks, audio, blank government PDFs |
| `careflow_meeting_notes` | one audio recording and one capable `.docx`/`.doc` report template | images, spreadsheets, PDF templates |
| `careflow_government_forms` | elder source image/text/profile plus a listed government-form template ID | roster workbooks or arbitrary blank PDFs |
| `roster_copilot` | one HC timetable workbook and one escort workbook in named roles | generic Excel sheets or CareFlow exports |

Validation errors repeat the expected role and supported formats so a general
agent can repair the request without reading server logs.

### 7.2 Response Envelope

Every operation returns this stable outer shape:

```json
{
  "schema_version": "1.0",
  "tool": "careflow_paper_forms_to_excel",
  "operation": "status",
  "job_id": "opaque-id",
  "state": "pending_review",
  "native_status": "pending_review",
  "native_refs": {},
  "result": {},
  "artifacts": [
    {
      "kind": "review_workbook",
      "path": "/absolute/local/path/file.xlsx",
      "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "size_bytes": 12345,
      "sha256": "..."
    }
  ],
  "next_operations": ["review", "export"],
  "warnings": [],
  "error": null
}
```

`result` preserves the application's domain payload. Only transport-specific
HTTP fields are normalized. A native `download_url` may remain under
`result` for traceability, but the usable MCP transport is the absolute
artifact `path`.

Errors use stable wrapper codes while retaining sanitized native error data:

```json
{
  "code": "UNSUPPORTED_FILE_TYPE",
  "message": "...",
  "retryable": false,
  "native_code": null,
  "native_message": null,
  "details": {}
}
```

Native Roster conflict codes such as `STALE_SCHEDULE_VERSION` and
`STALE_CONTENT_HASH` are not collapsed into a generic error.

### 7.3 Job and Native Identity

The public `job_id` is an opaque MCP identifier. The shared job store maps
it to:

- CareFlow `VolunteerBatch.id` for paper-to-Excel jobs;
- CareFlow `VisitSession.id` for meeting-note jobs;
- an MCP-owned native reference for government-form jobs;
- RosterCopiilot `run_id` for roster jobs.

Roster's native `run_id` remains in `result`. Subsequent MCP calls use
the MCP `job_id`, while Roster mutations also provide the returned
`source_version_id` and `content_hash`.

### 7.4 Lifecycle

Normalized states are:

```text
accepted -> running -> pending_review -> reviewed -> exported
                    \-> failed

roster only:
pending_review/reviewed -> draft | blocked | ready -> published

meeting only:
pending_review -> confirmed; transcript may independently become burned
```

The MCP projection does not replace native state. It stores both normalized
`state` and the meaningful native status or publication state.

Calls are synchronous from the MCP caller's perspective. `start` creates the
job, records an `accepted` operation, stages input, marks it `running`, invokes a
one-shot worker, and returns the worker's resulting reviewable, failed, or
terminal state with `job_id`. Later `status`, review, export, burn, revalidate,
and publication calls use that ID. Mutating operations are recorded before
worker dispatch; there is no background queue in the current implementation.

### 7.5 Durability, Idempotency, and Recovery

The shared `jobs.sqlite3` database is authoritative for MCP jobs, operation
request hashes/responses, and artifacts. Each job also has an atomically
replaced `manifest.json` projection containing the schema version, tool/job
identity, timestamps, current wrapper/native state, native references,
registered artifact metadata, warnings, and the last error. Tool results and
original accepted input remain in SQLite; role-specific staged hashes are held
in tool state where required.

Within one host process, each call takes an `asyncio` lock keyed by public job
ID. SQLite uniqueness plus canonical request hashes implement replay: the same
`request_id` and payload returns the recorded success or failure, while changed
payload reuse returns `IDEMPOTENCY_KEY_REUSED`. A failed non-start operation
preserves the last successful job state and valid next operations.

There is currently no cross-process lock/lease, stale-`running` transition,
native commit receipt, or automatic restart reconciliation loop. A process
crash cannot be reported as success, but an operation left `running` requires
operator inspection or future recovery work; replay alone does not prove that
publication or transcript burn can be resumed after an ambiguous native
commit. This limitation is a release-hardening item in Sections 14 and 16.

### 7.6 Host-Worker Protocol

The private protocol contains only:

- protocol version;
- tool name, operation, and job ID;
- one absolute job root containing input/intermediate/output/log directories;
- validated tool payload;
- absolute managed application source, data, and resource roots;
- structured result, native references, artifact candidates, warnings, or
  sanitized error.

The host routes by the static tool manifest. The CareFlow worker accepts only
the three CareFlow tool names; the Roster worker accepts only
`roster_copilot`. A worker rejects an unknown tool or protocol version
before importing a native adapter.

## 8. Tool Implementation Plans

Tool-specific input schemas, operation matrices, native call chains, review
rules, output details, and acceptance fixtures live in separate implementation
plans:

| Tool | Responsibility | Detailed plan |
|---|---|---|
| `careflow_paper_forms_to_excel` | Convert completed volunteer-form images into reviewed records and a CareFlow-generated Excel workbook. | [CareFlow Paper Forms to Excel MCP Implementation Plan](NGOPilotMCP/docs/implementation/CareFlow_Paper_Forms_To_Excel_MCP_Implementation_Plan.md) |
| `careflow_meeting_notes` | Convert an audio recording and report template into reviewed CareFlow meeting/home-visit notes. | [CareFlow Meeting Notes MCP Implementation Plan](NGOPilotMCP/docs/implementation/CareFlow_Meeting_Notes_MCP_Implementation_Plan.md) |
| `careflow_government_forms` | Extract or accept an elder profile, review mapped values, and fill a supported government PDF. | [CareFlow Government Forms MCP Implementation Plan](NGOPilotMCP/docs/implementation/CareFlow_Government_Forms_MCP_Implementation_Plan.md) |
| `roster_copilot` | Run the complete weekly roster workflow through review export and ready-only publication. | [Roster Copilot MCP Implementation Plan](NGOPilotMCP/docs/implementation/Roster_Copilot_MCP_Implementation_Plan.md) |

Those documents are authoritative for tool-specific behavior. This architecture
is authoritative for packaging, ownership, shared contracts, process isolation,
state, transport, recovery, and release-level constraints.

## 9. File Transport and Validation

All file transport uses local absolute paths over stdio. The host never returns
binary blobs, `file://` URLs, or HTTP URLs as primary artifact transport.

For every input path, the MCP boundary:

1. Requires an absolute path.
2. Resolves it and verifies an allowed, readable, non-empty regular file.
3. Rejects devices, FIFOs, sockets, unsafe symlinks, and paths inside another
   job's private directory.
4. Enforces configured allowed input roots.
5. Applies the owning tool's suffix, content, role, and size rules.
6. Copies the file into that job's `inputs/` directory without mutating
   the source.
7. Hashes the source for its immutable staged name; tools that need durable
   size/SHA-256/display-name metadata also store it in their native references.
8. Passes only the staged path to the native adapter.

Shared content-safety primitives include:

- images: suffix-specific JPEG/PNG/HEIC-family header verification and format
  allowlists; pixel/dimension and decompression-bomb inspection remain open;
- DOCX/XLSX/XLSM: valid ZIP container, `[Content_Types].xml`, entry count, and
  uncompressed member/total-size/compression-ratio limits;
- audio: extension plus a basic container/header probe where reliable;
- generated PDF/DOCX/XLSX: reopen and structural verification before delivery.

Role-specific decisions remain in the owning tool implementation. For example,
the generic validator can identify a valid XLSX container, the Roster
controller fixes HC and escort roles, and the original Roster importers remain
responsible for required workbook sheet structure.

File names are display metadata and never become directory names. Non-ASCII
file names are supported. Artifact records contain resolved absolute paths,
sizes, media types, and hashes.

## 10. Concurrency and Process Safety

- Operations on the same public `job_id` are serialized by an in-memory
  `asyncio.Lock` within one MCP host process.
- Calls for different jobs may start concurrent one-shot subprocesses.
  CareFlow and Roster processes have separate interpreters, import paths,
  application paths, and native databases.
- There is no host-wide CareFlow mutation lock, Roster facade lock, or
  cross-process MCP job lock in the current implementation. Deployments should
  run one stdio host per state root until those concurrency gates are added.
- Roster review retains its database compare-and-swap behavior, so stale or
  concurrent decisions fail as the application requires.
- Roster publication retains its native publication lock and atomic file
  replacement.
- Review exports are versioned in the MCP artifact registry and cannot be
  mistaken for final publications.

The current Roster publication lock uses POSIX `fcntl`. The first release
is therefore macOS/Linux only. Windows support requires an explicit
cross-platform lock adaptation and parity tests.

## 11. Security and Privacy

- MCP-created state/job directories use owner-only permissions where supported;
  staged files, promoted artifacts, and manifests are set to `0600`. Native
  application-created files retain the application's permissions and process
  umask.
- API keys and provider configuration are inherited from managed runtime
  configuration; MCP schemas never accept or return them, and MCP code does not
  intentionally log them. Native-output redaction remains subject to the log
  limitation below.
- Manifests contain hashes and minimal summaries, not raw transcripts or full
  elder/worker records.
- Worker logs are size-bounded and stored below owner-only job directories, but
  the current logger captures native stdout/stderr and exception text without a
  general secret/PII redaction pass. Native services must not print sensitive
  content; redaction tests remain a release-hardening gate.
- Raw meeting transcripts remain only in CareFlow's encrypted vault and retain
  native burn behavior.
- Intermediate job results contain information required for caller review and
  parity. No automated retention/cleanup policy is implemented yet.
- Tool results necessarily contain requested review data. Adapters do not
  intentionally log those payloads, but native stdout/stderr is captured
  without a general redaction pass as noted above.
- Absolute output paths are returned only for verified artifacts owned by the
  requested tool and job.
- Published Roster artifacts are checked against the native stored SHA before
  they are snapshotted or returned.
- No tool automatically emails, messages, uploads, or distributes an artifact.

## 12. Error and State Semantics

The MCP layer validates transport and file-role concerns but does not
reinterpret domain decisions:

- a wrong file role or type fails before the native call;
- CareFlow extraction failures remain visible in native record/session results;
- missing government-form mappings remain visible for review;
- Roster build, audit, stale-version, blocked-export, and not-ready-publication
  outcomes retain their native codes and fail closed.

An operation failure is durable and its immediate response includes the error,
last successful stage, retryability, and preserved valid next operations. A
later successful native `status` refresh may clear that prior error. Failed
output validation never registers or delivers an artifact.

Every tool plan defines its exact operation-to-native error mapping. Shared
wrapper codes are limited to transport concerns such as:

- `INVALID_REQUEST`
- `UNKNOWN_JOB`
- `INVALID_JOB_STATE`
- `UNSUPPORTED_FILE_TYPE`
- `PATH_NOT_ABSOLUTE`
- `PATH_NOT_ALLOWED`
- `FILE_CONTENT_MISMATCH`
- `IDEMPOTENCY_KEY_REUSED`
- `WORKER_UNAVAILABLE`
- `WORKER_PROTOCOL_ERROR`
- `OUTPUT_VALIDATION_FAILED`

## 13. Compatibility and Inherited Constraints

| Constraint | Architecture response |
|---|---|
| Both apps use top-level `app` | two separate managed application environments and workers |
| Backend wheels omit required assets | explicit payload manifest and install self-check |
| CareFlow config/DB initialize at import time | set absolute environment and working directory before import |
| Three tools share CareFlow runtime state | namespace MCP jobs and keep tool code independent; current locking covers only calls on the same public job, so one host per state root is required |
| CareFlow welfare flow has no native job | MCP-owned durable job and review snapshots |
| CareFlow meeting mode is not stored natively | persist it in MCP job metadata |
| CareFlow paper export permits partially reviewed batches | preserve behavior and report counts |
| CareFlow `.doc` conversion uses macOS `textutil` | capability-gated; `.docx` is the portable default |
| CareFlow UI advertises HEIC without a guaranteed decoder | capability-gated; JPG/PNG guaranteed |
| CareFlow active Excel template is global | no per-job template in v1; serialize if later added |
| Theta published-PDF path mismatch | do not advertise broken custom templates; authoring stays out of scope |
| Roster fixed division workbook lives outside wheel package | bundle required workbook in a resolved resource layout |
| Roster depends on global persisted master data | isolate application state and record the native data version/hash |
| Roster final lock uses `fcntl` | macOS/Linux first release |
| Roster review export is not final publication | distinct `export` and `publish` operations |
| Long AI work can exceed an MCP call timeout | durable queued operation plus status polling |

Redistribution must be confirmed before release. CareFlow includes an MIT
license. No RosterCopiilot license file is present in the inspected source, and
the bundled division workbook may contain NGO-sensitive material. Private
deployment still requires permission to package that code and workbook.

## 14. Testing and Parity Strategy

### 14.1 Tool-Level Contract and Parity Tests

Each independent tool suite runs the original application path and its native
adapter against the same fixture, then compares normalized domain results.
Only timestamps, generated IDs, absolute roots, and transport URLs may be
normalized. Artifact comparison is structural because ZIP/PDF serialization
may differ without changing document behavior.

Each suite must prove:

- strict operation and file-role validation;
- native request and response parity;
- identical review and state-transition effects;
- structurally equivalent delivered artifacts;
- native error/conflict preservation;
- restart and idempotency behavior for that tool;
- no import from another tool implementation package.

The detailed fixture and assertion matrix is owned by each implementation plan.

Current evidence is intentionally narrower than the original release target:
automated tests verify strict schemas, tool-local controllers, exact native
service-call boundaries, state projection, artifact structure/promotion,
idempotent replay, and import isolation. Real-worker smokes verify the principal
lifecycle paths. Exhaustive normalized golden-payload comparisons, restart at
every native commit boundary, and full fault-injection matrices remain open
release-hardening work and are not represented as passing tests.

### 14.2 MCP End-to-End Tests

- A clean `list_tools` returns exactly the four agreed names.
- Each tool completes its full lifecycle over stdio.
- No worker output contaminates protocol stdout.
- All delivered artifact paths are absolute, exist under the owning job,
  hash correctly, and reopen successfully.
- Non-ASCII input and output names work.
- A host restart preserves completed jobs and reconciles interrupted jobs.
- Duplicate idempotent calls replay; changed-payload key reuse fails.
- Concurrent calls on one job serialize correctly.
- Disabling or failing one tool adapter does not import or break another tool's
  implementation, except when their intentionally shared CareFlow runtime is
  unavailable.

At this revision, exact four-tool FastMCP discovery and controller-level
lifecycle routing are automated. Full lifecycle execution over a captured
stdio client, cross-process concurrent mutation tests, and crash/restart
reconciliation at every boundary remain pending.

### 14.3 Security and Negative Tests

- relative, missing, empty, or disallowed paths;
- wrong file assigned to a role;
- extension/content mismatch;
- unsafe symlinks, traversal, devices, FIFOs, and sockets;
- oversized images, workbooks, audio, or templates;
- image and ZIP decompression bombs;
- corrupt PDF, DOCX, or XLSX output;
- unknown operations/jobs and invalid state transitions;
- request-ID reuse with a changed payload;
- interrupted worker operations and bounded/redacted logs;
- secrets and raw transcripts absent from generic manifests and logs.

Tool-specific negative cases remain in the four implementation plans.

The current suite covers the main schema, absolute-path, file-content,
cross-job identity, corrupt-artifact, hash-mismatch, and transcript-projection
cases. Devices/FIFOs, decompression bombs, log redaction under native failures,
and exhaustive interruption cases remain pending hardening evidence.

### 14.4 Clean-Install Tests

Build the final artifact, install it in a fresh environment, bootstrap both
managed application runtimes, and verify:

- the CareFlow worker imports the pinned CareFlow `app` revision and all
  three independent CareFlow adapters;
- the Roster worker imports the pinned Roster `app` revision and only the
  Roster adapter;
- the other application's `app` is not importable in either worker;
- all prompts, templates, PDFs, and fixed roster assets are present;
- no source checkout or current working directory is required;
- the host starts from an arbitrary directory;
- discovery and at least one mock/offline workflow per tool succeed.

The existing application suites remain mandatory regression suites.

This section is partially closed. The payload is cleaned, hashed in
`vendor.lock.toml`, and packaged through an explicit allowlist with local
application wheels. The rebuilt wheel contains all mandatory assets and no
generated-source/cache leakage. A fresh host venv installed that wheel from an
arbitrary working directory, listed exactly four tools, and bootstrapped both
managed runtimes twice idempotently. The installed CareFlow worker discovered
all five government templates, and an installed-wheel structured-profile OALA
job completed `start -> review -> export` with a verified promoted PDF. The
other three installed-wheel lifecycles remain open.

## 15. Implementation Sequence

| Phase | Current status | Completion evidence / open item |
|---|---|---|
| 0. Contracts and permissions | Partial | Versions, revisions, workflows, assets, hashed runtime locks, and `vendor.lock.toml` are frozen; exhaustive golden fixtures and RosterCopiilot redistribution authorization remain open. |
| 1. Host, packaging, isolation | Complete | Host, workers, cleaned payload, manifest, local app wheels, arbitrary-directory host install, and idempotent two-venv bootstrap pass. |
| 2. Shared infrastructure | Core complete | Jobs, operation replay, per-process job locks, staging, hashing, promotion, and failure-state preservation pass; leases and exhaustive crash reconciliation are not implemented. |
| 3. Four independent tools | Complete | Four eight-module packages, tool suites, and real-worker lifecycle smokes are present. |
| 4. Release verification | In progress | `125 passed`; wheel inspection plus fresh install/bootstrap/list-tools and one Government Forms lifecycle pass. The other installed-wheel tool lifecycles and full fault/concurrency coverage remain. |

### Phase 0: Freeze Contracts and Permissions

- Record both source revisions and asset hashes.
- Confirm RosterCopiilot code/workbook packaging permission.
- Capture native request/response fixtures and golden artifacts.
- Resolve dependencies into reproducible CareFlow and Roster locks.

Exit criterion: all four native workflows are fixed as versioned fixtures and
redistribution is authorized.

### Phase 1: Host, Packaging, and Runtime Isolation

- Create the outer package and stdio entry point.
- Implement the minimal host registry, router, one-shot worker client, and
  worker protocol.
- Bundle source/resource payloads.
- Bootstrap two managed environments and set pre-import environment rules.
- Prove there is no `app` namespace collision.

Exit criterion: a clean install launches both workers and locates all required
resources without starting FastAPI.

### Phase 2: Shared Domain-Neutral Infrastructure

- Implement the request/response envelope and shared wrapper errors.
- Implement the namespaced job/operation/artifact store, request-hash replay,
  in-process locks, staging, hashing, output verification, artifact promotion,
  and failure-state preservation.
- Add import-boundary enforcement for the four tool packages.
- Register stub manifests for exactly four tools.

Exit criterion: lifecycle, replay, primary path-security, failure-state, and
tool-isolation tests pass with stub native adapters. Cross-process leases and
automatic crash recovery are separate hardening gates.

### Phase 3: Independent Tool Implementations

Implement the tools one at a time from their separate plans:

1. [CareFlow Paper Forms to Excel](NGOPilotMCP/docs/implementation/CareFlow_Paper_Forms_To_Excel_MCP_Implementation_Plan.md)
2. [CareFlow Meeting Notes](NGOPilotMCP/docs/implementation/CareFlow_Meeting_Notes_MCP_Implementation_Plan.md)
3. [CareFlow Government Forms](NGOPilotMCP/docs/implementation/CareFlow_Government_Forms_MCP_Implementation_Plan.md)
4. [Roster Copilot](NGOPilotMCP/docs/implementation/Roster_Copilot_MCP_Implementation_Plan.md)

Each implementation lands in its own module and test directory, calls only its
pinned native boundary, and reaches its plan's acceptance criteria before the
next tool depends on it. No tool implementation task may be placed in another
tool's module.

Exit criterion: all four independent suites pass principal native-call parity
and produce verified, namespaced output artifacts.

### Phase 4: Cross-Tool and Release Verification

- Run both original application suites and all MCP suites.
- Verify same-job serialization and characterize concurrent cross-job CareFlow
  and Roster calls.
- Perform clean installation on the target private-agent host; an offline
  wheelhouse bundle remains a later distribution variant.
- Validate tool descriptions with a general agent using correct and incorrect
  representative files.
- Produce the install command, MCP configuration entry, supported-format table,
  and operations runbook.

Exit criterion: the standalone package exposes exactly four tools and completes
all four workflows end to end without either source checkout.

## 16. Release Acceptance Criteria

`Verified` means objective evidence exists in the current automated suite or a
recorded real-worker smoke. `Partial` means the behavior is implemented but the
full release-strength evidence named in the criterion is not present. `Open`
blocks release closure, not the completed four-tool implementation.

| # | Criterion | Status | Current evidence / remaining gate |
|---|---|---|---|
| 1 | `list_tools` returns exactly the four agreed names. | Verified | Static registry and FastMCP discovery integration tests. |
| 2 | Every tool has an independent implementation/test directory and no tool imports another. | Verified | AST/import package-contract tests plus tool-local checks. |
| 3 | CareFlow and RosterCopiilot are pinned in separate managed venvs and retain domain ownership. | Verified | Hashed locks, version/source checks, separate interpreters, and native-adapter-only `app` imports. |
| 4 | No FastAPI/Uvicorn service or network port is required. | Verified | Stdio FastMCP host and direct one-shot worker subprocesses. |
| 5 | File arguments are role-specific, absolute, staged, content-validated, and hashed before native use. | Verified for supported roles | Controller, staging, validation, and role-routing tests. Exhaustive device/FIFO and bomb cases remain hardening work. |
| 6 | MCP owns intermediate/review state and delivers outputs from namespaced job directories. | Verified | SQLite/job-manifest persistence and artifact-promotion controller tests plus worker smokes. |
| 7 | Artifact paths are absolute, existent, size/SHA-256 registered, and structurally valid. | Verified | XLSX, DOCX, PDF, corrupt-output, and publication hash tests. |
| 8 | Native calls, payload projection, and principal state transitions have parity evidence. | Verified for principal paths | Native-boundary tests and real-worker lifecycle smokes; exhaustive golden-payload comparison remains open hardening. |
| 9 | CareFlow AI output cannot bypass review before final export. | Verified | Government Forms and Meeting Notes reject export/review omissions; Paper export preserves CareFlow's reviewed-rows-only rule. |
| 10 | Roster review export is distinct from final publication. | Verified | Distinct native operations, artifact kinds/names, and controller tests. |
| 11 | Roster publish fails unless the exact current version/hash is freshly ready. | Verified for blocked path and adapter contract | Real worker rejected blocked publication; strict version/hash schemas and native publication facade are preserved. A real ready-publication smoke remains desirable. |
| 12 | Jobs survive restart and ambiguous mutations never rerun silently. | Partial | SQLite persistence, request replay, and failed-followup state preservation are tested. Exhaustive crash receipts/reconciliation are not implemented. |
| 13 | Raw meeting transcripts and secrets are absent from generic state/logs. | Partial | Public projection excludes transcript/vault fields and the real smoke retained vault privacy. Failure-log redaction under every native error is not exhaustively tested. |
| 14 | A clean target-host wheel install works without checkout venvs or current-working-directory assumptions. | Partial | Clean wheel install, arbitrary-directory CLI/discovery, idempotent managed-runtime bootstrap, five-template discovery, and one Government Forms lifecycle pass. The other three installed-wheel lifecycles remain. |
| 15 | Embedded application redistribution is authorized and traceable. | Open | CareFlow license is bundled; the RosterCopiilot source payload has no license file and authorization must be recorded. |

## 17. Final Architectural Position

The unit of distribution is one MCP product. The execution model is the stdio
host invoking a one-shot subprocess in either the isolated CareFlow or isolated
RosterCopiilot environment for each native operation. The two application
environments prevent their top-level `app` packages from colliding.

Within that product, the four MCP tool implementations are deliberately
separate and cannot import one another. They may share domain-neutral host/job
infrastructure, and the three CareFlow tools intentionally share the CareFlow
worker, venv, and native database.

NGOPilotMCP owns the workflow boundary: inputs, staged copies, intermediate and
review results, output delivery, job identity, durable operation state, and
recovery. The pinned CareFlow and RosterCopiilot dependencies own every
internal domain algorithm and native review/export/publication effect.
