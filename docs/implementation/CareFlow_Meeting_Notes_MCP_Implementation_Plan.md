# CareFlow Meeting Notes MCP Implementation Plan

Status: implemented; principal lifecycle and transcript boundary verified  
Architecture: [MCP-pre-build algorithm design plan.md](../../MCP-pre-build%20algorithm%20design%20plan.md)  
Public tool: `careflow_meeting_notes`  
Pinned native dependency: CareFlow 0.4.8

## Implementation Record

The independent eight-module package implements `start`, `status`, `review`,
`export`, and `burn`. Automated tests cover both mode values, strict role-based
audio/template validation, dynamic complete-slot review, exact CareFlow phase
one/phase two/burn calls, repeated render promotion, export without rerender,
DOCX structure, transcript-safe public projection, and import independence. A
real managed-CareFlow worker smoke completed `start -> review -> export`,
promoted the native DOCX, and retained raw transcript data inside CareFlow's
native vault. The full authored package suite passes with `125 passed`.

The implementation record distinguishes these principal-path results from the
still-open exhaustive two-mode golden comparison and ambiguous burn
crash/restart matrix.

## 1. Purpose and Scope

This tool converts one supported audio recording and one DOC/DOCX report
template into reviewed CareFlow meeting or home-visit notes.

This document owns the detailed implementation contract for this tool. The
top-level architecture intentionally contains only the cross-tool host and
isolation rules.

## 2. Independent Code Boundary

All tool-specific implementation code lives under:

```text
src/ngopilot_mcp/tools/careflow_meeting_notes/
  __init__.py
  manifest.py
  schemas.py
  controller.py
  validation.py
  native_adapter.py
  state.py
  artifacts.py

tests/tools/careflow_meeting_notes/
  test_schemas.py
  test_controller.py
  test_native_parity.py
  test_artifacts.py
  test_privacy.py
```

The package owns only the behavior that is specific to this MCP tool:

- operation schemas, tool description, and response projection;
- workflow controller and CareFlow call adapter;
- audio/template-role, review-content, and burn-operation validation beyond
  shared file-safety checks;
- interpretation of native session state, stored `mode`, transcript-burn state,
  and native-ID mappings;
- DOCX artifact meaning, version behavior, and validation requirements;
- unit, contract, parity, artifact, and transcript-privacy tests.

It uses NGOPilotMCP's shared server/host, SQLite job/operation/artifact store,
per-process job locks, request-hash replay, failure-state checkpointing, file
staging and hashing, worker protocol, artifact promotion, and runtime
bootstrap. The three CareFlow tools use the same managed CareFlow virtual
environment, CareFlow worker, and CareFlow application-data root.

Code under this package must not import any other package under
`src/ngopilot_mcp/tools/`. It may import versioned shared infrastructure from
the host, jobs, files, and workers packages. Shared infrastructure must not
contain this tool's schemas, operation branching, native payload interpretation,
transcript policy, or artifact semantics.

`manifest.py`, `schemas.py`, and schema discovery are host-safe and must not
import CareFlow. `native_adapter.py` is worker-only and is the only module in
this package permitted to import the pinned CareFlow `app` package.

## 3. Ownership Boundary

NGOPilotMCP owns accepted inputs, immutable staged inputs, intermediate and
review results, delivered outputs/artifacts, durable job state, idempotency,
and recovery. CareFlow 0.4.8 is a pinned dependency in the shared managed
CareFlow virtual environment and owns all internal domain logic.

The tool calls CareFlow's `home_visit` and `visit_note_agent` services directly.
CareFlow owns transcription, template normalization and analysis, slot
generation, encrypted transcript storage, DOCX rendering, session transitions,
and transcript burning. The MCP adapts inputs and snapshots returned results;
it does not copy, rewrite, or second-guess those algorithms.

CareFlow may write a temporary or native DOCX as part of phase two. After the
shared artifact service validates it against this tool's DOCX requirements,
NGOPilotMCP snapshots or promotes the delivered document into the job's
`outputs/` directory and returns that absolute path. The native export path is
retained only as metadata. Native intermediate results needed for review or
recovery are snapshotted under `intermediate/` or in the shared job database
without copying the raw transcript or recomputing domain results.

## 4. MCP Tool Contract

Tool name: `careflow_meeting_notes`

This tool preserves both original prompt modes despite its concise name:
`home_visit` and `internal_meeting`.

### 4.1 Start Input

```json
{
  "operation": "start",
  "job_id": null,
  "input": {
    "title": "Weekly case meeting",
    "mode": "internal_meeting",
    "audio_path": "/absolute/meeting.m4a",
    "template_path": "/absolute/meeting-template.docx",
    "note": "optional"
  }
}
```

