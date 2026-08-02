# CareFlow Paper Forms to Excel MCP Implementation Plan

Status: implemented; principal lifecycle verified; release hardening tracked below  
Architecture: [Architecture_Design_Plan.md](../../Architecture_Design_Plan.md)  
Public tool: `careflow_paper_forms_to_excel`  
Pinned native dependency: CareFlow 0.4.8

## Implementation Record

The independent eight-module tool package and its four public operations are
implemented. Automated tests cover strict schemas, content-aware image
validation, staged-path routing, exact CareFlow service-call boundaries,
complete-field review routing, partial export, workbook verification/promotion,
and import isolation. A real managed-CareFlow worker smoke completed
`start -> review -> export` and promoted the native workbook into the MCP job.
The full authored package suite currently passes with `125 passed`.

This record does not claim exhaustive crash/restart injection or byte-for-byte
golden workbook parity. Those remaining hardening items are identified
explicitly in the acceptance matrix rather than being treated as completed
evidence.

## 1. Purpose and Scope

This tool turns completed volunteer visit-form images into reviewed structured
records and a native CareFlow Excel export.

This document owns the detailed implementation contract for this tool. The
top-level architecture intentionally contains only the cross-tool host and
isolation rules.

## 2. Independent Code Boundary

All tool-specific implementation code lives under:

```text
src/ngopilot_mcp/tools/careflow_paper_forms_to_excel/
  __init__.py
  manifest.py
  schemas.py
  controller.py
  validation.py
  native_adapter.py
  state.py
  artifacts.py

tests/tools/careflow_paper_forms_to_excel/
  test_schemas.py
  test_controller.py
  test_native_parity.py
  test_artifacts.py
```

The package owns only the behavior that is specific to this MCP tool:

- operation schemas, tool description, and response projection;
- workflow controller and CareFlow call adapter;
- image-role and review-payload validation beyond shared file-safety checks;
- interpretation of native batch/record state and native-ID mappings;
- Excel artifact meaning, naming, validation requirements, and partial-export
  reporting;
- unit, contract, parity, and artifact tests.

It uses NGOPilotMCP's shared server/host, SQLite job/operation/artifact store,
per-process job locks, request-hash replay, failure-state checkpointing, file
staging and hashing, worker protocol, artifact promotion, and runtime
bootstrap. The three CareFlow tools use the same managed CareFlow virtual
environment, CareFlow worker, and CareFlow application-data root.

Code under this package must not import any other package under
`src/ngopilot_mcp/tools/`. It may import versioned shared infrastructure from
the host, jobs, files, and workers packages. Shared infrastructure must not
contain this tool's schemas, operation branching, native payload interpretation,
or artifact semantics.

`manifest.py`, `schemas.py`, and schema discovery are host-safe and must not
import CareFlow. `native_adapter.py` is worker-only and is the only module in
this package permitted to import the pinned CareFlow `app` package.

## 3. Ownership Boundary

NGOPilotMCP owns accepted inputs, immutable staged inputs, intermediate and
review results, delivered outputs/artifacts, durable job state, idempotency,
and recovery. CareFlow 0.4.8 is a pinned dependency in the shared managed
CareFlow virtual environment and owns all internal domain logic.

The tool calls CareFlow's `volunteer_form` and `excel_export` services directly.
CareFlow owns image extraction, AI review, correction recording, batch state
transitions, template-aware Excel writing, and every field-level domain rule.
The MCP adapts inputs and snapshots returned results; it does not copy, rewrite,
or second-guess those algorithms.

CareFlow may write a temporary or native export as part of its algorithm. After
the shared artifact service validates it against this tool's Excel requirements,
NGOPilotMCP snapshots or promotes the delivered workbook into the job's
`outputs/` directory and returns that absolute path. The native export path is
retained only as metadata. Native intermediate results needed for review or
recovery are snapshotted under `intermediate/` or in the shared job database;
this persistence does not recompute domain results.

## 4. MCP Tool Contract

Tool name: `careflow_paper_forms_to_excel`

### 4.1 Start Input

```json
{
  "operation": "start",
  "job_id": null,
  "input": {
    "title": "2026-08-02 volunteer visits",
    "image_paths": ["/absolute/form-01.jpg", "/absolute/form-02.png"],
    "volunteer_team": "optional",
    "visit_date": "2026-08-02",
    "note": "optional",
    "auto_complete": false
  }
}
```

Validation contract:

- `title` is required and non-empty.
- `image_paths` contains at least one absolute, existing, non-empty image.
- Reliably supported formats are `.jpg`, `.jpeg`, and `.png`; file content is
  verified, not just the suffix.
