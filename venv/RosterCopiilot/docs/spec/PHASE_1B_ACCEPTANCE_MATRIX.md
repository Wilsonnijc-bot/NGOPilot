# Phase 1B Acceptance Matrix

**Status:** A-E engineering gates implemented; real NGO evidence pending
**Companion:** `PROVENANCE_AND_PUBLICATION_SPEC.md`

Every row needs an automated negative-path assertion where failure could make
an unsafe workbook look publishable. Packages are implemented sequentially;
the full gate runs after each package.

The automated package evidence is green in the current working tree. This is
not the NGO gate: confirmed master data and two NGO-selected,
roster-owner-signed comparison weeks are still external requirements.

## A. Provenance and demand conservation

| ID | Acceptance | Required proof |
| --- | --- | --- |
| A-01 | Identical normalized inputs reproduce identical `demand_id` values across two runs. | Unit test over fixed, HC, escort, duty, and change-derived demand. |
| A-02 | Parser/list ordering does not change IDs or disposition counts. | Shuffle inputs; compare canonical report excluding run/version IDs. |
| A-03 | Adapter and engine preserve demand ID, source evidence, gap IDs, and assumptions. | Snapshot -> Task -> ScheduleEntry assertions. |
| A-04 | Normal week-pattern and out-of-week exclusions are diagnostics, not weekly demands. | Denominator excludes them and records exclusion reason. |
| A-05 | Every weekly demand has exactly one of the five terminal dispositions. | Conservation assertion over baseline, cancellation, suppression, repair, and unassigned cases. |
| A-06 | Zero and duplicate dispositions fail reconciliation and block publication. | Construct both invalid versions; assert structured error. |
| A-07 | A seed/unknown fact used by a placement produces `needs_review` with linked gap/audit; it never stays ordinary `scheduled`. | Worker seed skill, unknown gender, unknown route fixtures. |
| A-08 | Shared data-gap audits deduplicate while all affected entries retain links. | One worker gap affecting at least two entries. |
| A-09 | Unassigned and export-failure demand each reconcile to exactly one terminal blocking audit and one RC_未分配 item; duty uses `duty_under_coverage` without a duplicate blocker. | Scheduler, duty-shortfall, and forced mapper-failure tests. |
| A-10 | API payloads expose structured source evidence, demand/disposition IDs, and one reconciliation report. | Weekly demo API schema assertions. |
| A-11 | Every export placement exposes exact assignment/detail cells plus demand, entry, audit, gap, and evidence IDs. | Export-plan manifest assertion. |
| A-12 | Every review comment starts `RC:待審` and contains reason, audit, demand, entry, and source evidence. | Open workbook and assert exact comment lines. |
| A-13 | API, UI input model, RC sheets, and RC_meta use identical disposition/audit totals. | Workbook/API reconciliation test. |

## B. Persistent weekly runs and review state

| ID | Acceptance | Required proof |
| --- | --- | --- |
| B-01 | A created weekly run, snapshot, dataset, current version, and report survive app/store restart. | Temporary SQLite restart test. |
| B-02 | Schedule versions are append-only; a decision creates a child and leaves the parent byte-equivalent. | Hash parent before/after decision. |
| B-03 | Decisions persist actor/time/note/action/source/result version, validator result, and idempotency key. | Store round trip and duplicate-request test. |
| B-04 | Edited decisions persist a linked ManualOverride with audit/decision/run/version provenance. | Store and model round trip. |
| B-05 | Existing POST response and review-draft export URL remain compatible after `_RUNS` removal. | Existing weekly-demo tests plus restart export. |
| B-06 | Missing/corrupt persisted run data returns a structured fail-closed error, never a fresh silent rerun. | Negative store/API test. |

## C. Review APIs and existing UI