Validation contract:

- `title`, `audio_path`, and `template_path` are required.
- `mode` is exactly `home_visit` or `internal_meeting`.
- Audio extensions are exactly `.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`, and
  `.ogg`.
- Report templates are `.docx` or `.doc`; PDF is explicitly rejected.
- `.docx` is portable. The current `.doc` converter uses macOS `textutil`, so
  `.doc` is advertised only when the worker capability check succeeds.

Start calls `home_visit.create_session` and `run_phase1`. The native flow
transcribes audio while analyzing/normalizing the template, generates a
template contract and editable slot content, encrypts the full transcript, and
moves to `pending_review`.

### 4.2 Operations

| Operation | Required payload | Original effect | Result/next state |
|---|---|---|---|
| `start` | title, mode, audio and template paths | create session and run phase 1 | template contract and draft slot content; `pending_review` |
| `status` | `job_id` | load session and at most the permitted transcript snippet | current session payload |
| `review` | complete `slot_content_final`, optional `reviewer` | call `run_phase2`; render reviewed template | native state `confirmed`, absolute DOCX artifact |
| `export` | `job_id` | return/register the already rendered native artifact | absolute `.docx` artifact; no second renderer |
| `burn` | `job_id` | call original transcript vault burn | `transcript_burned=true` |

CareFlow combines review and rendering in phase 2. The MCP `review` operation
therefore performs the original render; `export` is an idempotent artifact
retrieval operation and does not create a different document. Reviewing an
already confirmed session is allowed by the native service and may generate a
new timestamped DOCX; the artifact registry retains previous versions.

The native generated path is the resolved absolute version of
`data/exports/visit_notes/visit_note_<native_session_id>_<timestamp>.docx`.

The MCP job stores `mode` because the current `VisitSession` record does not.
It never stores the raw transcript in the generic job database, manifest, or
logs. Only the native encrypted vault and the original at-most-200-character
snippet behavior are retained. `burn` is an independent privacy flag; the
native code does not change the session status to its existing `BURNED` enum.

## 5. Native Call Boundary

The outer MCP server never imports CareFlow's top-level `app` package. The tool
controller dispatches through the shared worker protocol to the shared CareFlow
worker, where `native_adapter.py` invokes only these existing service boundaries:

| Operation | Native boundary |
|---|---|
| `start` | `home_visit.create_session`, then `home_visit.run_phase1` |
| `status` | load the mapped `VisitSession` and only the native permitted snippet |
| `review` | `home_visit.run_phase2` with complete `slot_content_final` |
| `export` | no renderer call; retrieve the already promoted artifact for the current reviewed result |
| `burn` | `home_visit.burn_transcript` for the mapped session |

The adapter returns the native domain payload and session ID through the worker
envelope. It performs no transcription, template analysis, slot generation,
rendering, encryption, or transcript-burning logic of its own.

## 6. Operation-by-Operation Implementation Tasks

### 6.1 `start`

1. Parse the strict start schema and apply the validation contract in Section 4.1.
2. Ask the shared file service to stage and hash the audio and report template
   under their explicit roles in the namespaced job.
3. Persist `accepted`, including the requested `mode`, then dispatch the staged
   paths to the CareFlow worker through the shared runner.
4. Invoke the native phase-one chain in Section 5 and persist the session ID as
   the native reference.
5. Snapshot the template contract, editable slot content, permitted transcript
   snippet, and native status under `intermediate/` or in `jobs.sqlite3`; never
   copy the raw transcript into generic MCP state or logs.

### 6.2 `status`

1. Load the job, stored `mode`, and native session mapping from the shared job
   store.
2. Reconcile native session state through the CareFlow worker when required by
   shared recovery policy.
3. Return the current session payload with at most the native permitted snippet,
   artifact versions, burn flag, errors, warnings, and valid next operations.

### 6.3 `review`

1. Require the complete `slot_content_final` payload and optional reviewer.
2. Use the shared per-job lock and request-idempotency service before mutation.
3. Call native `run_phase2`, preserving CareFlow's allowed repeated-review
   behavior and native state transition.
4. Snapshot the reviewed slot result, validate the native DOCX, promote it to a
   new version under `outputs/`, and register it through shared artifact
   infrastructure while retaining the native path only as metadata.

### 6.4 `export`

1. Require a successfully registered DOCX for the current reviewed result.
2. Return that existing namespaced `outputs/` artifact idempotently after the
   shared artifact service rechecks ownership and integrity.
3. Do not invoke a second renderer or create a semantically different document.

### 6.5 `burn`

1. Use the shared per-job lock and durable operation record before dispatch.
2. Invoke native `burn_transcript` for the mapped session; never handle or log
   raw transcript content in the outer process.
