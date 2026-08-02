# Roster Copilot MCP Implementation Plan

Status: implemented; full operation surface and blocked-publication parity verified  
Architecture: [MCP-pre-build algorithm design plan.md](../../MCP-pre-build%20algorithm%20design%20plan.md)  
Public tool: `roster_copilot`  
Pinned native dependency: RosterCopiilot 0.6.0

NGOPilotMCP owns every accepted and staged input, persisted intermediate and
review result, delivered output artifact, public job state, recovery path, and
piece of tool-specific orchestration and internal MCP logic. RosterCopiilot
0.6.0 is a pinned application dependency in the managed Roster virtual
environment and owns all internal roster-domain logic. The MCP invokes and
preserves that logic; it does not reproduce scheduling, review, preflight,
workbook-generation, or publication algorithms.

## Implementation Record

The independent eight-module package implements all seven operations:
`start`, `status`, `review`, `revalidate`, `export`, `publish`, and
`get_published`. Automated tests cover strict operation contracts, named HC and
escort roles, immutable staged hashes, exact native facade commands,
version/hash review inputs, review/final workbook separation, structural and
SHA-256 verification, published-artifact reuse, native conflict projection,
and import independence. A real managed-Roster worker smoke completed native
start/status and review export, and a blocked publication preserved the native
`PUBLICATION_NOT_READY` error. The full authored package suite passes with
`125 passed`.

A successful real ready-publication smoke, exhaustive native golden payload
comparison, and commit-boundary crash injection remain explicit release
hardening items rather than implied completion evidence.

## 1. Purpose and Scope

This tool implements the complete durable weekly roster workflow from an HC
workbook, an escort workbook, a target week, and temporary changes through
audit review, revalidation, review export, and ready-only final publication.
The first release exposes `start`, `status`, `review`, `revalidate`, `export`,
`publish`, and `get_published` through the one public tool `roster_copilot`.

This plan owns Roster-specific implementation. The architecture owns the
cross-tool MCP host, envelopes, shared job database, file staging, artifact
registry, one-shot worker protocol, runtime bootstrap, operation replay, and
failure-state checkpointing.

## 2. Independent Code Boundary

### 2.1 Required Module Tree

```text
NGOPilotMCP/
  src/ngopilot_mcp/tools/roster_copilot/
    __init__.py
    manifest.py
    schemas.py
    controller.py
    validation.py
    native_adapter.py
    state.py
    artifacts.py
  tests/tools/roster_copilot/
    test_schemas.py
    test_controller.py
    test_native_adapter.py
    test_artifacts.py
    test_independence.py
```

| Module | Tool-local responsibility |
|---|---|
| `manifest.py` | Host-safe public name, description, worker target, and operation list |
| `schemas.py` | Strict Roster operation discriminated union; results use the shared `ToolExecution` envelope |
| `controller.py` | Roster workflow orchestration over shared host services |
| `validation.py` | Roster input-role, workbook, week, and changes-envelope validation |
| `native_adapter.py` | Worker-only conversion between the shared worker envelope and pinned Roster Python calls |
| `state.py` | Interpretation of shared job state and public-to-native identity mappings |
| `artifacts.py` | Roster review/final workbook verification and promotion semantics |
| `tests/tools/roster_copilot/` | Roster-only contract, controller, native-boundary, artifact, and independence coverage; shared runtime tests own generic replay/failure-state checks |

`__init__.py`, `manifest.py`, and schema discovery must be safe to import in
the MCP host. They must not import RosterCopiilot's top-level `app` package.
`native_adapter.py` is loaded only inside the managed Roster worker;
`controller.py` reaches it through the shared worker client.

### 2.2 Dependency Rules

This package may import sibling modules and stable shared host APIs. It must
not import any other package below `ngopilot_mcp.tools`, and no other tool may
import it. The shared host discovers it through `manifest.py`, not through a
tool-to-tool dependency.

This tool owns only its schemas, controller, native adapter, validation, state
interpretation, artifact semantics, manifest, and tests. It must not create a
private job database, staging layer, artifact registry, worker client, virtual
environment, app-data root, resources root, or runtime root. Similar
tool-specific code stays local rather than moving into a shared CareFlow/Roster
adapter with conditionals.

### 2.3 Responsibility Split

