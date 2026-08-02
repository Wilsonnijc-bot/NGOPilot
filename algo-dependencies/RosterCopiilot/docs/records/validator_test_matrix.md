# Validator & Scheduling Rule Test Matrix

**Record type:** living implementation and test-coverage matrix; update statuses
when tests land, but preserve the historical disposition section.<br>
**Status:** v1.2 reconciled against Phase 1B engineering · **Audience:** implementing agent.<br>
**Companions:** `../spec/MASTER_DATA_AND_VALIDATOR_SPEC.md` (entities, gap policy),
`../spec/rulebook.md` (rule authority),
`../spec/human_review_policy.md` (severity/blocking), and
`../spec/rescheduling_algorithm.md` (target repair behaviour).

This matrix is the authoritative checklist of behaviours the deterministic
scheduler must prove with tests. The original v1.0 review correctly identified
missing Phase 1A work, but its implementation-status prose became stale after
v0.5.0. Statuses and §5/§6 below were reconciled on 2026-07-17 against the
current working tree and the Phase 1B provenance/export tests. The governing
contract is `../spec/PROVENANCE_AND_PUBLICATION_SPEC.md`; real NGO confirmation
remains separate from automated coverage.

---

## 0. Conventions

**Dual enforcement.** Every hard rule is checked in two independent places:

1. the eligibility gate (`engine/eligibility.py::check_assignment`) — prevents
   bad placements at solve time;
2. the independent validator (`engine/validator.py::validate_entries`) —
   re-checks a finished roster with separate bookkeeping.

A hard rule counts as **covered** only when both paths are exercised, and the
validator test is **negative-path**: construct an invalid roster by hand and
assert the violation is reported. v0.5.0 added those constructed violations in
`test_validator_hard_rules.py`; remaining partial rows are identified below.

**Fixture style.** Engine tests construct `MockDataset`/entries directly (no
Excel, no API). Integration rows (`W-*`) may use the demo API with the real
sample workbooks. All tests deterministic; no time/randomness.

**Status legend** (current automated coverage):
✅ covered · ◐ positive-path or behaviour-only (negative validator test
missing) · ✗ missing entirely.

Severity/blocking vocabulary is `../spec/human_review_policy.md` §1–2. Audit kinds are
the implemented `AuditKind` enum; reason codes the implemented
`ReviewReasonCode` enum.

---

## 1. Hard-rule cases

| ID | Rule (ref) | Given | Gate must | Validator must | Audit item when unresolved | Status |
|---|---|---|---|---|---|---|
| H-01 | No double booking (RB-TIME-01) | two session tasks, same (worker, date, period, session) | reject 2nd placement (`time_conflict`) | report `TIME_CONFLICT` on constructed collision | `unassigned_task` · high · **blocking** if displaced task has no other candidate | ✅ scheduler plus `test_validator_reports_session_double_booking` |
| H-02 | Full-period occupancy (RB-ESC-05/08) | escort entry (session_index=None) + any session entry, same half-day | reject | report `TIME_CONFLICT` for every entry in slot | as H-01 | ✅ `test_validator_reports_full_period_overlap_for_every_entry` |
| H-03 | Leave blocks assignment (RB-LEAVE-01) | worker with AM leave; task that AM | reject (`worker_on_leave`) | constructed entry on leave slot → `WORKER_ON_LEAVE` | `replacement_suggestion` · warning; `unassigned_task` · high · blocking if none | ✅ repair behaviour plus constructed leave violation |
| H-04 | Gender-sensitive services (RB-GEND-01/02) | BATH/PC for elder requiring F; male worker | reject (`gender_mismatch`) | constructed mismatch → `GENDER_MISMATCH`; scheduled-but-unverifiable → `GENDER_UNKNOWN` | `data_gap_gender` (as `DATA_GAP`) · warning; consequence may be blocking `unassigned_task` | ✅ mismatch, unknown, and allowed review path tested |
| H-05 | Skill-gated services (RB-SKILL-01/02) | HC task; worker without qualified HC fact | reject (`skill_mismatch`); MEAL must **pass** with zero facts | constructed mismatch → `SKILL_MISMATCH`; MEAL never flagged | `data_gap_skill` (as `DATA_GAP`) · warning; `unassigned_task` if nobody qualifies | ✅ mismatch and MEAL exemption tested |
| H-06 | Exclusive worker binding (RB-EXCL-01/02/04) | exclusive E+RO; bound worker on leave | never substitute: propose **cancel** | constructed substitute entry → `EXCLUSIVE_BINDING` | `exclusive_cancellation` · high · **blocking** | ✅ repair/scheduler behaviour plus constructed substitution |
| H-07 | Escort `must` preference (RB-ESC-07/EXCL-03) | escort with `preference_strength=must`, preferred W-A; assign W-B | reject (`preference_unmet`) | active escort entry assigned elsewhere → `PREFERENCE_UNMET` | `unassigned_task` · high · blocking if the must-worker is unavailable (never silently reassigned) | ✅ gate and validator parity tested |
| H-08 | Saturday A/B availability (RB-TIME-03) | Saturday task; worker on off-rotation team; also `saturday_team=None`; also Sunday | reject (`not_working_day`) | constructed entries → `NOT_WORKING_DAY` | none-team worker: `data_gap_saturday_team` · warning; Saturday shortfall → normal unassigned/duty items | ◐ off-team/Sunday validator path ✅; null-team solve-time gap test missing |
| H-09 | Centre duty shortfall (RB-DUTY-01) | duty requirement 2; only 1 eligible worker that slot | fill what it can, never over-assign ineligible workers | shortfall is a version-level fact: `duty_under_coverage` audit present, count correct | `duty_under_coverage` · high · **blocking** | ✅ `test_duty_shortfall_becomes_blocking_audit_item` |
| H-10 | No silent deletion of tasks (RB-DATA-01) | every generated demand; suppress/cancel/displace some | — | conservation check: each demand ends as exactly one of {active entry, cancelled entry, unassigned entry, suppressed-with-audit}; totals reconcile | any unexplained disappearance = test failure, not an audit item | ✅ stable demand IDs, five-way conservation, and missing/duplicate/zero disposition failures covered in `test_provenance*.py` |
| H-11 | Capacity lock / forbid override (RB-CAP-01) | `ManualOverride(action=forbid_assignment, pin={worker, weekday, period})`; task in that slot | slot removed from capacity (reject) | constructed entry inside forbidden slot → `FORBIDDEN_ASSIGNMENT` | override honoured silently is the norm; a violating manual edit → `template_issue` · warning + override note | ✅ gate, validator, and master-data integration tested |
| H-12 | Week pattern gates existence (RB-FIX-02/03) | HC `weeks=[1,3]`; target week is 2nd occurrence; 單月/雙月 pair in odd month | generator emits no occurrence (not "unassigned") | nothing to validate — absence asserted at generator level | none (absence is correct); unparseable pattern → `DATA_GAP` · high · blocking (occurrence withheld) | ◐ generator-level week-pattern absence ✅; explicit alternate-pair test missing |

