# Evaluation Metrics

**Status:** living metric catalog, reconciled 2026-07-17. The current engine
computes a useful subset in `backend/app/engine/metrics.py`; the remaining rows
are explicitly marked as future. The frontend shows selected generation and
review counts, not a complete metrics dashboard.

All implemented metrics are deterministic functions of the schedule version,
dataset and optional parent version. Current runtime values are stored in
`ScheduleVersion.summary`.

## 1. Current Metrics

| Metric | Definition | Goal | Implementation |
| --- | --- | --- | --- |
| `hard_constraint_violations` | Independent validator violations | Always 0 | Implemented |
| `coverage_rate` | Assigned demand entries divided by current demand entries | Increase | Implemented; Phase 1B reconciliation provides the authoritative weekly-demand denominator |
| `unassigned_count` | Unassigned entries, with duty and escort sub-counts | 0 for duty and escort | Implemented |
| `escort_fulfillment_rate` | Assigned escort entries divided by escort demand entries | 1.0 | Implemented |
| `center_duty_slots_below_required` | Centre/day/period requirements below configured count | 0 | Implemented |
| `workload_balance_score` | `1 - population_stddev / mean` over active full-time worker session loads | Increase | Implemented; does not yet FTE-adjust part-time workers |
| `change_distance_from_original` | Added, removed or worker/status-changed entries against parent | Decrease | Implemented as an unweighted count |
| `manual_review_total` / `manual_review_blocking` | Pending review items | Decrease without hiding risk | Implemented |
| `cancelled_count` / `needs_review_entries` | Entry-state counts | Diagnostic | Implemented |
| `runtime_ms` | Engine runtime for the run | Diagnostic | Implemented |
| parallel-run cell/disposition diff counts, category totals, and unchanged-approval ratio | Generated/manual comparison quality | Zero uncategorized/blocking diffs | Implemented in `app/evaluation/parallel_run.py` |

## 2. Target Metrics Not Yet Implemented

| Metric | Intended definition | Dependency |
| --- | --- | --- |
| `total_travel_penalty` | Travel-matrix minutes between consecutive assignments, including revisit penalties | NGO-confirmed locations and versioned travel matrix |
| `preference_honoured_rate` | Eligible escort/elder preferences honoured | Complete preference semantics and stable denominator |
| `duty_fairness_spread` | Rolling maximum minus minimum duty counts | Persisted multi-week duty history |
| weighted change distance | Communication-cost-weighted roster changes | NGO-confirmed disruption weights |
| `exclusive_service_cancel_count` | Exclusive occurrences cancelled because the bound worker is unavailable | Dedicated metric; currently derivable from entries/audits only |
| reviewer decision time | Operational review efficiency | Real NGO parallel run and agreed start/end event semantics |

Future metrics are design targets, not claims about the current dashboard or
benchmark output.

## 3. Executable Benchmark Protocol

The current source of truth is:

```bash
.venv/bin/python backend/scripts/run_benchmark.py \
  --json /tmp/rostercopiilot_benchmark.json
```

The runner executes deterministic mock baseline/repair scenarios, real workbook
parser and no-edit round-trip checks, and a scheduler-snapshot scenario. It
fails on hard-rule violations or scenario-specific assertion failures. Runtime
output belongs in `/tmp`; do not commit changing `runtime_ms` values as product
changes.

`../future/target_benchmark_cases.json` is an aspirational CP-SAT/operational
test design. The current runner does not load it, and several cases require
features that do not yet exist.

## 4. Implemented Parallel-Run Report And Remaining Operational Metrics

`backend/scripts/run_parallel_review.py` now reports deterministic two-week
demand/disposition totals, exact placement-cell comparisons, diff categories,
blocking IDs, decision counts, unchanged-approval ratio, hard violations, and
export failures. It excludes runtime and separates engineering, comparison,
and NGO gates. See `PARALLEL_RUN_GUIDE.md`.

During real NGO parallel runs, additionally collect:

- reviewer decision time per item;
- percentage of suggestions approved unchanged (the harness computes this from
  persisted approve/reject/edit decisions);
- differences against the roster owner's manual workbook;
- same-week manual Excel edits outside the system;
- unresolved gender, skill, route and rule-config gaps;
- roster completion time against the Friday deadline.

Targets should be set with the NGO after observing two real weeks. The previous
draft's 80% unchanged-approval and fixed review-count thresholds remain
hypotheses, not accepted service levels.