| Owner | Responsibilities |
|---|---|
| Shared NGOPilotMCP host | MCP transport/envelopes, registration, SQLite job/operation/artifact rows, per-process job locks, directory creation, file staging, artifact promotion, one-shot worker protocol, runtime bootstrap, request replay, and failure-state checkpointing |
| `tools/roster_copilot` | Roster contracts, controller, validation, native call selection/adaptation, state interpretation, artifact rules, and tests |
| RosterCopiilot 0.6.0 | Workbook parsing, master-data lowering, demand construction, scheduling, provenance, impact analysis, reconciliation, preflight, immutable review versions, decision validation, compare-and-swap persistence, workbook generation, and ready-only publication |

## 3. Ownership and Native Authority

NGOPilotMCP owns immutable staged HC/escort copies, their hashes and role
assignments, normalized MCP requests, native result snapshots needed for
review/recovery, promoted review/final workbooks, artifact records, public job
state, and recovery metadata.

RosterCopiilot remains authoritative for its native run, schedule versions,
content hashes, dependency groups, decisions, overrides, preflight reports,
publication state, publication records, and native artifact hashes. The
adapter reuses `app.api.demo` and Roster services directly without ASGI/HTTP.
It records returned results but never independently calculates or edits native
domain values.

The built-in division template and persisted Roster master data are native
algorithm inputs, not tool-private resources. Their effective revision or
version is recorded in MCP job metadata for traceability.

## 4. MCP Tool Contract

The shared request envelope uses a strict discriminated union on `operation`.
Unknown fields and payloads for another operation are rejected. Existing-job
operations require the public MCP `job_id`; `state.py` resolves it to the
native Roster `run_id`.

### 4.1 Start Input

```json
{
  "operation": "start",
  "job_id": null,
  "input": {
    "hc_workbook_path": "/absolute/2026_HC timetable.xlsx",
    "escort_workbook_path": "/absolute/escort master.xlsx",
    "week_start": "2026-08-03",
    "changes": []
  }
}
```

Validation and routing contract:

- Both paths are required, absolute, existing, regular, non-empty files.
- Only `.xlsx` and `.xlsm` are accepted, case-insensitively.
- Preserve the current default 10 MB compressed size limit per workbook.
- The shared staging service creates immutable job-local copies before Roster
  opens either file.
- The HC path always routes to the HC importer and the escort path always
  routes to the escort importer; generic or positional workbook arrays are
  forbidden.
- The HC importer expects sheet `52026`, row-3 headers, and five fixed
  seven-column blocks beginning at columns 1, 8, 15, 22, and 29.
- The escort importer expects sheet `1月`, rows 6 through 147, and cached
  formula values. Files not recalculated/saved by Excel may lack
  formula-derived dates.
- `week_start` is an ISO date. The native builder aligns a non-Monday date
  backward to Monday and returns its warning; the adapter preserves it.
- `changes` is an array supporting native types `leave`,
  `elder_cancellation`, `escort_new`, and `escort_cancelled`.

MCP validates that `changes` is an array of objects. Domain interpretation
stays native. Unlike the original `changes_json` string path, malformed
transport JSON or non-object members are rejected before they can be silently
ignored.

Start preserves this native chain:

```text
WeeklyRosterDemoBuilder.build
  -> run_scheduler
  -> prepare_generated_division_roster_export
  -> RosterStore.create_weekly_run
```

The result preserves the native full payload: run/week, publication state,
parse/generation/change summaries, current version, impact reports, audit
items, dispositions, evidence, data gaps, unassigned items, reconciliation,
export report, decisions, overrides, and publication metadata.

### 4.2 Review Input

`operation="review"` passes the exact native `WeeklyReviewCommand`:

```json
{
  "source_version_id": "required-current-version",
  "content_hash": "required-current-hash",
  "idempotency_key": "required",
  "actor": "required",
  "action": "approve",
  "audit_id": "required",
  "audit_ids": [],
  "note": null,
  "override_note": null,
  "edited_entry": null
}
```

Preserved rules:

- `action` is `approve`, `reject`, or `edit`.
- `audit_id` plus `audit_ids` must identify the complete native dependency
  group.
- `reject` and `edit` require `note`.
- `edit` requires `edited_entry`; the other actions cannot supply it.
- Editable native fields are `worker_id`, `schedule_date`, `period`,
  `session_index`, `start_time`, `end_time`, and `notes`, plus the identity
  required by the native command.
- Only `edit` may supply `override_note`. A hard-rule-violating edit requires
  it and remains blocked; an unnecessary override is rejected.