3. Persist `transcript_burned=true` independently from the native session
   status and replay the stored result for an identical retry.

## 7. Shared Runtime State

This tool uses the shared NGOPilotMCP state root:

```text
<state>/
  jobs.sqlite3
  jobs/careflow_meeting_notes/<job_id>/
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
  runtimes/
    careflow/.venv/
```

`jobs.sqlite3`, the artifact registry, per-process job locks, request replay,
and failure-state checkpointing are shared infrastructure. Job files are isolated by the
`jobs/careflow_meeting_notes/<job_id>/` namespace. The
`app-data/careflow/` root and `runtimes/careflow/.venv/` environment are shared
by all three CareFlow tools; the encrypted transcript remains in CareFlow's
shared native vault, not in the generic job tree. Mutating native operations
use the serialization policy defined by the architecture: calls on one public
job serialize within a host, while cross-job calls do not. This tool interprets
its state and native references but does not own a separate database, worker,
virtual environment, resource store, artifact registry, or runtime root.

## 8. Ordered Implementation Milestones

| Milestone | Status | Completion evidence / remaining gate |
|---|---|---|
| 1. Package and contracts | Complete | Eight modules plus schema, privacy, artifact, controller, and native-boundary tests pass; no cross-tool import exists. |
| 2. Shared-services integration | Complete | Controller uses shared jobs, role staging, operation replay, worker dispatch, promotion, and namespaced state. |
| 3. Phase-one adapter | Complete for principal path | Exact `create_session`/`run_phase1` calls and safe projection are tested; real-worker start passed. A golden native comparison for both modes is still open. |
| 4. Review/export lifecycle | Complete | Complete dynamic slots, repeated review artifacts, structural DOCX promotion, and export-without-rerender pass. |
| 5. Burn/recovery lifecycle | Core burn complete; recovery hardening open | Native burn routing and public burn state pass. Ambiguous worker-failure reconciliation is not fault-injection tested. |
| 6. Release parity | Partial | Tool and full package suites plus a source-runtime real-worker lifecycle pass; this tool's installed-wheel lifecycle and exhaustive restart/privacy-log gates remain. |

## 9. Verification and Acceptance

| ID | Acceptance criterion | Status | Current evidence / missing evidence |
|---|---|---|---|
| CMN-01 | No module imports another tool package; only shared APIs cross tool boundaries. | Verified | Privacy/import AST test and package-contract integration test. |
| CMN-02 | Unknown fields, unsupported modes/audio, PDF templates, corrupt inputs, and incapable `.doc` conversion fail before the native call. | Verified | Strict schemas, file-role validation, and artifact tests. |
| CMN-03 | Both `home_visit` and `internal_meeting` preserve CareFlow's template contract, slot content, state, and permitted snippet. | Partial | Both modes parse and route; exact native phase-one boundary and a real worker start pass. Full golden outputs for both modes are not automated. |
| CMN-04 | Raw transcript/vault data never enters generic job state or logs. | Verified for public state; log matrix partial | Projection tests exclude raw/vault/working fields and the real smoke retained vault privacy. Injected-secret scans across every failure log are open. |
| CMN-05 | Complete reviewed slots invoke native phase two and produce the native state plus a structurally valid promoted DOCX. | Verified | Native-boundary, controller, artifact, and real-worker review tests. |
| CMN-06 | Repeated reviews create distinct registered versions; export returns the latest artifact without rerender. | Verified | Controller worker-call counts and artifact assertions. |
| CMN-07 | Returned DOCX paths are absolute, namespaced, reopenable, and size/SHA-256 registered. | Verified | Controller, artifact, and shared runtime tests. |
| CMN-08 | Burn preserves native deletion/overwrite semantics, exposes only burn state, and does not blindly rerun after ambiguity. | Partial | Native burn and controller state projection pass; ambiguous crash/restart fault injection is open. |
| CMN-09 | The shared CareFlow venv/worker/app-data/vault and shared MCP job store are used with no private infrastructure. | Verified | Import/source checks, configured worker routing, bootstrap, and real-worker smoke. |

Contract tests compare the MCP tool with the pinned native workflow using the
same fixtures. IDs, timestamps, absolute roots, and transport URLs may be
normalized; domain payloads and document structure may not.

Tool implementation exit is satisfied for all five operations and the
principal real-worker lifecycle. Release closure still requires the partial
CMN-03/CMN-04/CMN-08 evidence and this tool's installed-wheel lifecycle.

## 10. Deferred and Out of Scope

Portable legacy `.doc` conversion is deferred on platforms without the native
macOS `textutil` capability; `.docx` remains the portable contract.
