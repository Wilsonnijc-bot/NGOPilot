# Rescheduling Algorithm — Dynamic Repair After Baseline

**Status:** target policy plus implementation reference. The current engine
implements deterministic leave/cancellation/escort repair and depth-1 escort
displacement. Depth-2 chains, open-ended hospitalisation lifecycle, dependency
transactions, and CP-SAT batch repair remain future work. The future optimizer
formulation is in `../future/optimization_model.md`.

## 0. Common pipeline

Every change follows the same five stages; scenarios below only specialise them.

```
EVENT → (1) AFFECTED-SET DETECTION → (2) CANDIDATE GENERATION → (3) RANKING
      → (4) PROPOSAL (AuditItems, never silent) → (5) HUMAN DECISION → new ScheduleVersion(kind=repair)
```

Invariants:
- **I1** The published baseline `V0` is immutable; repairs produce `V1` with `parent_version_id = V0`.
- **I2** Entries outside the affected set are pinned (`RB-CHG-02`), unless a displacement chain (depth ≤ 2) is explicitly proposed and approved.
- **I3** Every automatic action has an `explanation` and an `AuditItem`; severity per `human_review_policy.md`.
- **I4** Hard rules (skill/gender/exclusivity/availability/double-booking) are never relaxed by the repair engine.
- **I5** Events are processed as a batch per invocation (§9); the queue is ordered before solving, not FIFO-patched.

Shared helpers (pseudocode):

```python
def candidates(task, V, *, allow_displacement=False):
    pool = [w for w in workers
            if elig(w, task)                        # skill+route+gender+exclusive+overrides
            and avail(w, task.date, task.period)
            and free(w, task.sessions, V)]
    ranked = rank(pool, task, V)
    if ranked or not allow_displacement:
        return ranked
    # displacement: workers whose current task is strictly lower priority AND itself re-coverable
    disp = []
    for w in eligible_busy_workers(task, V):
        t2 = current_task(w, task.slot, V)
        if priority(t2) < priority(task):
            c2 = candidates(t2, V, allow_displacement=False)   # depth-2 cap
            if c2 or is_absorbable(t2):                        # absorbable: duty/misc that can go one head short of required+buffer
                disp.append((w, t2, c2[:3]))
    return ranked, disp

def rank(pool, task, V):  # deterministic, explainable ordering
    return sorted(pool, key=lambda w: (
        travel_delta(w, task, V),          # 1. added travel minutes for w's day
        -has_preference(task, w),          # 2. escort/elder preference (prefer)
        workload_delta(w, V),              # 3. keep weekly load balanced
        -affinity(w, task),                # 4. home-centre / familiar-route bonus
        duty_fairness_delta(w, V),         # 5. rolling duty-count fairness
        w.id,                              # 6. stable tie-break
    ))
```

`free(w, slot, V)` treats `needs_review` proposals as occupied (no
double-proposing). Scenario outputs use the current Pydantic `AuditItem`; the
v0.1 `audit_item_schema.json` remains a design reference and may omit Phase 1B
additive provenance fields.

---

## 1. Employee full-day leave

- **Event:** `LeaveEvent{worker_id, date, scope: full_day, reported_at}`
- **Affected:** all V0 entries of worker on date (both periods, both sessions), incl. duty and ESC slots.
- **Handling per entry, in priority order (duty first — they are the scarcest):**
  - `exclusive` fixed service → **cancel** (RB-EXCL-02): AuditItem `exclusive_cancellation`, severity high, requires approval before elder is notified. Do **not** search substitutes.
  - escort entry → treat as escort needing reassignment (see §7 logic): candidates among escort-qualified; preference notes respected.
  - duty entry → refill from free workers; if none, propose pulling from lowest-priority displaceable task; if still none → `duty_under_coverage` (high).
  - other fixed/misc → `candidates(task, V1, allow_displacement=True)`; top-1 becomes `replacement_suggestion` (warning) with top-3 alternatives; none → `unassigned_task` (high).
- **Review trigger:** every cancellation and unassigned; replacements auto-approvable in bulk.
- **Failure mode:** N unassigned tasks remain → escalate to degraded-mode question RB-U-03; system proposes the drop-list ordered by lowest π.

```python
def on_full_day_leave(ev, V0):
    V1 = V0.branch(trigger=ev)
    affected = sorted(V1.entries(worker=ev.worker_id, date=ev.date),
                      key=lambda e: -priority(e))
    for e in affected:
        e.status = "affected"
        if e.is_exclusive_fixed():        propose_cancel(e, reason="exclusive worker on leave")
        elif e.service == ESC:            propose_escort_reassign(e, V1)
        else:                             propose_replacement_or_unassigned(e, V1)
    return V1
```