- Every mutation targets the exact current immutable version/content hash;
  stale calls fail closed.

Review preserves this chain:

```text
apply_weekly_review
  -> full export preflight of immutable child
  -> RosterStore.save_weekly_run_decision (compare-and-swap)
```

### 4.3 Operations and Artifacts

| Operation | Required payload | Native effect | MCP result |
|---|---|---|---|
| `start` | HC path, escort path, week, optional changes | Parse, schedule, preflight, persist | Full current run and new public `job_id` |
| `status` | `job_id` | Load and verify durable run | Full current run |
| `review` | Exact version/hash and review command | Immutable atomic transition | New current version or native conflict |
| `revalidate` | Exact `source_version_id`, `content_hash` | Rebuild/compare preflight without new version | Same version plus revalidation result |
| `export` | `job_id` | Write native review workbook when permitted | Registered absolute review path |
| `publish` | Actor and exact version/hash | Fresh preflight and ready-only publication | Publication and registered absolute final path |
| `get_published` | `publication_id` | Validate existing immutable publication | Registered absolute final path |

`export` means review export, never publication. It may succeed for a safe,
labelled draft while publication state is `draft`; native export-preflight
failure blocks it.

`publish` preserves the native publication lock, fresh preflight,
`publication_state == "ready"`, temporary write plus atomic replace, SHA-256
record, and idempotent retry. It creates
`照顧員工作分工表_正式版.xlsx` but sends it nowhere.

After native export/publication, the shared artifact service verifies and
snapshots the bytes into job `outputs/`. Responses return that MCP-owned
absolute path, ending in `照顧員工作分工表_審核草稿.xlsx` or
`照顧員工作分工表_正式版.xlsx`. Native paths are provenance metadata only.

### 4.4 Persisted Global Inputs

The MCP SQLite job record and native references retain the division-template
path/hash, master-data version, staged workbook hashes/display names, target
week, structured changes, native `run_id`, current version/content hash, and
dependency version `0.6.0`. The lightweight `manifest.json` projects current
state, native references, artifacts, warnings, and errors. This prevents
treating the two workbooks as the complete algorithm input.

Browser workspace pointers and archives are ancillary features, not job
identity, and remain outside first-release parity.

## 5. Runtime State

```text
<state>/
  jobs.sqlite3
  jobs/
    roster_copilot/
      <job_id>/
        manifest.json
        inputs/
        intermediate/
        outputs/
        logs/
  app-data/
    rostercopiilot/
      roster.db
      exports/
  runtimes/
    rostercopiilot/
      .venv/
```

`jobs.sqlite3` is the shared MCP job database and is initialized by the shared
`JobStore`. The namespaced job directory is created by the host: `inputs/`
holds immutable staged files, `intermediate/` is reserved for snapshots,
`outputs/` holds promoted registered artifacts, and `logs/` holds worker
records. Logs are bounded beneath the private job directory; general
content-redaction and automated retention are not implemented.

The shared worker client starts a one-shot Roster subprocess in
`runtimes/rostercopiilot/.venv/` and sets `ROSTER_DB_PATH` to the absolute
`app-data/rostercopiilot/roster.db` path and `ROSTER_EXPORT_DIR` beneath
`app-data/rostercopiilot/exports/`. These are managed Roster app data and
runtime infrastructure, not tool-private state.

The shared job row is authoritative for MCP lifecycle. It maps public
`job_id` to native `run_id`, current native version/hash, staged inputs,
intermediate checkpoints, native publication IDs, and registered artifacts.
The native Roster store remains authoritative for domain state. Intermediate
snapshots preserve returned results but never recompute or replace it.

## 6. Native Call Boundary

The host sends validated operations through the shared versioned worker
envelope. Only worker-side `native_adapter.py` imports `app.*`; it converts
dates/paths, calls Python services directly, and returns JSON-safe payloads or
native artifact descriptors.