- Multiple images are allowed. The existing UI recommends at most 20 but the
  backend does not enforce that recommendation, so the MCP emits a warning
  above 20 rather than rejecting by default. A managed deployment may set an
  explicit safety cap, which must be reported in tool metadata.
- `visit_date`, if supplied, is an ISO date string.
- `auto_complete` is passed unchanged to the original extraction flow.

Start calls the original batch creation, photo ingestion, and extraction. Its
review payload contains one record per source image, including the native
`record_id`, staged source path, original filename, extracted fields,
confidence, bounding boxes, provider/model metadata, errors, completeness,
missing/low-confidence fields, AI review annotations, and proposed final fields.

The 13 current editable fields are:

```text
elder_name, elder_age, elder_gender, elder_phone, elder_address,
living_alone, visit_date, volunteer_name, duration_minutes, mood,
health_concerns, follow_up_needed, follow_up_note
```

### 4.2 Operations

| Operation | Required payload | Original effect | Result/next state |
|---|---|---|---|
| `start` | metadata and `image_paths` | create batch, ingest images, run vision/text extraction | `pending_review` or `failed` |
| `status` | `job_id` | load batch and records | current full review payload |
| `review` | one or more `{record_id, final_fields, reviewer?}` | call `review_record`; persist corrections | record(s) reviewed; batch becomes `confirmed` when all are reviewed |
| `export` | `job_id` | export reviewed rows through original Excel writer | absolute `.xlsx` artifact, native state `exported` |

Review submits the complete 13-field `final_fields` dictionary for each record,
not a partial patch. This preserves CareFlow's correction logging.

The original export rule is intentionally preserved: export is allowed when at
least one record has been reviewed, and it includes reviewed records only. It
does not require every uploaded image to be reviewed, even though the frontend
warns the user. The MCP result must report reviewed, unreviewed, and exported
row counts so an agent cannot mistake a partial export for a complete batch.

The native generated path is the resolved absolute version of CareFlow's
`data/exports/batch_<native_batch_id>_<timestamp>.xlsx` path.

Custom Excel-template management is not a first-release operation. The active
CareFlow template is installation-scoped. If per-job template input is added
later, it must be serialized and snapshot/restored because the original active
template store is global.

## 5. Native Call Boundary

The outer MCP server never imports CareFlow's top-level `app` package. The tool
controller dispatches through the shared worker protocol to the shared CareFlow
worker, where `native_adapter.py` invokes only these existing service boundaries:

| Operation | Native boundary |
|---|---|
| `start` | `volunteer_form.create_batch`, then `add_photos`, then `run_extraction` |
| `status` | load the mapped `VolunteerBatch` and its `VolunteerRecord` rows |
| `review` | `volunteer_form.review_record` for each submitted record |
| `export` | `excel_export.export_batch` for the mapped native batch |

The adapter returns the native domain payload and native IDs through the worker
envelope. It performs no extraction, correction, batch-transition, or workbook
generation logic of its own.

## 6. Operation-by-Operation Implementation Tasks

### 6.1 `start`

1. Parse the strict start schema and apply the validation contract in Section 4.1.
2. Ask the shared file service to stage and hash each image under the namespaced
   job; retain source order and display names.
3. Persist an `accepted` operation and dispatch staged paths to the CareFlow
   worker through the shared runner.
4. Invoke the native start chain in Section 5 and persist the batch ID plus all
   returned record IDs as native references.
5. Snapshot the complete review payload under `intermediate/` or in
   `jobs.sqlite3`, then project the native state as `pending_review` or `failed`.

### 6.2 `status`

1. Load the job and native batch mapping from the shared job store.
2. Reconcile the current native batch and record state through the CareFlow
   worker when required by the shared recovery policy.
3. Return the full current review payload, native status, warnings, errors, and
   valid next operations without recomputing extraction.

### 6.3 `review`

1. Require one or more known `record_id` values and a complete 13-field
   `final_fields` dictionary for every submitted record.
2. Use the shared per-job lock and request-idempotency service before mutation.
3. Call native `review_record` for each record and persist the returned
   correction/state effects as the new review snapshot.
4. Report per-record review state and `confirmed` only when the native batch has
   reached that state.

### 6.4 `export`

1. Load the current native batch and call the native Excel writer; preserve its
   requirement that at least one record is reviewed.
2. Validate the generated workbook structurally and register its size, media
   type, and SHA-256 through shared artifact infrastructure.
3. Snapshot/promote the validated workbook into
   `jobs/careflow_paper_forms_to_excel/<job_id>/outputs/` and return that
   absolute path, retaining the native path only as metadata.
