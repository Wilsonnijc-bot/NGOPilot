# RosterCopiilot

RosterCopiilot is an NGO roster-scheduling system. The product goal is **not**
to make the NGO upload several Excel workbooks every week. The current Excel
files are primarily reverse-engineering evidence: they tell us the NGO's roster
rules, vocabulary, slot geometry, colours, and final workbook format.

Current app version: `0.6.0`.

## Product Direction

The scheduler should use the reverse-engineered rules in `docs/spec/` to draft
worker rosters, surface risky changes for human review, and export a familiar
`照顧員工作分工表2026(HKU).xlsx`-style workbook for staff.

The current demo path is:

```text
內置照顧員工作分工表固定基礎/模板
        + 使用者上載 HC 時間表
        + 使用者上載護送總表
        + 本週臨時變更
        -> 自動生成照顧員工作分工表格式 Excel
```

In this demo, the division workbook is not a normal user upload. It is the
system's built-in fixed roster base and export template. The uploaded HC and
escort workbooks directly drive the generated weekly draft.

The implemented workbook import pipeline is support tooling:

- to verify the reverse-engineering result against the sample files;
- to keep source-cell evidence for rules and fixtures;
- to regression-test the NGO workbook writer;
- not to define the normal product workflow as "upload three workbooks."

## Current State

Implemented:

- `SchedulerSnapshot` input contract, task generator, and bridge into the
  deterministic greedy scheduler / change repair engine.
- Representative scheduler fixture that produces a draft roster without reading
  Excel at solve time.
- Store-backed app state using SQLite/SQLModel.
- Reverse-engineering support importers for the sample workbook families:
  - `docs/照顧員工作分工表2026(HKU).xlsx`
  - `docs/2026_HC 時間表(HKU).xlsx`
  - `docs/護送個案總表(2026)(HKU).xlsx`
- Import batch persistence and ambiguity endpoints, treated as developer/demo
  tooling rather than the product's primary input path.
- User-facing demo endpoint `POST /api/demo/weekly-roster`:
  built-in division base + uploaded HC workbook + uploaded escort workbook +
  temporary changes -> generated `ScheduleVersion`.
- NGO-format division workbook exporter that preserves the original workbook
  layout, writes generated roster entries back into `恆常服務`, and adds
  `RC_*` review sheets.
- Export preflight for generated division workbooks: hard-rule revalidation,
  cell-placement manifest, export-failure reconciliation, and blocked/draft/
  ready publication state before the template grid is mutated.
- Stable demand/source/gap/entry/audit provenance, one terminal disposition per
  weekly demand, and exact exported-cell traceability shared by API and RC
  sheets.
- SQLite-backed weekly runs with immutable schedule-version lineage, durable
  approve/edit/hard-bypass decisions, manual overrides, and restart-safe
  revalidation. The current-version pointer advances through a database-level
  compare-and-swap, so concurrent decisions commit exactly once and stale
  requests receive a structured 409.
- A durable workspace pointer that restores the reviewer's current run after a
  browser refresh, plus named immutable run archives with editable copies
  forked from an archived version.
- A separate ready-only final-publication action. It records the publishing
  actor, exact version/content hash, immutable artifact metadata, and SHA-256;
  blocked or draft versions remain review-only.
- A deterministic two-week comparison harness for generated run JSON, the
  roster owner's manual workbook, and an explicit classification ledger.
- Scheduler-produced assignment-grid exporter for the draft roster.
- Static frontend wizard for upload -> generate -> review/revalidate -> review
  download -> explicit ready-only final publication.

Not completed for production yet:

- NGO-confirmed worker/elder skills, genders, routes, availability, rule
  configuration, and operational ownership of the maintained master data.
- Two NGO-selected, roster-owner-signed parallel-run weeks with zero
  uncategorized or blocking differences.
- Production role/access controls, backup/restore operations, training, and
  deployment runbooks.
- CP-SAT or any global optimization solver.
- Treating unconfirmed NGO semantics as hard rules.

## Project Layout