| Operation | Required native call path |
|---|---|
| `start` | `WeeklyRosterDemoBuilder.build` -> `run_scheduler` -> `prepare_generated_division_roster_export` -> `RosterStore.create_weekly_run` -> demo response assembly |
| `status` | `RosterStore.get_weekly_run` -> demo reconstitution with canonical preflight verification -> response assembly |
| `review` | Load exact record -> `apply_weekly_review` -> full preflight -> `RosterStore.save_weekly_run_decision` CAS -> response assembly |
| `revalidate` | `validate_current_version` -> reconstitution with rebuilt preflight/stored-plan comparison; same version, `revalidated=true`, `version_unchanged=true` |
| `export` | Reconstitute current run -> `save_generated_division_roster_workbook` with its prepared native plan |
| `publish` | `weekly_publication_lock` -> load inside lock -> `publish_weekly_run` -> `RosterStore.save_weekly_run_publication` |
| `get_published` | Load run -> resolve `publication_id` -> validate recorded immutable path and SHA-256 |

The adapter preserves native structured error codes/context. It must not
start ASGI, call HTTP, rebuild response/domain algorithms, weaken preflight,
or mutate Roster state outside these native write boundaries.

## 7. Operation Implementation Tasks

### 7.1 `start` and `status`

1. Parse `start`, require `job_id: null`, and allocate the shared job/lock.
2. Validate, stage, role-label, and hash both workbooks; pass only staged paths
   to the worker. Validate the date and changes envelope without interpreting
   domain semantics.
3. Invoke the native start chain; checkpoint the native `run_id`, global-input
   versions, current version/hash, and full returned response before success.
4. Implement `status` by resolving native `run_id`, loading/reconstituting the
   durable run, snapshotting its returned state, and never rerunning parsing or
   scheduling.

Exit condition: one public job maps to exactly one native run, and `status`
restores the same version after host/worker restart and source-file removal.

### 7.2 `review` and `revalidate`

1. Parse exact command fields and reject extras before worker invocation.
2. Under the shared job lock, pass the native run and exact version/hash to
   Roster. MCP enforces the transport/action shape; Roster remains authoritative
   for dependency groups, hard rules, overrides, idempotency, and CAS.
3. Record decision/resulting version only after native CAS commit; stale or
   conflicting calls cannot advance MCP metadata.
4. Revalidate through native current-version and rebuilt-preflight checks;
   preserve the native unchanged indicators and returned version/hash without
   independently recalculating them.

Exit condition: parity covers atomic groups, immutable children, stale writes,
overrides, idempotent replay, CAS, and no-new-version revalidation.

### 7.3 `export`

1. Serialize against conflicting job operations and invoke the native review
   writer with the durable current run/prepared plan.
2. Require native preflight success; verify a non-empty readable workbook and
   calculate SHA-256 without rewriting content.
3. Promote through the shared registry into `outputs/`, preserve native path
   only as metadata, and return the registered MCP path.

Exit condition: the returned path is inside job `outputs/`, its hash matches
the registry, and later native-file changes cannot alter it.

### 7.4 `publish` and `get_published`

1. Require actor and exact version/hash; use the native lock, reload, fresh
   preflight, ready-only check, atomic file write, and publication-store commit.
2. Verify final bytes against the native publication SHA-256, promote them to
   `outputs/`, and map native `publication_id` to the shared artifact.
3. Implement `get_published` by validating the native record/hash and returning
   the verified promoted path without republishing.
4. `get_published` can promote an existing verified native publication when
   its ID is known. The host does not automatically reconcile an ambiguous
   publish/promotion crash.

Exit condition: blocked/draft/stale publication creates no final artifact;
exact retries return the same publication and registered bytes.

## 8. Failure, Concurrency, and Recovery Rules

- The router's per-job lock supplements, and never replaces, native
  version/hash guards, review idempotency/CAS, and publication locking.
- MCP job metadata advances only after a successful worker response; the job
  snapshot is written before the operation response is marked succeeded.
- A failed follow-up preserves the last successful state and next-operation
  set. Retrying the same `request_id` replays that recorded failure; a new
  request ID performs an explicit new attempt.
- Missing, corrupt, or tampered promoted artifacts fail closed; publication
  additionally verifies the native authoritative SHA-256.
- Native structured error codes are projected without returning unrestricted
  stack traces in the MCP response.

The current host has no cross-process lease, native commit receipt, or automatic
reconciliation loop. It therefore does not yet prove that an ambiguous crash
after native start/review/publication can always resume without repeating a
native call. That limitation is tracked by RC-11 and must not be inferred from
the implemented request replay.

## 9. Ordered Milestones