## 2. Employee half-day leave

Same as §1 with `scope ∈ {AM, PM}`; affected set filtered to that period. Extra check: if the worker's remaining half-day contains a task whose time window spills across the boundary (e.g. escort with early pickup for a 14:00 appointment when AM leave ends 13:00) → flag `time_window_conflict` (warning) instead of assuming feasibility.

## 3. Elder cancels service (single occurrence)

- **Event:** `ServiceCancellationEvent{elder_id, date_from=date_to=d, service_scope, reason: personal/other}`
- **Affected:** V0 entries for that elder on d within scope.
- **Handling:** entry → `cancelled` (needs approval only if exclusive — cancelling an exclusive service is sensitive because resuming it must go back to the bound worker; otherwise auto with info item). Freed worker-slot enters **refill cascade** (RB-DUTY-04): duty gaps → pending escorts → unassigned fixed → nothing (leave free, info item "released, no gap to fill" — the NGO may prefer idle over make-work `[assumption to confirm]`).
- **Review:** refill suggestions = info/warning; no candidate needed (releasing is safe).
- **Failure mode:** none hard; worst case idle worker.

```python
def on_cancellation(ev, V0):
    V1 = V0.branch(trigger=ev)
    for e in V1.entries(elder=ev.elder_id, dates=ev.range, scope=ev.service_scope):
        e.status = "cancelled"; audit(e, kind="service_cancellation",
                                      severity="high" if e.exclusive else "info")
        slot = e.freed_slot()
        gap = first_gap_by_priority(V1, slot)      # duty shortfall → escort u[t] → unassigned fixed
        if gap: propose_assign(e.worker, gap, explanation=f"freed by {ev.id}, fills {gap.kind}")
    return V1
```

## 4. Elder is hospitalized

