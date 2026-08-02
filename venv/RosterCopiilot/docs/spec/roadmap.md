# Roadmap — Scheduler-First Path

**Status:** v0.6.0 stable baseline; Phase 1B engineering implemented and review workflow hardened, NGO parallel-run gate pending. Earlier drafts used an import-first Phase 1
framing and explicitly excluded automatic scheduling. That was the wrong product
framing. The Excel workbooks are reverse-engineering evidence and output-format
fixtures; the product is an automatic roster drafter with human review.

Guiding constraint: **the NGO keeps its Excel output workflow**. We change how
the roster is drafted, not what staff receive.

Current demo bridge: the division workbook is built into the system as fixed
base/output template; the user uploads HC and escort workbooks plus temporary
changes, then downloads a generated division workbook draft. This is a demo path,
not the final production data-maintenance model.

## Phase 0 — Mock Scheduling Demo

- **Scope:** deterministic scheduler on realistic mock data; demo leave,
  cancellation, escort demand changes, audit queue, and Excel-style export.
- **Purpose:** prove the review workflow and explainability shape.
- **Non-goals:** real production data, CP-SAT, full NGO rule coverage.
- **Acceptance:** NGO recognises the flow: "system drafts, supervisor reviews,
  final workbook comes out."

## Phase 1 — Rule-Based Scheduler From Reverse Engineering

- **Scope:** reuse the strong-agent reverse-engineering outputs in
  `excel_semantics.md`, `data_dictionary.md`, `rulebook.md`,
  `canonical_schema.md`, and `rescheduling_algorithm.md` to build a scheduler
  input model and task generator.
- **Engineering tasks:**
  - Convert confirmed/inferred rules into config and validator checks.
  - Generate schedulable tasks for fixed services, HC week patterns, escort
    demand, centre duty, meal/logistics tasks, and leave/cancellation events.
  - Connect those tasks to the existing greedy scheduler/repair engine.
  - Export scheduler-produced assignments into the division workbook format.
  - Keep uncertainty as review/audit items, not silent assumptions.
- **Support tooling:** existing workbook parsers may be used to verify samples
  and create fixtures. They are not the product's required weekly input path.
- **Acceptance:** for a representative week, the system produces a draft total
  roster in the NGO division-sheet format, with zero hard-rule violations and a
  review queue for unresolved choices.
- **Demo story:** "Given next week's known HC, escort, leave, and cancellation
  facts, the system drafts the total division sheet. The supervisor reviews the
  few risky cards, then exports the staff-facing workbook."

### Phase 1A — Master Data & Validator Hardening

- **Status:** implemented in v0.5.0; next work is NGO-maintained data entry
  and parallel-run validation.
- **Scope:** replace the demo seed assumptions (grant-all skills, missing
  genders, on-the-fly elders) with a persisted, versioned, validated master
  data set consumed by the weekly demo builder; extend hard-rule validator
  coverage accordingly.
- **Spec:** `MASTER_DATA_AND_VALIDATOR_SPEC.md` (entities, gap policy,
  source-of-truth matrix, required test cases, acceptance criteria).
- **Non-goals:** unchanged from Phase 1 — no CP-SAT, no LLM in the decision
  path, no new weekly upload requirements, no review UI.

### Phase 1B — Provenance And Review-Publication Closure

- **Status:** engineering packages A-E implemented; real NGO evidence remains pending.
- **Dependency order:** provenance and demand conservation -> durable weekly
  runs/decisions/overrides -> approve/edit/reject and revalidation -> separate
  ready-only final publication -> reconciliation metrics and a two-week
  parallel-run harness.
- **Specs:** `PROVENANCE_AND_PUBLICATION_SPEC.md` and
  `PHASE_1B_ACCEPTANCE_MATRIX.md`.
- **Acceptance:** every dated weekly demand has one explicit disposition; every
  uncertain or seeded placement links source evidence and an audit to its exact
  cell; API/UI/RC counts reconcile; only `publication_state=ready` can produce
  a staff-facing final workbook.
- **NGO gate:** confirmed master data and two roster-owner-signed parallel weeks
  remain required. Engineering fixture runs do not satisfy this gate.

## Phase 2 — Operational Review And Parallel Run

- **Scope:** validate the implemented rule-based workflow with the real roster
  owner while the manual workbook remains operational source of truth.
- **Operational tasks:**
  - confirm worker/elder skills, genders, routes, availability, rule config,
    and master-data ownership;
  - select two representative weeks, including controlled changes;
  - run the generated draft and manual roster in parallel, classify every diff,
    close blockers, and obtain roster-owner sign-off;
  - measure unchanged approvals, external Excel edits, review time, and weekly
    drafting time; use evidence to decide whether bulk approval or a metrics
    dashboard is actually needed.
- **Acceptance:** two signed weeks, zero uncategorized/blocking differences,
  and documented NGO-confirmed master data. Fixture-smoke success is not this
  acceptance.

## Phase 3 — Optimization Upgrade

- **Scope:** add CP-SAT or another optimizer only after the rule-based scheduler
  is correct and trusted.
- **Non-goals:** replacing human approval, using LLMs in scheduling decisions.
- **Acceptance:** optimizer improves travel/fairness/unassigned metrics without
  increasing hard-rule violations or unacceptable churn.

## Phase 4 — Live Deployment

- **Scope:** NGO-owned deployment, backups, role access, optional Drive upload,
  training, and runbook.
- **Acceptance:** several consecutive weeks fully drafted through the system,
  with measurable admin-time reduction and restorable backups.

## Explicit Non-Goals

- Making the NGO upload three different source workbooks every week as the
  primary product workflow.
- Re-extracting rules already captured by the strong-agent reverse-engineering
  documents.
- Treating unconfirmed semantics as hard rules.
- Adding CP-SAT before the deterministic scheduler is useful.