| Milestone | Status | Completion evidence / remaining gate |
|---|---|---|
| 1. Boundary and schemas | Complete | Eight modules, all seven strict variants, and import-independence tests pass. |
| 2. Shared job integration | Complete | Named-role staging, hashes, shared SQLite operations, per-job serialization, replay, and promotion are wired and tested. |
| 3. Worker, start, status | Complete for principal path | Pinned direct facade calls, native run mapping, source-independent status, and a real worker start/status pass. Crash-time duplicate-run reconciliation is not fault-injection tested. |
| 4. Review and revalidation | Complete for contract boundary | Exact native commands, strict action rules, conflict-code projection, and immutable identity routing pass. Exhaustive native CAS/version golden fixtures remain open. |
| 5. Review export | Complete | Native writer call, distinct review filename/kind, structural verification, promotion, and real worker review export pass. |
| 6. Publication | Implemented; real success smoke open | Ready-only native facade, exact version/hash request, SHA-256 verification, promotion, and `get_published` reuse pass controller tests; real worker blocked publication preserves `PUBLICATION_NOT_READY`. |
| 7. Release parity | Partial | Tool/full suites and source-runtime smokes pass. This tool's installed-wheel lifecycle, crash/corruption matrices, and real ready-publication remain release work. |

## 10. Acceptance Matrix and Current Evidence

| ID | Acceptance criterion | Status | Current evidence / missing evidence |
|---|---|---|---|
| RC-01 | All seven operations accept only their documented payloads. | Verified | Strict schema tests cover start, review action combinations, revalidate, publish, and get-published. |
| RC-02 | Invalid workbook paths, size/type/content, and HC/escort role swaps fail before native invocation. | Verified for supported cases | Validation and named-role controller tests; device/FIFO and decompression-bomb cases remain hardening. |
| RC-03 | Start preserves original filenames, structured changes, native run identity, and full native result projection. | Verified for principal path | Native facade and controller assertions plus real worker start/status. Exhaustive normalized run-payload golden comparison is open. |
| RC-04 | Review preserves dependency-group commands, exact version/hash, native conflicts, immutable child effects, and CAS authority. | Verified for call boundary | Strict schemas, exact command construction, controller routing, and native conflict-code test. Exhaustive native CAS fixtures are open. |
| RC-05 | Revalidate passes exact version/hash, preserves native preflight, and creates no MCP artifact/version. | Verified for call boundary | Command construction and controller identity routing; full native before/after golden version comparison is open. |
| RC-06 | Review export is distinct from publication and produces a structurally valid promoted review workbook. | Verified | Native writer, controller, artifact tests, and real worker review export. |
| RC-07 | Publish is ready-only for the exact version/hash; final artifact hash is native-authoritative; get-published reuses the promoted artifact. | Verified in controller; real blocked path verified | Publish/get controller and hash tests plus real `PUBLICATION_NOT_READY`. A real ready-publication success remains open. |
| RC-08 | Every workbook path is absolute, namespaced, registered, SHA-256 verified, and independent from its native path. | Verified | Controller/artifact/shared-runtime tests. |
| RC-09 | Restart/status no longer depends on caller workbooks and public-to-native identity remains durable. | Verified for persisted identity | SQLite mappings and staged inputs are durable; real restart after source deletion is not separately automated. |
| RC-10 | Corrupt or hash-mismatched native/promoted files fail closed. | Verified for output boundaries | Corrupt workbook and publication hash tests; intermediate snapshot tamper injection is open. |
| RC-11 | Commit-boundary crashes produce no duplicate run, review child, publication, or artifact. | Partial | Request replay and artifact uniqueness exist; exhaustive native-commit crash receipts/reconciliation are not implemented. |
| RC-12 | No tool-to-tool/host `app` imports or tool-private infrastructure exist; Roster runs independently of CareFlow tools. | Verified | AST/import and package-contract tests plus separate worker/venv configuration. |
| RC-13 | Logs exclude workbook/elder data and publish has no external delivery side effect. | Partial | No external send path exists. Injected-sensitive-data scans across all worker failure logs are not automated. |

Tool implementation exit is satisfied for all seven operations, review export,
blocked-publication parity, artifact ownership, and independence. Release
closure still requires RC-11/RC-13 hardening, a real ready-publication smoke,
and this tool's installed-wheel lifecycle.

## 11. Deferred and Out of Scope

Browser workspace pointers, archives, generic import/schedule/export support
routes, and master-data administration remain outside the first release. Any
future addition extends this tool's operation union and tests; it does not
justify another MCP tool or a cross-tool implementation dependency.