```text
backend/app/api/        FastAPI routers
backend/app/domain/     Canonical scheduling/domain models
backend/app/engine/     Deterministic scheduler, repair, validation, metrics
backend/app/importer/   Reverse-engineering support parsers and ambiguity models
backend/app/exporter/   NGO-format workbook writer and export preflight
backend/app/evaluation/ Deterministic two-week comparison and gate metrics
backend/app/store/      SQLite/SQLModel persistence
backend/app/services/   App state facade, weekly demo builder, simplified export
backend/scripts/        Benchmark, inspectors, and demo scripts
backend/tests/          Unit, integration, importer, exporter, and API tests
docs/                   Documentation index, evidence, specs, records, and archives
frontend/index.html     Static demo UI
```

文档入口见 `docs/README.md`；繁體中文操作說明見 `docs/使用說明.md`。

## Setup

Use Python 3.11 or newer.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

Run the API:

```bash
.venv/bin/python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

Serve the static frontend on an allowed local origin:

```bash
python3 -m http.server 3000 --directory frontend
```

Then open `http://127.0.0.1:3000/`. The static page resolves its API origin
automatically: an explicit `localStorage.rc_api_base` override wins; a
`file://` page or a non-`8000` localhost static server (the dev flow above)
falls back to `http://localhost:8000`; anything else uses the **same origin**
(relative `/api/...`), which is what the reverse-proxy deployment relies on.
Icons are served from the vendored `frontend/vendor/lucide.min.js` (no external
CDN); the page still renders if that file is missing.

Useful environment variables:

```bash
export ROSTER_DB_PATH=/tmp/rostercopiilot.db
export ROSTER_EXPORT_DIR=/tmp/rostercopiilot_exports
# Deployment hardening (see deploy/ubuntu/):
export ROSTER_ENV=production          # disables /docs, /redoc, /openapi.json
export ROSTER_CORS_ORIGINS=""         # same-origin only (never use "*")
export ROSTER_MAX_UPLOAD_MB=10        # per-workbook upload cap (413 above it)
export ROSTER_API_TOKEN=...           # optional bearer/X-API-Key gate for API clients
```

If unset, the app writes to `data/roster.db` and `data/exports/`, both ignored by
git. For a hardened Ubuntu (Nginx + systemd) deployment of the supervised demo,
see [`deploy/ubuntu/README.md`](deploy/ubuntu/README.md).

## Useful Developer Flows

Health:

```bash
curl http://localhost:8000/api/health
```

Run the scheduler demo against the compatibility dataset:

```bash
curl http://localhost:8000/api/changes/examples
curl -X POST http://localhost:8000/api/schedule/generate \
  -H "Content-Type: application/json" \
  -d '{"changes":[]}'
```

The scheduler-first product boundary is `POST /api/schedule/solve`; it accepts a
`SchedulerSnapshot` JSON body and returns a draft `ScheduleVersion` plus task
generation stats.

Run the user-facing weekly demo with two uploaded workbooks:

```bash
curl -X POST http://localhost:8000/api/demo/weekly-roster \
  -F "hc_workbook=@docs/2026_HC 時間表(HKU).xlsx" \
  -F "escort_workbook=@docs/護送個案總表(2026)(HKU).xlsx" \
  -F "week_start=2026-01-05" \
  -F 'changes_json=[]'
```

The response includes `export_url`. Download the review draft workbook:

```bash
curl http://localhost:8000/api/demo/weekly-roster/{run_id}/export \
  --output "照顧員工作分工表_審核草稿.xlsx"
```

The weekly-demo response also includes `publication_state`,
`publication_label`, `review_export_allowed`, `export_block_reasons`, and
`export_report`. `review_export_allowed` means only that the preflight permits
writing a clearly labelled review draft; it never means the workbook is ready
to distribute. Only `publication_state=ready` is publishable. If hard-rule
revalidation or cell placement fails, the export endpoint returns
`409 EXPORT_PREFLIGHT_FAILED` and does not mutate the staff-facing grid.

Read or revalidate the durable current run:

```bash
curl http://localhost:8000/api/demo/weekly-roster/{run_id}
curl -X POST http://localhost:8000/api/demo/weekly-roster/{run_id}/revalidate \
  -H "Content-Type: application/json" \
  -d '{"source_version_id":"{version_id}","content_hash":"{content_hash}"}'
```