## 2. Soft-rule / ranking cases

Soft rules never produce violations and never block. Tests assert the
**deterministic rank order** (`engine/ranking.py::rank_key` — the tuple order
is the product behaviour) or a version-diff metric. Every deviation from a
soft preference must still carry an `explanation`.

| ID | Behaviour (ref) | Test recipe | Expected |
|---|---|---|---|
| S-01 | Minimize churn on repair (RB-CHG-02) | baseline; one leave event; diff repaired vs baseline | entries not sharing (worker/date/period) with the event are byte-identical; churn count == affected entries only; baseline object immutable (extends `test_repair.py::test_baseline_untouched_by_repair`) |
| S-02 | Prefer same worker where safe (RB-FIX-01) | fixed service with eligible `assigned_worker_id`; run baseline twice, second time with the pinned worker also eligible for a competing task | template worker keeps their own task in both runs; a repair that returns an elder's service after suspension proposes the **original** worker first |
| S-03 | Route/area fit (RB-GEO-01) | two eligible workers, one with `task.district` in `routes` | district-match worker ranks first; `ranking_explanation` mentions 熟悉路線; **note:** `worker.routes` currently mixes meal routes and districts — test must pin the intended semantics (district list) so the conflation is at least explicit |
| S-04 | Balance workload (RB-LOAD-01/DUTY-02) | two equally-eligible workers, one already loaded this week | lighter worker ranks first; for duty tasks, lower `duty_count` wins after affinity; assert full tuple order on a 3-worker case (district > preference > workload > affinity > fairness > id) |
| S-05 | `prefer` hints are soft (RB-ESC-07) | escort with `preference_strength=prefer` for W-A; W-A busy | task goes to next candidate **without** violation; audit `escort_adjustment`/`replacement_suggestion` · warning notes the unmet preference; the same fixture with `must` flips to H-07 behaviour |

## 3. Data-gap behaviour

Policy: unknown facts are never guessed (`RB-DATA-01`,
`UnknownDataPolicy`). Each row asserts: scheduler behaviour + the surfaced
`DataGap`/audit + where it lands in the export.