4. Return reviewed, unreviewed, and exported row counts on every successful
   export, including a partial export.

## 7. Shared Runtime State

This tool uses the shared NGOPilotMCP state root:

```text
<state>/
  jobs.sqlite3
  jobs/careflow_paper_forms_to_excel/<job_id>/
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
`jobs/careflow_paper_forms_to_excel/<job_id>/` namespace. The
`app-data/careflow/` root and `runtimes/careflow/.venv/` environment are shared
by all three CareFlow tools; mutating native operations use the serialization
policy defined by the architecture: calls on one public job serialize within a
host, while cross-job calls do not. This tool interprets its job fields and
native references but does not own a separate database, worker, virtual
environment, resource store, or runtime root.

## 8. Ordered Implementation Milestones

| Milestone | Status | Completion evidence / remaining gate |
|---|---|---|
| 1. Package and contracts | Complete | Eight modules exist; strict schema and import-boundary tests pass. |
| 2. Shared-services integration | Complete | Controller uses shared jobs, immutable staging, operation replay, worker dispatch, and artifact promotion. |
| 3. Native start/status adapter | Complete for principal path | Exact `create_batch -> add_photos -> run_extraction` routing is tested; a real worker start completed. Exhaustive normalized golden extraction fixtures remain hardening. |
| 4. Review lifecycle | Core complete | Complete 13-field validation, cross-job record rejection, exact `review_record` calls, replay infrastructure, and real-worker review are verified. Crash/restart reconciliation at every commit boundary is not automated. |
| 5. Export lifecycle | Complete for supported behavior | Reviewed-rows-only native export, partial counts, structural XLSX validation, promotion, and real-worker export pass. Full style/formula golden comparison is still open. |
| 6. Release parity | Partial | Tool and full package suites plus the source-runtime smoke pass; this tool's installed-wheel lifecycle and exhaustive recovery/security gates remain. |

## 9. Verification and Acceptance

| ID | Acceptance criterion | Status | Current evidence / missing evidence |
|---|---|---|---|
| PFE-01 | No module imports another `ngopilot_mcp.tools.*` package; only shared APIs cross tool boundaries. | Verified | Tool-local AST checks and package-contract integration test. |
| PFE-02 | Unknown operations/fields, invalid dates, empty images, and unsupported or corrupt image content fail before a native call. | Verified | Schema, validation, and artifact tests. |
| PFE-03 | Start follows the pinned CareFlow service chain and projects the native review payload without reimplementing extraction. | Verified for principal path | Native-boundary test plus real-worker start smoke. Exhaustive normalized golden payload comparison remains open. |
| PFE-04 | Review requires all 13 fields, routes only job-owned record IDs, and preserves native correction/batch effects. | Verified for principal path | Schema/controller/native-boundary tests and real-worker review smoke. Multi-record crash/restart database reconciliation remains open. |
| PFE-05 | Same-key retries replay, changed-payload key reuse fails, and interrupted work is recovered without blind extraction rerun. | Partial | Shared SQLite replay and changed-payload rejection are tested; tool-specific ambiguous-worker crash injection is not. |
| PFE-06 | With at least one reviewed record, export contains reviewed rows only and reports reviewed/unreviewed/exported counts. | Verified | Native adapter and controller partial-export tests plus real-worker export. |
| PFE-07 | The promoted workbook is structurally valid and behaviorally equivalent to the native CareFlow export. | Partial | Structural reopen and native-file promotion pass; exhaustive sheets/formulas/styles/merges golden comparison is not automated. |
| PFE-08 | Returned output is absolute, namespaced, reopenable, size/SHA-256 registered, with native path only as metadata. | Verified | Controller, artifact service, and shared runtime tests. |
| PFE-09 | The tool uses the shared CareFlow venv/worker/app-data and shared MCP job store with no private infrastructure. | Verified | Source/import scans, configured worker routing, clean source bootstrap, and real-worker smoke. |

Contract tests compare the MCP tool with the pinned native workflow using the
same fixtures. IDs, timestamps, absolute roots, and transport URLs may be
normalized; domain payloads and workbook structure may not.

Tool implementation exit is satisfied: all four operations exist, the principal
real-worker lifecycle completes, and no critical contract criterion is open.
Release closure still requires the partial PFE-05/PFE-07 evidence and this
tool's installed-wheel lifecycle in the architecture plan.

## 10. Deferred and Out of Scope

Per-job custom Excel templates and template administration remain deferred
because the current CareFlow active-template setting is global.