Review decisions use the exact current version/hash and create immutable child
versions. Reject/edit require a note; an invalid edit requires an override note
and remains blocked:

```bash
curl -X POST http://localhost:8000/api/demo/weekly-roster/{run_id}/review-decisions \
  -H "Content-Type: application/json" \
  -d '{"source_version_id":"{version_id}","content_hash":"{content_hash}","idempotency_key":"review-001","actor":"supervisor","action":"approve","audit_id":"{audit_id}"}'
```

Only a server-revalidated `ready` version accepts the separate final action:

```bash
curl -X POST http://localhost:8000/api/demo/weekly-roster/{run_id}/publish \
  -H "Content-Type: application/json" \
  -d '{"actor":"supervisor","source_version_id":"{version_id}","content_hash":"{content_hash}"}'
```

The response supplies `final_export_url`; it downloads
`照顧員工作分工表_正式版.xlsx`. This is an explicit human action, not automatic
distribution.

Export the current schedule into the NGO division workbook format:

```bash
curl -X POST http://localhost:8000/api/export/ngo-format \
  -H "Content-Type: application/json" \
  -d '{}' \
  --output ngo_division_export.xlsx
```

Export the representative scheduler draft as a staff assignment grid:

```bash
curl -X POST http://localhost:8000/api/export/assignment-grid \
  --output assignment_grid.xlsx
```

Reverse-engineering support only: import the default sample workbooks from
`docs/` and inspect parser ambiguities:

```bash
curl -X POST "http://localhost:8000/api/import/workbooks?use_default_docs=true"
curl http://localhost:8000/api/import/batches
curl "http://localhost:8000/api/import/ambiguities?status=pending"
```

## Validation

Run the normal test suite:

```bash
.venv/bin/python -m pytest
```

Run the benchmark:

```bash
.venv/bin/python backend/scripts/run_benchmark.py --json /tmp/rostercopiilot_benchmark.json
```

Run the two-week comparison harness against a manifest prepared with the roster
owner:

```bash
.venv/bin/python backend/scripts/run_parallel_review.py \
  --manifest /path/to/parallel-run/manifest.json \
  --json /tmp/rostercopiilot_parallel_run.json
```

See `docs/evaluation/PARALLEL_RUN_GUIDE.md`. Fixture success proves the harness,
not NGO acceptance.

Inspect the sample workbook parsers:

```bash
.venv/bin/python backend/scripts/inspect_division_import.py
.venv/bin/python backend/scripts/inspect_escort_import.py
.venv/bin/python backend/scripts/inspect_hc_import.py
```

Expected current headline results:

- `pytest`: see current test output.
- Benchmark: 14 scenarios, 0 hard constraint violations.
- Division fixture parse: 46 workers, 370 fixed-service candidates, 0 silently dropped cells.
- Escort fixture parse: 111 schedulable requests, 1 blocking ambiguity.
- HC fixture parse: 57 parsed records, 6 recovered Excel-date-mangled week-pattern cells.

## Next Engineering Target

Do not re-extract the rules. Reuse the strong-agent reverse-engineering results
already in `docs/spec/`, especially:

- `excel_semantics.md`
- `data_dictionary.md`
- `rulebook.md`
- `canonical_schema.md`
- `rescheduling_algorithm.md`
- `human_review_policy.md`

Phase 1A added versioned master data and validator hardening. Phase 1B's
engineering packages now implement demand/source provenance, durable weekly
review decisions, revalidation, ready-only publication, and the two-week
comparison harness. NGO-confirmed employee skills, genders, route eligibility,
elder requirements, and two signed parallel-run weeks remain external
production gates; the repository is not claiming staff readiness.

## Key Specs

- `docs/README.md`
- `docs/spec/README.md`
- `docs/spec/PRODUCT_SPEC.md`
- `docs/spec/ENGINEERING_SPEC.md`
- `docs/spec/api_contract.md`
- `docs/spec/roadmap.md`
- `docs/spec/excel_semantics.md`
- `docs/spec/rulebook.md`
- `docs/spec/excel_io_contract.md`