| ID | Missing fact | Scheduler behaviour | Expected audit/gap item | Export placement | Status |
|---|---|---|---|---|---|
| G-01 | worker gender, gender-constrained task | worker ineligible for that pairing only | `DATA_GAP` · `gender_unknown` · warning, entity=worker; consequence unassigned → `unassigned_task` · high · blocking | RC_審核 (gap) + RC_未分配 (consequence) | ✅ causal per-entity gap/evidence and terminal unassigned linkage covered |
| G-02 | elder gender **and** no explicit `gender_requirement`, gender-sensitive service | requirement resolves `UNKNOWN`; placement only as `needs_review` + `gender_ok_unverified`; a `scheduled` entry is a validator violation | `DATA_GAP` · `gender_unknown` · warning, entity=elder | RC_審核 | ✅ validator plus reciprocal demand/entry/audit/gap/evidence and exact-cell comment coverage |
| G-03 | skill fact absent/`unknown` for skill-gated service | ineligible (fail-safe); `source=seed` facts stay eligible but flagged | absent: `DATA_GAP` · `skill_mismatch`-reason · warning; seed: one per-worker `data_gap_skill` · warning | RC_審核 | ✅ used seed gaps dedupe across entries; absent candidate skill reaches the terminal blocker and export provenance |
| G-04 | route (meal) / district (elder) | route unknown: assignment allowed only as `needs_review` (`route_unqualified`, RB-SKILL-03 is P1); district missing: excluded from ranking bonus only | route: audit `replacement_suggestion`-style · warning; district: `data_gap_district` · info | RC_審核 (route) / issues API only (district) | ✅ unknown route is review-linked and preserved through repair; confirmed route/skill candidates rank ahead |
| G-05 | ambiguous alias (upload nickname matches 0 or ≥2 active workers/elders) | never auto-pick: demand imported **unpinned** (0 matches → provisional elder / unresolved worker); temporary change referencing it is **not applied** | `DATA_GAP` · blocking for unapplied changes; `source_ambiguity`-class audit · warning for unpinned demand | RC_審核 + change rejected in response `data_gaps` | ◐ unresolvable covered in weekly-demo tests; **≥2-match collision test ✗** (MD save-time duplicate-alias error now regression-tested) |
| G-06 | unconfirmed RuleConfig value (Saturday anchor, week-of-month, duty counts) | scheduler proceeds with the assumption | one `unconfirmed_rule_config` · info per value, listed in generation summary | RC_變更摘要 assumptions block | ◐ master-data issue coverage ✅; exact response/RC linkage incomplete |

## 4. Audit-item expectation table (consolidated)

For every unresolved case, exactly one item of the right kind — never a bare
log line, never silence.

| Situation | AuditKind | Severity | Blocking | ReviewReasonCode |
|---|---|---|---|---|
| task nobody can take | `unassigned_task` | high | yes | `no_qualified_worker` |
| exclusive worker absent | `exclusive_cancellation` | high | yes | `exclusive_worker_absent` |
| duty below required count | `duty_under_coverage` | high | yes | `duty_shortfall` |
| displacement chain proposed | `displacement_chain` | high | yes (atomic) | `displacement_required` |
| leave replacement proposed | `replacement_suggestion` | warning | no | `replacement_proposed` |
| escort quota shift handled | `escort_adjustment` | warning | no | `escort_over_baseline` |
| freed worker refilled | `refill` | info | no | `worker_released` |
| unmet `prefer` hint | `replacement_suggestion` | warning | no | `preference_unmet` |
| unknown gender (worker/elder) | `data_gap` | warning | no | `gender_unknown` |
| unknown/seed skill | `data_gap` | warning | no | `skill_mismatch` |
| unknown meal route | `replacement_suggestion` | warning | no | `route_unqualified` |
| unparseable week pattern | `data_gap` | high | yes | — (occurrence withheld) |
| malformed/unapplied temporary change | `data_gap` | high | yes | — |
| template worker fails hard gate | `template_issue` | warning | no | `template_worker_ineligible` |

## 5. Current routing after Phase 1B engineering

Completed after v0.5.0: H-10 five-way demand conservation; G-01/G-02/G-03/G-04
causal evidence/gap/audit/entry/cell linkage; fail-closed export reconciliation;
durable review decisions; and ready-only final publication.

The engineering P0 is no longer a missing provenance spine. The next gate is
operational: NGO-confirmed master data and two signed parallel-run weeks.
H-08 null-team solve-time coverage, H-12 alternate-pair coverage, the
soft-ranking cases, alias-collision upload coverage, and review-budget guards
remain valid bounded follow-ups; they must not be reported as NGO acceptance.

## 6. Historical v1.0 findings and v0.5.0 disposition

1. **Resolved:** weekly demo consumes the active `MasterDataSet`; changing
   master-data skills changes the draft.
2. **Resolved:** bootstrap uses the real division template, unknown genders,
   and explicitly labelled seed skills rather than mock genders.
3. **Resolved:** constructed invalid rosters prove the independent validator
   catches time, skill, gender, exclusivity, leave, weekend, must-preference,
   and capacity-lock violations.
4. **Resolved for provenance:** must preference and forbid overrides have
   gate/validator parity; unknown route use is now review-linked to affected
   entries/cells. NGO confirmation of route facts remains external.
5. **Availability CRUD drift (mild).** Spec treats availability as derived;
   the API persists raw `WorkerAvailability` rows. Acceptable as a manual
   blocked-slot channel if documented; otherwise remove the endpoints.
6. **Fixed (this review):** alias-collision validation flagged inactive
   workers as errors, contradicting spec §3.1 and its own message
   (`domain/master_data.py`; regression test added).