| ID | Acceptance | Required proof |
| --- | --- | --- |
| C-01 | GET run returns the durable current version and reconciliation report. | API restart test. |
| C-02 | Approve transitions the intended suggestion and creates/revalidates a child version. | API test with parent immutability. |
| C-03 | Reject requires a note and records a supervisor hard-bypass: the kept (or week-cancelled) terminal entry carries the `supervisor_hard_bypass` flag and the waived blocker stops re-blocking export. | 422 without note; hard-bypass disposition and flag after valid reject. |
| C-04 | Edit revalidates; a violating edit without override note is rejected. | Skill/time/gender negative cases. |
| C-05 | A violating edit with override note may persist only as `blocked`, never `ready`. | Publication assertion. |
| C-06 | Dependency/displacement decisions are atomic. | Partial decision attempt rejected. |
| C-07 | Revalidation is idempotent and does not duplicate audits or change stable IDs. | Call twice; compare IDs/counts. |
| C-08 | UI keeps upload -> generate -> review -> download in one flow and exposes approve/edit/hard-bypass beside existing review items. | Copy guard plus live browser checks. |
| C-09 | UI totals and publish state come from the server reconciliation report. | Frontend fixture assertion; no independent count formula. |
| C-10 | Two racing decisions against the same source version commit exactly once: the loser gets a structured 409, no partial version/decision/override persists, and same-key retries replay the committed decision. | Concurrent API tests plus store-level CAS rollback test. |
| C-11 | Review controls disable immediately on submission with a visible processing state; a stale 409 automatically reloads the current run. | Frontend copy guard plus live browser double-click check. |

## D. Final publication

| ID | Acceptance | Required proof |
| --- | --- | --- |
| D-01 | Review-draft download semantics and filename remain unchanged. | Existing download test. |
| D-02 | Final publication is a separate action and rejects `blocked` and `draft` with 409 plus reasons. | API tests for both states. |
| D-03 | Final action revalidates the exact current version/content hash and rejects stale requests. | Modify/current-version race test. |
| D-04 | Only `ready` produces `照顧員工作分工表_正式版.xlsx`. | Ready fixture test and workbook open. |
| D-05 | Published version is frozen and recorded with actor/time/artifact metadata. | Restart persistence test. |

## E. Reconciliation and parallel-run harness

| ID | Status | Acceptance | Required proof |
| --- | --- | --- | --- |
| E-01 | Implemented | Reconciliation metrics are deterministic and omit runtime timing. | Repeat test; compare canonical JSON bytes. |
| E-02 | Implemented | Harness accepts two explicit week cases, generated run data, and manual comparison workbooks/JSON or CSV ledgers without inventing missing demand. | CLI and library tests with temporary fixtures. |
| E-03 | Implemented | Ledger classifies every diff as expected, reviewer-approved, or blocking; uncategorized diffs fail. | Positive and negative fixture ledgers, including cell/value/link mismatches. |
| E-04 | Implemented; NGO evidence pending | Harness reports NGO confirmation/sign-off separately from engineering pass. | Missing sign-off returns `ngo_gate=pending`; synthetic complete-evidence contract test. |
| E-05 | Implemented | Fixture smoke runs never claim NGO parallel-run acceptance. | `scope=fixture_smoke` output assertion. |

Automated evidence lives in `backend/tests/test_parallel_run.py`. The tests use
synthetic workbooks and sign-off identifiers only; they do not satisfy the real
NGO-dependent gate in `PROVENANCE_AND_PUBLICATION_SPEC.md` section 13.

## F. Full package gate

After every package A-E, run:

```bash
.venv/bin/python -m pytest
.venv/bin/python backend/scripts/inspect_division_import.py
.venv/bin/python backend/scripts/inspect_escort_import.py
.venv/bin/python backend/scripts/inspect_hc_import.py
.venv/bin/python backend/scripts/run_benchmark.py --json /tmp/rostercopiilot_benchmark.json
```

For packages C/D, serve the actual application and verify 1280 px, 820 px, and
390 px widths: Traditional Chinese copy, no overlap or horizontal overflow, no
console errors, and working generate/review/review-download/final-publication
state transitions.

## G. Agent package boundaries

| Package | Allowed focus | Explicit non-goals |
| --- | --- | --- |
| Agent A | Domain provenance fields/helpers, generation/adapter/engine propagation, audit/export/API serialization, A tests | persistence, review endpoints/UI, final publish |
| Agent B | Weekly-run repository/service, immutable version/decision/override durability, B tests | review UI, publish action |
| Agent C | Approve/edit/reject/revalidate APIs and in-place wizard integration, C tests | final artifact, optimization |
| Agent D | Ready-only final publication and artifact metadata, D tests | changing review-draft semantics |
| Agent E | Reconciliation metrics/ledger and two-week harness, E tests/docs | claiming NGO sign-off or fabricating data |
