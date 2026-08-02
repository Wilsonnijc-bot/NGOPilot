# Human Review & Audit Policy

**Status:** current policy contract; approve/edit/reject persistence,
revalidation, and ready-only final publication are implemented. The system
proposes; the roster owner disposes. Machine-readable reference schema:
`audit_item_schema.json`.

Design stance (from the transcript): the NGO's supervisor already reviews a colleague's draft today ("同事初稿，跟住我就再做，跟住就發出去"). The system replaces the *draft*, not the *review*. Nothing reaches elders or workers without a human having seen — or deliberately bulk-approved — it.

---

## 1. When human review is required

**Blocking** (publication of the affected day/week is blocked until decided):

| Trigger | Item kind | Why |
|---|---|---|
| Exclusive service cancellation (RB-EXCL-02) | `exclusive_cancellation` | Elder-facing commitment; NGO must control communication |
| Any unassigned task (`u[t]=1`) | `unassigned_task` | Service would silently not happen |
| Centre duty under-coverage (RB-DUTY-01) | `duty_under_coverage` | Highest-priority rule in the NGO's own cascade |
| Displacement chain (escort over quota etc.) | `displacement_chain` | Multi-entry atomic change; downstream impact |
| Future solver relaxation used (`../future/optimization_model.md` §7) | `constraint_relaxed` | A hard rule was softened to find any solution |
| Rule conflict detected (two rules demand contradictory placements) | `rule_conflict` | Cannot be resolved by policy |

**Non-blocking, must-review** (a labelled review draft may be downloaded, but
final publication remains `draft` until every pending item is decided):

| Trigger | Item kind |
|---|---|
| Replacement suggestion after leave | `replacement_suggestion` |
| Escort quota change handling (up or down) | `escort_adjustment` |
| Gender constraint uncertainty (`gender_ok_unverified` — worker or elder gender unknown) | `data_gap_gender` |
| Skill uncertainty (candidate excluded/included on `unknown` skill) | `data_gap_skill` |
| Low-confidence source evidence (unparsed fixture cell, un-mangled week pattern, ambiguous name match) | `source_ambiguity` / support `import_ambiguity` |
| Template deviation (5.6 stability penalty paid) | `template_deviation` |

**Notify-only** (info feed, auto-approved):
refill of freed worker into duty (`refill`), auto-cancelled escorts of a hospitalised elder, idle release with no gap to fill.

## 2. Severity levels

| Level | Meaning | UI behaviour |
|---|---|---|
| `high` | Service delivery or safety at stake; blocking set above | Red; top of queue; blocks publish of affected scope |
| `warning` | Judgment call; system has a default it believes in | Amber; bulk-approve allowed per kind; keeps final state non-ready while pending |
| `info` | FYI or policy-resolvable item | Gray; collapsible; any automatic resolution is persisted before `ready` |

Escalation: any `warning` item older than the publication deadline (Friday cut-off) without decision escalates to `high` — silence must not publish surprises. Regardless of severity, current Phase 1B publication policy requires zero pending audits for `ready`.

## 3. Approve / edit / hard-bypass flow

```
pending ──approve──▶ approved: suggested_entry status needs_review→scheduled
   │
   ├────edit──────▶ edited:   reviewer modifies entry (worker/time/…);
   │                          hard-constraint validator re-checks; violation ⇒ warn + require override note;
   │                          saved as ManualOverride(scope=entry, origin_audit_item_id=this)
   │
   └────reject────▶ rejected: supervisor hard-bypass (強制略過). The current
                              arrangement is kept as scheduled — or the demand
                              is cancelled for the week when nothing is
                              assigned — and the entry is tagged with the
                              supervisor_hard_bypass constraint flag. The
                              waived blocker no longer re-blocks export;
                              validator, reconciliation, and export preflight
                              treat the entry as supervisor-accepted risk.
```

Rules:
- Decisions are per-item; `displacement_chain` and `depends_on` groups decide
  atomically (approve-all or bypass-all).
- A hard-bypass decision may cover several *independent* audit groups at once
  (the UI's per-category "一鍵強制忽略"); each dependency group inside the
  selection must still be complete, and the decision persists every affected
  item identity in `audit_ids` plus a `hard_bypass` marker.
- Every decision captures `decided_by`, `decided_at`, optional `note`;
  hard-bypasses **require** a note (that note is training data for better
  ranking later).
- A reviewer edit that violates a hard rule is persisted only with
  `override_note`; independent validation remains visible and the resulting
  version stays `blocked`.
- Decisions target one exact durable version and content hash. The store
  advances the current-version pointer with a database-level compare-and-swap,
  so of two racing decisions exactly one commits; the loser receives a
  structured 409 (`STALE_SCHEDULE_VERSION`) and no partial version, decision,
  or override survives. Retrying the same logical decision reuses its
  idempotency key and replays the committed result.

## 4. How manual overrides affect future schedules

1. **Entry-scope** override → applies to that occurrence only; next weekly solve ignores it.
2. **Week-scope** → pin/forbid for the remainder of the week's versions.
3. **Recurring** → written back as `ManualOverride(scope=recurring)`; the weekly task generator applies it like template data (e.g. "從今以後 L明 只由美紅跟" becomes a `must` binding). Recurring overrides appear in a monthly digest so the template owner can fold them into the real template (or the system proposes updating `FixedService.assigned_worker_id` after 4 consecutive identical overrides — suggestion only).
4. Overrides are effective-dated and never deleted — superseded ones get `effective_to`.

## 5. Explaining recommendations

Every suggested entry carries `explanation` composed from templated fragments (no free-form generation in the decision path):

- eligibility summary: "美紅: HC-qualified ✓, 女 ✓ (elder requires F), available Tue AM ✓"
- ranking justification: "chosen over 翠君: same-day district match (柴灣, +0 min travel vs +35 min)"
- cascade provenance: "freed because Y珍 hospitalised (event #E-2031); fills GC duty gap (required 2, had 1)"
- data caveats: "note: 美紅's ESC skill is unverified — see data gap item #A-114"

The audit item stores `evidence_refs[]` (rule ids, event ids, source cells) so any explanation can be traced to `rulebook.md` and the original Excel cell.

## 6. Traceability chain

```
Source evidence (rule id, config row, event id, optional Excel source_ref)
      → FixedService/EscortRequest/task
      → ScheduleEntry(origin_*) → AuditItem(evidence_refs) → Decision(by/at/note)
      → ManualOverride(origin_audit_item_id) → next ScheduleVersion(parent_version_id, trigger_event_ids)
```

Retention: versions and audit items are append-only; exports embed `version_id` in the workbook (hidden metadata sheet) so a printed roster can always be traced back.

## 7. Review workload budget

Working hypothesis for parallel-run evaluation: a normal week should have at
most 10 blocking items and 30 bulk-approvable warnings; a heavy-disruption day
should have at most 8 blocking items. These thresholds are not NGO-approved
service levels. Track them through
`../evaluation/evaluation_metrics.md`; if the system floods the reviewer, it
has failed at saving admin time.
