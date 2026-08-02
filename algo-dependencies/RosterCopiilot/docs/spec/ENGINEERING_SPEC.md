# RosterCopiilot — Engineering Specification

**Version:** v0.6.0 stable baseline; Phase 1B review/publication workflow hardened (hard-bypass review, durable workspace/archives, concurrency-safe decisions), NGO gate pending · **Audience:** developers.

This document describes the intended scheduler-first architecture. Existing
workbook import code remains useful support tooling, but it is no longer the
product north star.

## 1. Source Of Truth

Do not re-extract the business rules. Reuse the strong-agent
reverse-engineering outputs:

- `excel_semantics.md`
- `data_dictionary.md`
- `rulebook.md`
- `canonical_schema.md`
- `rescheduling_algorithm.md`
- `human_review_policy.md`
- `../records/fact_check_report_2026-07-01.md`

If these documents conflict, use this precedence:

1. `PRODUCT_SPEC.md` and this file for product/architecture boundaries;
2. `rulebook.md` for business-rule meaning and confidence;
3. active phase contracts (`MASTER_DATA_AND_VALIDATOR_SPEC.md`,
   `PROVENANCE_AND_PUBLICATION_SPEC.md`) for implemented/additive fields;
4. `canonical_schema.md` / `schema.json` as the reverse-engineered conceptual
   model, not a generated runtime schema;
5. `rescheduling_algorithm.md` for target repair behaviour, checking its status
   note for incomplete scenarios;
6. `excel_semantics.md` / `data_dictionary.md` for source evidence;
7. `../reference/importer_implementation_notes.md` and code comments.

The current Pydantic models and tested API payloads decide runtime
serialization when the v0.1 JSON reference schemas omit newer additive fields.

## 2. Correct System Shape

```text
rule/config snapshot
      +
weekly demand / changes / availability
      ↓
task generator
      ↓
eligibility validator + greedy scheduler
      ↓
draft ScheduleVersion
      ↓
independent validation + export preflight
      ↓
labelled review-draft workbook
      ↓
durable human review and revalidation
      ↓
ready-only final publication
      ↓
two-week manual-roster comparison (operational gate)
```

The workbook parser path is auxiliary:

```text
sample workbooks → parser → fixtures / source evidence / regression checks
```

It must not be treated as the required weekly product input.

## 3. Code Layout

```text
backend/app/
├── domain/            # canonical entities: Employee, Elder, FixedService,
│                      # EscortRequest, ScheduleEntry, AuditItem, ChangeEvent
├── engine/            # task generation, eligibility, ranking, scheduler,
│                      # repair, validation, metrics
├── services/          # AppState facade, master-data bridge, impact analysis
├── store/             # SQLite persistence for versions, decisions, support data
├── importer/          # support parsers for reverse-engineering fixtures
├── exporter/          # division workbook writer
├── evaluation/        # deterministic parallel-run comparison and metrics
├── api/               # FastAPI routers
└── mockdata/          # deterministic fixtures retained for tests/benchmarks
```

Dependency direction: `api → services → engine → domain`. The engine must not
read Excel files or import FastAPI/store code.

## 4. Scheduler Input Model

The implemented scheduling boundary is a frozen `SchedulerSnapshot` containing:

- workers with aliases, skills, routes, working hours, Saturday team, leave;
- elders/services with gender requirements, units, districts, exclusive worker
  bindings, status;
- fixed services with weekday, period, session, week pattern, assigned worker;
- escort requests with date, period, appointment time, destination, transport,
  preference strength;
- centre duty requirements;
- meal/logistics tasks;
- active manual overrides;
- solver/ranking config.

The weekly demo builds this snapshot upstream from maintained master data,
target-week uploads, and temporary changes. The engine schedules it without
reading Excel.

## 5. Scheduling Pipeline

Baseline solve:

1. Generate tasks for the target week.
2. Place pinned fixed services where hard constraints allow.
3. Allocate HC, escort, duty, meal, and logistics tasks in priority order.
4. Produce `AuditItem`s for cancellations, replacements, unassigned tasks,
   duty shortfalls, and data gaps.
5. Run independent validation before returning the draft.

Repair solve:

1. Sort events free-before-consume.
2. Detect affected entries.
3. Propose minimal replacement/cancellation/refill.
4. Preserve unrelated assignments where possible.
5. Surface every risky move for review.

## 6. Hard Constraints

The shared eligibility gate and independent validator must cover:

- no double-booking by worker/date/period/session;
- leave and non-working day;
- skill-gated services;
- gender-sensitive services;
- exclusive worker binding;
- `must` escort preference;
- Saturday A/B availability;
- centre duty minimums as blocking shortfalls;
- no silent deletion of tasks.

Unknown gender/skill/route means ineligible or review-required, never assumed
safe.

## 7. Review And Persistence

Every draft schedule is a `ScheduleVersion`. SQLite persists the complete
weekly run document, append-only versions, decisions, entry-scope overrides,
export report/plan, and successful publication records. Loading a run rebuilds
and compares the canonical preflight artifacts; it never silently reruns the
scheduler when durable data is missing or corrupt.

The implemented review contract is:

- approve suggestion;
- reject with note;
- edit with validation and override note when needed;
- approve/reject displacement chains atomically;
- keep unassigned/duty gaps visible until resolved.

Every mutation targets the exact durable current version/content hash and
creates an immutable child. Invalid edits are rejected unless a reviewer gives
an override note; an overridden hard violation persists only as `blocked`.
Revalidation is idempotent and does not manufacture a new version.

## 8. Export Contract

The exporter produces a clearly labelled review draft when review preflight is
safe. A separate endpoint freshly preflights the exact current version and
produces `照顧員工作分工表_正式版.xlsx` only when
`publication_state=ready`. The final artifact is recorded with actor/time,
version/content hash, path, and SHA-256 and is checked on restart/download.
Both forms must:

- preserve the worker-column and weekday/period/session structure;
- write scheduler-produced assignments into the familiar cell grammar;
- preserve business fill-colour semantics;
- mark changes or review-required cells additively with border/comment;
- include `RC_*` sheets when useful for review/audit.

## 9. Existing Support Tooling

Current import endpoints and parsers can stay, but their documentation and UI
must label them as support/demo tooling. The v0.5.0 user-facing demo has a
narrower bridge path: built-in division workbook template + uploaded HC
timetable + uploaded escort workbook + temporary changes. The parsers are useful
for:

- proving the reverse-engineering claims against sample workbooks;
- creating golden fixtures;
- validating source-cell references;
- checking no workbook data is silently dropped during analysis.

They are not the normal operational workflow.

## 10. Standing Regression Priorities

Maintain tests for:

1. task generation from a scheduler snapshot;
2. rule validator coverage for each hard constraint;
3. baseline solve with representative NGO-style tasks;
4. repair scenarios for leave, cancellation, and escort changes;
5. division workbook export from scheduled entries;
6. demand conservation and reciprocal evidence/gap/audit/cell linkage;
7. durable restart, immutable decisions, and stale/idempotent review requests;
8. blocked/draft publication rejection and ready artifact integrity;
9. deterministic two-week comparison with complete diff classification.

Parser round-trip tests are secondary regression checks.
