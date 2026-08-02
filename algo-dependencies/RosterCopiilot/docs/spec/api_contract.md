# API Contract

**Status:** v0.6.0 stable API plus implemented Phase 1B weekly
review/publication routes. Routes explicitly labelled future remain contracts,
not claims about the current server.
Workbook import endpoints remain support tooling rather than the normal product
workflow.

## 1. Health

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness, app version, engine mode |

## 2. Current User-Facing Demo

The implemented demo path uses the built-in division workbook as fixed base and
output template. Users upload HC and escort workbooks for the target week,
review/revalidate a durable run, and may download a clearly labelled review
draft. A separate named action can produce a final workbook only when the exact
current version has `publication_state=ready`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/demo/weekly-roster` | build a weekly roster from `hc_workbook`, `escort_workbook`, `week_start`, and `changes_json`; saves the workspace pointer |
| GET | `/api/demo/weekly-roster/{run_id}` | load the durable current version, reconciliation, decisions, overrides, and public publication metadata |
| POST | `/api/demo/weekly-roster/{run_id}/review-decisions` | atomically approve, hard-bypass (`reject`), or edit an audit group against the exact current version/hash; the current pointer advances via a database-level compare-and-swap, losers receive a structured 409 `STALE_SCHEDULE_VERSION`, and same-key retries replay idempotently |
| POST | `/api/demo/weekly-roster/{run_id}/revalidate` | rebuild and compare preflight artifacts without creating a new version |
| GET | `/api/demo/weekly-roster/{run_id}/export` | download `照顧員工作分工表_審核草稿.xlsx` when `review_export_allowed=true` |
| POST | `/api/demo/weekly-roster/{run_id}/publish` | freshly preflight and record `照顧員工作分工表_正式版.xlsx`; rejects every state except `ready` |
| GET | `/api/demo/weekly-roster/{run_id}/published/{publication_id}` | download a persisted final artifact after lineage/existence/SHA validation |
| GET/PUT | `/api/demo/workspace` | read or save the single-user pointer to the weekly run the browser restores on refresh |
| GET/POST | `/api/demo/archives` | list immutable archives, or freeze the exact current version of a run as a named read-only snapshot |
| GET | `/api/demo/archives/{archive_id}` | load one frozen archive and its exact stored payload |
| POST | `/api/demo/archives/{archive_id}/editable-copy` | fork a frozen archive into a new independent editable weekly run |

## 3. Current Maintained Master Data

The implemented versioned document and entity-shaped administration surface is
under `/api/master-data`:

| Method | Path | Purpose |
|---|---|---|
| GET/PUT | `/api/master-data` | read or replace the versioned `MasterDataSet` document |
| GET | `/api/master-data/versions` | list immutable master-data versions |
| GET | `/api/master-data/issues` | validation errors and data gaps |
| GET/POST/PUT/DELETE | `/api/master-data/workers[...]` | worker registry |
| GET/POST/PUT/DELETE | `/api/master-data/elders[...]` | elder registry |
| GET/POST/PUT/DELETE | `/api/master-data/fixed-services[...]` | recurring services |
| GET/POST/PUT/DELETE | `/api/master-data/availability[...]` | availability records |
| GET/POST/PUT/DELETE | `/api/master-data/leave-events[...]` | maintained leave events |
| GET/POST/PUT/DELETE | `/api/master-data/temporary-changes[...]` | maintained weekly changes |
| GET/PUT | `/api/master-data/rule-config` | rule configuration |
| GET/POST/PUT/DELETE | `/api/master-data/manual-overrides[...]` | capacity locks and overrides |

## 4. Scheduling

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/schedule/solve` | build a draft baseline schedule from a scheduler snapshot |
| GET | `/api/schedule/versions` | list versions |
| GET | `/api/schedule/versions/{id}` | get full version |
| GET | `/api/schedule/current` | mock-compat current version |
| POST | `/api/schedule/generate` | mock-compat baseline generation |
| POST | `/api/schedule/reset` | reset the compatibility dataset state |
| GET | `/api/schedule/audit` | current compatibility review queue |
| POST | `/api/schedule/audit/{id}/decision` | compatibility decision endpoint |
| POST | `/api/changes/apply` | apply current deterministic change/repair flow |

## 5. Future Production Review Surface

The current four-step product uses the `/api/demo/weekly-roster/...` routes in
section 2. The following normalized/global queue routes remain future contracts:

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/review/queue` | ordered review queue |
| GET | `/api/review/items/{id}` | full review item |
| POST | `/api/review/items/{id}/decision` | approve/reject/edit |
| POST | `/api/review/bulk-decision` | bulk warning/info approval |

## 6. Export

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/export/ngo-format` | current division-sheet-style review export |
| GET | `/api/export/current` | mock-compat review-pack export |
| POST | `/api/export/excel` | current compatibility Excel export |
| POST | `/api/export/assignment-grid` | export a scheduler-produced assignment-grid workbook |

Future async export jobs and staff distribution remain operational work. The
current ready-only final publication is the separate weekly-run action in
section 2; it does not send the file to anybody.

## 7. Support / Reverse-Engineering Tooling

These routes are useful for development, fixture checks, and source-cell
evidence. They should not be presented as the normal product workflow.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/import/workbooks` | parse sample workbooks into ImportBatch evidence |
| GET | `/api/import/batches[/{id}]` | inspect support import batches |
| GET | `/api/import/ambiguities` | inspect parser ambiguities |
| POST | `/api/import/ambiguities/{id}/resolution` | mark a parser ambiguity for demo/testing |
| POST | `/api/import/resolutions` | save alias mapping evidence |

## 8. Conventions

- Every schedule mutation creates a new immutable `ScheduleVersion`.
- Final publication requires `publication_state=ready`, including zero pending
  audits; blocked/draft review workbooks may still be downloaded when export
  preflight is safe.
- Hard-rule violations are bugs, not acceptable draft output.
- Human override is allowed only with a persisted note when it violates a hard
  constraint.
- APIs return aliases/pseudonyms, not real elder names.