- **Event:** `ServiceCancellationEvent{elder_id, date_from=d, date_to=null, service_scope=all, reason=hospitalised}`
- **Difference from §3:** open-ended (RB-CANC-02). Suppresses occurrences in the current week **and** marks the FixedService rows `suspended` so subsequent weekly solves skip them until the event is closed.
- **Extra outputs:** a standing review item listing all suspended recurring services + their bound workers; on `event closed` (elder discharged) the system proposes resuming with the **original** workers (exclusivity survives suspension).
- **Escorts of that elder** in-window → cancelled automatically (they can't attend), one info item each; freed escort capacity re-enters the pool (may resolve an over-quota day — recompute §6 for those days).

## 5. Escort demand decreases below baseline

- **Event:** `EscortQuotaOverride{date, period, required_count}` or cancellation of individual `EscortRequest`s.
- **Affected:** ESC entries beyond the new demand on (date, period). Which workers to release when 4 reserved → 2 needed: release order = **lowest displacement pain**: (1) workers whose release fills a duty gap that day, (2) workers with `prefer` notes on remaining escorts stay, (3) fairness (release the one with most escorts this week), (4) stable id.
- **Handling:** released ESC entries → `affected`; refill cascade as §3. All refills are `needs_review` (the NGO expects to see them: transcript "另外兩個同事要安排…工作 — 話俾我聽").
- **Failure mode:** none; idle fallback.

## 6. Escort demand increases above baseline

- **Event:** new `EscortRequest` rows past the reserved capacity (5th escort on a 4-slot day).
- **Candidate generation (ordered):**
  1. Free escort-qualified, gender-ok workers that slot (rare — baseline reserves are usually the free ones).
  2. Workers on **displaceable** tasks (priority(task) < priority(escort), i.e. fixed home services & misc, never duty below floor), where the displaced task itself has a replacement or is absorbable — the "chain" the NGO explicitly asked to see ("俾一個反饋…話俾我哋知佢係點安排").
  3. Depth-2 chains (A takes escort, B takes A's HC visit, B's meal route absorbed) — proposed only if depth-1 fails.
- **Ranking of chains:** total π-weighted disturbance, then travel delta, then count of touched entries.
- **Output:** AuditItem `escort_over_quota` (high) with the full chain rendered as: `嘉偉→ESC(L璋,PY 09:45); 嘉偉's E+RO:C蓮 → 秀英; 秀英's D(柴灣2) → absorbed by 志豪(route-qualified)`. Approving applies the whole chain atomically; rejecting offers next chain.
- **Failure mode:** no feasible chain → `unassigned_task` (high) + suggestion to negotiate the appointment (different period/day if 科目 allows — surfaced as text only, never auto).

```python
def on_extra_escort(req, V0):
    V1 = V0.branch(trigger=req)
    task = escort_task(req)
    free, chains = candidates(task, V1, allow_displacement=True)
    if free:   propose_assign(free[0], task, alternatives=free[1:3])
    elif chains: propose_chain(min(chains, key=chain_cost), alternatives=next_chains(2))
    else:      audit_unassigned(task, severity="high",
                                diagnosis=explain_no_candidates(task, V1))
    return V1
```

## 7. Exclusive worker is unavailable

Covered by §1/§2 branch, isolated here because the *product behaviour* differs:

- **Never generate candidates** for the exclusive task (RB-EXCL-01/02). The only options surfaced: (a) cancel occurrence [default], (b) human overrides exclusivity for this occurrence (creates `ManualOverride` + normal candidate list, flagged `exclusivity_overridden` — allowed because the human owns the elder relationship), (c) human reschedules occurrence within week to a slot where the bound worker is available (system checks feasibility and shows options — this is often what actually happens with HC "更改後日期").
- Option (c) generator: all (d', p') in week where bound worker free ∧ elder has no conflicting entry → ranked by travel fit; shown as alternatives on the cancellation item.
- **Downstream:** the freed elder-slot may release other things (rare); no cascade by default.

## 8. Center duty gap appears

- **Event:** any of the above leaves a duty task uncovered, or NGO edits requirement upward.
- **Detection:** recompute `coverage(c,d,p,role) = assigned − required` after every repair batch; negative ⇒ gap.
- **Candidates:** (1) free duty-qualified workers (affinity-ranked), (2) workers on misc/lowest-π tasks, (3) **cross-centre pull**: worker at over-covered centre (coverage>0) moves — allowed only same-day, flagged, (4) nothing → `duty_under_coverage` (high; per RB-DUTY-01 this is the top of the queue and blocks publication until acknowledged).
- **Fairness note:** gap-filling counts toward `dutycount_hist`, so chronic gap-fillers get relief in next baseline.

## 9. Multiple simultaneous change events

- **Input:** batch `{events[]}` (e.g. Monday morning: 2 leaves + 1 hospitalisation + 1 extra escort).
- **Algorithm:**
  1. Order events: cancellations/hospitalisations first (they **free** capacity), then quota decreases (free), then leaves (consume), then escort increases (consume). Freed-before-consumed maximises repair room and is deterministic.
  2. Apply stages within one working copy `V1`; later events see earlier proposals as tentative occupancy.
  3. **Interaction check:** if any consumed slot uses capacity freed by an unapproved cancellation, mark the consuming AuditItem `depends_on=[freeing item]` — approving is transactional per dependency chain (UI approves them together; rejecting the parent re-opens the child).
  4. If the batch touches > `K` entries (default 15) or produces ≥1 P0 violation, recommend full REPAIR solve (CP-SAT with min-change objective) instead of greedy patching; both paths emit identical AuditItem shapes, so the reviewer UX is unchanged.
- **Failure mode:** conflicting events on the same entity (leave + cancellation of the same visit) → dedupe by precedence (cancellation wins; leave item annotated "already cancelled").

## 10. Required human review (summary; details in `human_review_policy.md`)

| Scenario output | Review? | Severity |
|---|---|---|
| Exclusive cancellation (§1,2,7) | **Always, blocking** | high |
| Any `unassigned_task` | **Always, blocking** | high |
| Duty under-coverage (§8) | **Always, blocking** | high |
| Displacement chain (§6) | Always | high |
| Replacement suggestion (§1–2) | Yes, bulk-approvable | warning |
| Refill into duty/idle release (§3–5) | Yes, bulk-approvable | info/warning |
| Auto-cancel escorts of hospitalised elder (§4) | Notify-only | info |
| Gender/skill `unknown` blocked a better candidate | Yes — data-gap item | warning |

## 11. Phase mapping

- **Current rule-based engine:** deterministic baseline and local repair. The
  implemented ranking tuple in `engine/ranking.py` is the runtime behaviour;
  this document remains the target for incomplete scenarios.
- **Phase 1B:** implemented decision/provenance persistence, edit revalidation,
  ready-only publication, and deterministic parallel-run comparison.
- **Future CP-SAT:** keep greedy repair for small events and consider solver
  repair only after NGO parallel-run evidence. Both paths must share the same
  hard-rule validator.
