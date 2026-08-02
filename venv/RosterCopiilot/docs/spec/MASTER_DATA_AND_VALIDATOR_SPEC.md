# Phase 1A — Master Data & Validator Specification

**Status:** v1.0 · **Audience:** implementing (coding) agent.
**Position in roadmap:** between Phase 1 (rule-based scheduler bridge, shipped in
v0.4.0) and Phase 2 (operational review). Implements the "replace demo seed
assumptions with maintained data" step named in `PRODUCT_SPEC.md` §7.

**Source-of-truth precedence** (per `ENGINEERING_SPEC.md` §1): `rulebook.md`
wins for business meaning. `canonical_schema.md`/`schema.json` remain the v0.1
conceptual reference, while this active phase contract controls the explicitly
narrowed or additive Phase 1A runtime fields. It does not re-extract rules.
Rule IDs (`RB-*`) refer to `rulebook.md`; clarification IDs
(`Q-*`, `RB-U-*`) refer to open questions tracked there and in
`../ngo/clarification_packet.md`.

---

## 0. Problem and scope

The v0.4.0 demo drafts a weekly roster from: built-in division workbook
(fixed base + export template) + uploaded HC timetable + uploaded escort
workbook + temporary changes. It works, but three inputs are **demo seeds**,
not data:

1. every worker is granted the full skill list (`DEMO_SKILLS` in
   `backend/app/services/weekly_demo.py`) — RB-SKILL-01 is effectively off;
2. workers and elders have no gender — RB-GEND-01/02 can never activate;
3. elders are promoted on the fly from aliases with no persisted registry,
   so exclusivity, status (hospitalised), and district facts cannot accumulate.

Phase 1A introduces a **persisted, versioned, validated master data set** that
the weekly demo builder consults before falling back to template bootstrap.
The user-facing demo flow does not change: the user still uploads two
workbooks, enters changes, and downloads the division-format draft. Master
data is maintained through a small support API, not through weekly uploads.

Out of scope: review UI, CP-SAT, travel-time matrix, LLM anything (see §7).

---

## 1. Master data entities

Notation for the **Req** column:

- **✔** — schema-required; the record is invalid without it.
- **▲** — rule-activating; may be absent, but absence is a *data gap* that
  deactivates or degrades the named rule (fail-safe, never guessed).
- **○** — optional.

ID conventions follow `canonical_schema.md`: `W###` workers, `E####` elders,
`FS####` fixed services, `ER####` escort demands, `MO####` overrides.

Lifecycle classes:

- **Registry** (persisted, NGO-maintained): Worker, Elder, FixedService,
  RuleConfig, ManualOverride.
- **Weekly input** (transient per run, validated by the same module):
  EscortDemand, TemporaryChange, LeaveEvent.
- **Derived** (never hand-maintained): Availability.

### 1.1 Worker

Maps to `Employee` (`backend/app/domain/entities.py`); extra fields below are
new. Canonical provenance: `canonical_schema.md` §1.

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | `W###` | ✔ | unique, stable |
| `display_name` | str | ✔ | roster-header nickname, e.g. `輝` |
| `aliases` | str[] | ○ | extra nicknames used in HC/escort sheets (`寶芝`); drives upload alias resolution |
| `gender` | `M/F/null` | ▲ RB-GEND-01/02 | null ⇒ worker ineligible for gender-constrained pairings + `data_gap_gender` |
| `home_team` | str (`EH/IH/AMC/MRC/GC/…`) | ✔ default `EH` | affinity ranking RB-DUTY-03 |
| `skill_facts` | WorkerSkillFact[] | ▲ RB-SKILL-01 | see below; empty ⇒ all skill-gated services rely on policy in §3 |
| `route_facts` | RouteFact[] | ▲ RB-SKILL-03 | meal routes (灣仔1…寶珍) |
| `saturday_team` | `A/B/null` | ▲ RB-TIME-03 | null ⇒ never scheduled Saturday + gap |
| `employment_type` | `full/part` | ✔ default `full` | |
| `active` | bool | ✔ default true | gray-column departed workers ⇒ false |
| `effective_from` / `effective_to` | date/null | ○ | RB-FIX-04; `active` is the Phase 1A shortcut, effective dates win when present |
| `work_start` / `work_end` | time | ✔ defaults 8:30/17:30 | per-worker (R108); start < end |
| `notes` | str | ○ | keep raw annotations (`(7小時)`) |

**WorkerSkillFact** `{service_code, level: qualified/training/unknown,
source: matrix/ngo_confirmed/seed/manual, evidence?: str}`.
Lowering rule: `Employee.skills` = codes with `level=qualified`. A fact with
`source=seed` still lowers to qualified (the demo must keep working) but emits
**one per-worker** `data_gap_skill` warning ("技能未經 NGO 確認") — per-worker,
not per-assignment, to respect the review-workload budget
(`human_review_policy.md` §7). Absence of a fact = `unknown`, treated per §3
(never as "not qualified": `data_dictionary.md` §9, absence of tick is not
evidence of inability).

**RouteFact** `{route_code, qualified: bool, source, evidence?}` — same source
semantics.

### 1.2 Elder

Maps to `Elder`. Canonical provenance: `canonical_schema.md` §2.

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | `E####` | ✔ | |
| `display_name` | str | ✔ | masked alias (`Y珍`); never a real name (RB-PRIV-01) |
| `aliases` | str[] | ○ | alternate maskings seen in uploads |
| `gender` | `M/F/null` | ▲ RB-GEND-01 | null ⇒ gender-sensitive services for this elder are unverifiable ⇒ pairing ineligible or needs_review per §3 |
| `gender_requirement` | `M/F/ANY` | ✔ default `ANY` | explicit stated requirement wins over gender-derived |
| `district` | str/null | ▲ RB-GEO-01 (soft) | null ⇒ excluded from district-match ranking + info gap; NOT blocking in Phase 1A (no travel matrix yet) |
| `owning_unit` | str | ✔ default `EH` | `EH/IH/ED/AMC/MRC/GC/HSS` |
| `exclusive_worker_id` | FK Worker/null | ○ | elder-level binding (RB-EXCL-01); service-level binding lives on FixedService |
| `status` | `active/hospitalised/paused/exited` | ✔ default `active` | non-active suppresses demand (RB-CANC-02), never deletes it |
| `notes` | str | ○ | mobility notes, raw remarks |

### 1.3 FixedService

Maps to `FixedService`. Source: built-in division workbook template, promoted
once and then owned as registry data (the template remains the export layout
authority; see §4).

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | `FS####` | ✔ | |
| `elder_id` | FK/null | ▲ | null only for route/logistics tasks; null on a home-visit service ⇒ **blocking gap** (cyan incomplete cells) |
| `service_code` | ServiceCode | ✔ | canonical vocabulary (`data_dictionary.md` §1) |
| `weekday` | 1–6 | ✔ | |
| `period` | `AM/PM` | ✔ | |
| `session_index` | 1/2 | ✔ default 1 | sessions-as-hard-slots is assumption Q-A2 |
| `start_time` / `end_time` | time/null | ○ | deviations from canonical session times |
| `week_pattern` | WeekPattern | ✔ default weekly | RB-FIX-02; unparseable raw ⇒ **blocking gap**, occurrence not generated |
| `assigned_worker_id` | FK/null | ▲ | template worker; null ⇒ task floats to the scheduler |
| `is_exclusive` | bool | ✔ default per ServiceType (`E+RO` ⇒ true) | RB-EXCL-01/03 |
| `alternate_group` | str/null | ○ | 單月/雙月 pairs (RB-FIX-03) |
| `district` / `route` / `center` | str/null | ○ | per category |
| `active` | bool | ✔ default true | false = parked (dirty bootstrap row or suspended service); parked rows generate a review line, never occurrences |
| `effective_from` / `effective_to` | date/null | ○ | RB-FIX-04; `TBC` transfers stay un-applied + review item |
| `source_ref` | str | ✔ | e.g. `恆常服務!H3` — traceability |
| `source_confidence` | `high/medium/low` | ✔ | `low` ⇒ review item on every generated occurrence |
| `notes` | str | ○ | raw inline notes (`只要娥姐`) |

### 1.4 EscortDemand (weekly input)

Maps to `EscortRequest`. Source: uploaded escort workbook rows falling in the
target week, plus `escort_new` temporary changes. Not persisted as registry
data in Phase 1A; validated with the same rules.

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | `ER####` / upload row ref | ✔ | |
| `service_date` | date | ✔ | missing/out-of-week ⇒ row skipped + warning (never guessed into the week) |
| `period` | `AM/PM` | ✔ | missing ⇒ **blocking gap** for that row (observed: escort row 52) |
| `elder_id` | FK | ✔ | resolved via alias; unresolvable ⇒ auto-register a provisional Elder (as today) + `source_ambiguity` item |
| `appointment_time` | time/null | ○ | tolerant parse; keep raw |
| `destination` | str | ✔ default `未提供目的地` | gazetteer is out of scope (RB-U / §6 gazetteer deferred) |
| `subject` / `transport` | str/null | ○ | |
| `gender_requirement` | `M/F/ANY` | ✔ default `ANY` | per-case (RB-GEND-02); derivation from elder gender only when service is body-contact per remarks — Phase 1A default ANY unless explicit |
| `preferred_worker_id` | FK/null | ○ | from remarks regex (`安排X`/`建議安排X`) |
| `preference_strength` | `must/prefer/null` | ○ | `只要/安排`→must (hard, RB-ESC-07), `建議/盡量`→prefer (soft) |
| `remarks_raw` | str | ✔ keep | free text is a constraint channel — never dropped |
| `occupies_full_period` | bool | ✔ true | assumption Q-B5 / RB-ESC-08 |

### 1.5 Availability / Leave

**Availability is derived, never hand-maintained** (canonical §10): base = per
worker working hours × Mon–Sat, minus Saturday off-rotation (RB-TIME-03),
minus leave, minus `forbid_assignment` overrides (RB-CAP-01). It materialises
as `WorkerAvailability` rows in the snapshot.

**LeaveEvent** (weekly input; today arrives as a `leave` TemporaryChange):

| Field | Type | Req |
|---|---|---|
| `worker_id` | FK | ✔ |
| `date` | date | ✔ |
| `scope` | `full_day/AM/PM` | ✔ default full_day |
| `reason` | str | ○ |

### 1.6 TemporaryChange (weekly input)

The validated shape of `changes_json`. Types are the implemented `ChangeType`
enum: `leave`, `elder_cancellation`, `escort_new`, `escort_cancelled`.

| Field | Req | Notes |
|---|---|---|
| `type` | ✔ | unknown type ⇒ blocking gap, change not applied (current behaviour, keep) |
| `change_date` (or `date`) | ✔ | missing ⇒ blocking gap, not applied |
| `period` | ○ | null = full day |
| `worker_id` / `worker_alias` | ✔ for `leave` | unresolvable alias ⇒ blocking gap, not applied |
| `elder_id` / `elder_alias` | ✔ for `elder_cancellation`, `escort_new` | escort_new with no elder ⇒ blocking gap |
| `escort_request_id` | ✔ for `escort_cancelled` | |
| escort payload fields | ○ | destination, appointment_time, preferred_worker, reason |

Every accepted change must appear in `change_summary` and produce an
`ImpactReport`; every rejected change must appear as a blocking `DataGap`.
(Both already hold in v0.4.0 — regression-protect them.)

### 1.7 RuleConfig

Extends `SchedulerConfig` (`backend/app/domain/snapshot.py`). One active
config document, versioned. Every value carries `confirmed: bool` +
`assumption: str` — unconfirmed values still run the scheduler but surface
one summary-level review line each.

| Field | Default | Confirmed today? | Ref |
|---|---|---|---|
| `sessions` | AM1 8:30–10:30, AM2 11:00–12:30, PM1 14:00–15:30, PM2 16:00–17:30 | no (Q-A2) | `excel_semantics.md` §1.1 |
| `service_priority_order` | duty → escort → fixed home services → meal → logistics | yes (RB-PRIO-01); intra-tier no | `PRIORITY_TIER` in enums.py |
| `escort_occupancy` | full half-day, ≤1 escort/worker/half-day, baseline from template ESC slots per (weekday, period) — **not a constant 4** | partially (fact-check E2) | RB-ESC-01/08 |
| `escort_baseline_by_slot` | counted map `{(weekday, period): n}` from template yellow ESC cells | counted, not declared | RB-ESC-01 |
| `duty_requirements` | counted map `{(centre, weekday, period): n}` from template duty cells | **no — counted assumption, blocking for RB-DUTY-01 accuracy** | canonical §9 |
| `duty_min_counts` | absent | no (degradation floor unknown, RB-U-03) | |
| `saturday_anchor` | ISO-week parity: odd ⇒ team A (as implemented in `engine/context.py`) | **no (Q-A5 / RB-U-09)** | RB-TIME-03 |
| `week_of_month_definition` | k-th occurrence of weekday in month (as implemented in `WeekPattern.matches`) | **no (Q-A4 / RB-U-06)** | RB-FIX-02 |
| `pickup_lead_minutes_default` | 45 | no (RB-ESC-06 proposal) | |
| `unknown_data_policy` | see §3 | design decision | RB-DATA-01 |

### 1.8 ManualOverride

Maps to canonical §17. Persisted registry data; must survive re-solves.

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | `MO####` | ✔ | |
| `scope` | `entry/week/recurring` | ✔ | Phase 1A generator honours `recurring` and `week`; `entry` applies within one run |
| `pin` | `{worker_id?, elder_id?, date?, weekday?, period?, service_code?}` | ✔ | at least one key |
| `action` | `pin_assignment/forbid_assignment/cancel` | ✔ | `forbid_assignment` implements 不可加Case (RB-CAP-01) |
| `reason` | str | ✔ | required — explainability |
| `effective_from` / `effective_to` | date/null | ○ | superseded overrides get `effective_to`, never deleted |
| `origin_audit_item_id` | FK/null | ○ | traceability chain |

Phase 1A minimum behaviour: `forbid_assignment` removes matching
(worker, weekday/date, period) slots from scheduler capacity;
`pin_assignment` behaves like a `must` binding; `cancel` suppresses matching
generated occurrences. Applied overrides are listed in the export
`RC_變更摘要` sheet.

---

## 2. Storage, bootstrap, and API surface

- **Storage:** one versioned JSON document (`MasterDataSet`) in the existing
  SQLite store (`backend/app/store/sqlite.py`), following the
  `DatasetSnapshot` pattern: `{version, created_at, payload_json}`. Append-only
  versions; latest active. No per-entity tables in Phase 1A.
- **Bootstrap:** when no master data exists, build it from the built-in
  division template exactly as the demo builder does today (workers from
  columns, hours from R108, Saturday teams from R93, fixed services from
  candidate cells), plus skill/route facts from the 新同工跟服務紀錄表 matrix
  fixture where available (`source=matrix`), plus `source=seed` skill facts
  replacing today's `DEMO_SKILLS` so the roster remains generatable. Bootstrap
  output is saved as version 1 and marked `origin=template_bootstrap`.
  Bootstrap must never fail on dirty template cells: rows that would be
  `error`-level under §3.1 (e.g. unparseable pattern like `長周`, missing
  elder on a home-visit cell) are parked as `active=false` +
  `source_confidence=low` with a warning issue, so a human resolves them via
  PUT instead of the load aborting.
- **API (support tooling, not the user wizard):**
  - `GET /api/master-data` — active document + version metadata.
  - `PUT /api/master-data` — replace document; runs §5 MD validation; rejects
    on any `error`-level issue (422 with issue list); saves a new version.
  - `GET /api/master-data/issues` — validation issues of the active version.
- **Demo integration:** `WeeklyRosterDemoBuilder` consults the active
  `MasterDataSet` for workers/elders/fixed services/config/overrides, and
  keeps uploads + temporary changes as the only per-run inputs. With an
  untouched bootstrap document, demo output must be equivalent to v0.4.0
  (same entry counts ± data-gap wording).
- The API must be labelled support/admin tooling; it must not appear in the
  main wizard path (frontend copy guard test already enforces vocabulary).

---

## 3. Missing-field policy: what blocks, what warns

Two distinct levels, per `human_review_policy.md` §1 — **a data gap is usually
a warning; its downstream consequence may block.**

### 3.1 Master-data validation issues (checked on PUT / bootstrap)

| Condition | Level |
|---|---|
| broken FK (fixed service → missing elder/worker; override → missing worker; exclusive binding → inactive worker) | **error** (rejects save) |
| duplicate worker/elder id, duplicate alias across two active workers | **error** |
| `work_start ≥ work_end`; weekday/period/session out of range | **error** |
| unparseable `week_pattern` raw on an active FixedService | **error** |
| home-visit FixedService with `elder_id=null` | **error** |
| worker `gender=null` | warning `data_gap_gender` |
| worker with zero non-seed skill facts | warning `data_gap_skill` |
| elder `gender=null` while any gender-sensitive service targets them | warning `data_gap_gender` |
| elder `district=null` | info |
| `saturday_team=null` on an active full-time worker | warning |
| RuleConfig value with `confirmed=false` | info (one line each) |

### 3.2 Solve-time gap behaviour (`UnknownDataPolicy`, RB-DATA-01)

| Unknown fact | Policy | Consequence |
|---|---|---|
| worker gender, task gender-constrained | `ineligible_and_data_gap` | pair skipped; if task ends **unassigned** ⇒ blocking `unassigned_task` |
| elder gender, service gender-sensitive, no explicit requirement | requirement = `UNKNOWN` ⇒ pairing unverifiable | entry only placeable as `needs_review` with `gender_ok_unverified` flag; validator treats a `scheduled` entry here as a violation |
| skill fact absent (`unknown`) for a skill-gated service | `ineligible_and_data_gap` | as above |
| skill fact `source=seed` | eligible + per-worker warning | roster generatable; NGO sees exactly which workers run on assumptions |
| meal route fact absent | `manual_review_required` | assignment allowed as `needs_review` (`route_unqualified` is P1, violable with approval — RB-SKILL-03) |
| week pattern unparseable | `manual_review_required` | occurrence **not generated** + blocking gap (a silent no-show is worse than a flagged one) |
| duty required_count unconfirmed | proceed with counted value | shortfalls still blocking (`duty_under_coverage`); config assumption line shown |
| `saturday_team` null | worker never scheduled Saturday | warning gap |
| TemporaryChange malformed | not applied | **blocking** gap (user asked for something the system refused) |

Never blocking in Phase 1A: elder district (no travel matrix), destination
gazetteer, pickup lead default, intra-tier priority order.

---

## 4. Source of truth matrix

One owner per fact; everything else is a view (cross-workbook observation §4
in `excel_semantics.md`).

| Fact | NGO-maintained master data | Built-in division template | Weekly uploads (HC / escort) | Human-confirmed |
|---|---|---|---|---|
| worker registry, aliases, hours, Saturday team | **owner** (bootstrapped from template) | bootstrap source | — | confirms bootstrap |
| worker gender | **owner** | absent everywhere | — | sole source |
| worker skills / meal routes | **owner** | — (matrix sheet covers 6 staff only) | — | confirms; seed facts until then |
| elder registry, gender, district, status, exclusivity | **owner** | bootstrap source (aliases, districts) | provisional elders auto-registered from rows | confirms provisional/ambiguous |
| FixedService rows (weekly template) | **owner** after promotion | **bootstrap source + export layout authority** | — | confirms `low`-confidence cells, `TBC` transfers |
| HC dated occurrences for target week | — | — | **HC upload owner** (target-week rows only) | reviews `更改` remarks |
| escort demand for target week | — | — | **escort upload owner** + `escort_new`/`escort_cancelled` changes | reviews preferences/ambiguities |
| leave | — | — | `leave` temporary changes | — |
| duty required counts | RuleConfig (counted) | counted from template | — | must confirm (blocking-accuracy assumption) |
| session times, priority order, escort baseline, Saturday anchor, week-of-month rule | RuleConfig **owner** | ESC-slot counts counted from template | — | confirms each assumption |
| ManualOverride | **owner** | inline notes (`不可加Case`) seed initial rows | — | every override is a human decision |
| real names | never stored here | leaks re-masked (RB-PRIV-01) | leaks re-masked | NGO-side `PersonAlias` only |

---

## 5. Hard rules vs soft rules (Phase 1A enforcement map)

Hard rules live in **two places, by design**: the eligibility gate
(`engine/eligibility.py`) and the independent validator
(`engine/validator.py`). A rule is "implemented" only when both know it.

### 5.1 Hard (validator must detect; accepted rosters must return zero)

| Rule | Ref | Validator code | Phase 1A status |
|---|---|---|---|
| no double-booking; full-period excludes sessions | RB-TIME-01 | `time_conflict` | implemented — keep |
| working hours / leave / Sunday / Saturday A-B | RB-TIME-02/03, RB-LEAVE-01 | `worker_on_leave`, `not_working_day` | implemented — keep |
| skill gate (MEAL exempt) | RB-SKILL-01/02 | `skill_mismatch` | implemented; **rewire from seed skills to skill_facts** |
| gender match / gender unverifiable | RB-GEND-01/02 | `gender_mismatch`, `gender_unknown` | implemented; activates once genders exist |
| exclusive binding; cancel-don't-substitute | RB-EXCL-01/02/04 | `exclusive_binding`, `exclusive_worker_absent` | implemented — keep |
| `must` preference on escort | RB-ESC-07, RB-EXCL-03 | `preference_unmet` treated as hard for must | **verify coverage; add validator check if missing** |
| capacity lock (不可加Case) | RB-CAP-01 | new: forbid-override violation | **new in Phase 1A** |
| escort fixed appointment, full half-day occupancy | RB-ESC-05/08 | via `time_conflict` full-period rule | implemented — keep |
| week pattern gates occurrence existence | RB-FIX-02/03 | generator-level (no occurrence ⇒ nothing to validate) | implemented — add tests |
| duty coverage ≥ required | RB-DUTY-01 | blocking `duty_under_coverage` audit (not a HardViolation on entries) | implemented — keep semantics |
| no silent task deletion | RB-DATA-01 | every suppressed/unplaced demand has an entry/audit/gap | implemented — regression-protect |

### 5.2 Soft (ranking terms only; never block)

| Rule | Ref | Phase 1A treatment |
|---|---|---|
| district match / travel | RB-GEO-01/02 | district string match in ranking only; travel matrix **deferred** |
| `prefer` escort preference | RB-ESC-07 | ranking bonus (implemented) |
| duty fairness / rotation | RB-DUTY-02 | ranking term; rolling history deferred |
| centre affinity | RB-DUTY-03 | `home_team` bonus (implemented) |
| workload balance | RB-LOAD-01 | ranking term (implemented) |
| minimum-change repair | RB-CHG-02 | repair pins unaffected entries (implemented) |

---

## 6. Validator test cases (the coding agent must implement)

Three suites. Names are suggestions; behaviour is the contract. All tests are
deterministic, no Excel reads inside engine tests (fixtures construct
snapshots/master data directly).

### 6.1 MD — master data validation (`tests/test_master_data_validation.py`)

| ID | Given | Expect |
|---|---|---|
| MD-01 | fixed service referencing missing elder id | error issue, PUT rejected (422 with issue list) |
| MD-02 | two active workers sharing alias `娥` | error |
| MD-03 | worker `work_start=18:00, work_end=9:00` | error |
| MD-04 | PUT with an **active** FixedService whose raw pattern is `長周` | error (unparseable), message keeps raw text; same row with `active=false` passes with warning |
| MD-05 | PUT with an active home-visit FixedService, `elder_id=null` | error (cyan-cell case); inactive variant passes with warning |
| MD-06 | worker `gender=null` | warning `data_gap_gender`, save succeeds |
| MD-07 | worker with only `source=seed` skill facts | warning `data_gap_skill`, save succeeds |
| MD-08 | elder `gender=null` + a BATH FixedService targeting them | warning naming both elder and service |
| MD-09 | override `forbid_assignment` with empty `pin` | error |
| MD-10 | exclusive FixedService whose `assigned_worker_id` is inactive | error |
| MD-11 | RuleConfig with `saturday_anchor.confirmed=false` | info issue listing the assumption |
| MD-12 | valid bootstrap from built-in template | zero errors; ≥46 workers; warnings include per-worker seed-skill gaps |

### 6.2 HR — hard-rule validator (`tests/test_validator_hard_rules.py`; extend existing)

Each case builds a minimal dataset + entries and asserts `validate_entries`
output. One positive (violation detected) and one negative (clean pass) per
rule; the table lists the positive.

| ID | Scenario | Expected violation |
|---|---|---|
| HR-01 | worker double-booked same (date, period, session) | `time_conflict` ×2 entries |
| HR-02 | escort (full-period) + session task same half-day | `time_conflict` |
| HR-03 | HC assigned to worker whose skill_facts lack HC (`unknown`) | `skill_mismatch` |
| HR-04 | MEAL assigned to worker with zero skill facts | **no** violation (RB-SKILL-02) |
| HR-05 | BATH for elder requiring F assigned to M worker | `gender_mismatch` |
| HR-06 | BATH for elder with `gender=null`, no explicit requirement, entry `scheduled` | `gender_unknown` |
| HR-07 | same as HR-06 but entry `needs_review` + `gender_ok_unverified` flag | no violation (flagged path is the allowed one) |
| HR-08 | exclusive E+RO occurrence assigned to a different worker | `exclusive_binding` |
| HR-09 | exclusive worker on leave; occurrence `scheduled` to substitute | `exclusive_binding`; correct output is `cancelled` + `exclusive_cancellation` audit |
| HR-10 | entry on worker's leave half-day | `worker_on_leave` |
| HR-11 | Saturday entry for worker on the off-rotation team; Sunday entry | `not_working_day` ×2 |
| HR-12 | escort with `preference_strength=must` assigned to another worker | violation (or blocking audit) — must never pass silently |
| HR-13 | entry in a slot covered by `forbid_assignment` override (嫦 Tue AM) | new violation code for RB-CAP-01 |
| HR-14 | duty slot filled below `required_count` | blocking `duty_under_coverage` audit on the version |

### 6.3 GEN/INT — generation & integration (`tests/test_master_data_integration.py`)

| ID | Scenario | Expect |
|---|---|---|
| GEN-01 | FixedService `weeks_of_month=[1,3]`, target week = 2nd occurrence week | no occurrence generated; nothing unassigned, no gap |
| GEN-02 | 單月/雙月 alternate pair, odd month | exactly the odd-month member generated |
| GEN-03 | worker `saturday_team=null` | no Saturday entries for them + warning gap |
| GEN-04 | `pin_assignment` recurring override | generated occurrence pinned to that worker |
| GEN-05 | `cancel` override on a template occurrence | occurrence suppressed, listed (not silently gone) |
| INT-01 | demo run (real sample uploads) with bootstrap master data, no genders | draft generated; zero hard violations; gender gaps present as warnings |
| INT-02 | same, after setting all worker+elder genders via PUT | zero hard violations; `gender_unknown` gaps disappear; any gender-driven placement change is visible in audit items |
| INT-03 | PUT master data marking one worker's HC skill `unknown` | that worker receives no HC entries; displaced HC tasks reassigned or unassigned+blocking |
| INT-04 | PUT with a broken FK | 422; active version unchanged; demo still runs on previous version |
| INT-05 | export after INT-01 | workbook opens; `RC_*` sheets present; applied overrides listed in `RC_變更摘要` |
| INT-06 | review-budget guard on the representative week | blocking items ≤ 10, warnings ≤ 30 (`human_review_policy.md` §7); fail the test if the gap policy floods the queue |

Existing suites (`test_validator*`, `test_scheduler*`, `test_weekly_demo.py`,
benchmark) must stay green throughout.

---

## 7. Explicit non-goals (Phase 1A)

1. **No CP-SAT / no optimizer.** The deterministic greedy + repair engine
   remains the only solver (roadmap Phase 3 gate).
2. **No LLM anywhere in the scheduling decision path** — not in eligibility,
   ranking, repair, validation, or explanations (templated fragments only,
   `human_review_policy.md` §5). LLM-assisted *support tooling* (e.g. remark
   parsing suggestions) is also out of scope for this phase.
3. **No re-extraction of rules.** `rulebook.md` and companions are the source
   of truth. If implementation uncovers a direct contradiction with the sample
   workbooks, record it in `../records/fact_check_report_2026-07-01.md` and raise it — do not
   silently re-derive.
4. **No new weekly upload requirements.** The user still uploads exactly the
   HC timetable and escort workbook. Master data maintenance is an admin/API
   concern, invisible in the wizard.
5. **No travel-time matrix, no destination gazetteer** — district string match
   stays the only geography signal.
6. **No review UI** (approve/edit/reject screens are Phase 2). Phase 1A only
   guarantees the data those screens will need (issues, gaps, overrides,
   versions) exists and is persisted.
7. **No guessing.** Any unknown stays `null` + gap. Adding a "probably fine"
   default for gender, skills, Saturday anchor, or week-of-month semantics is
   a spec violation, not a convenience.

---

## 8. Acceptance criteria (definition of done)

1. `MasterDataSet` persists in SQLite with versioning; `GET/PUT
   /api/master-data` + `GET /api/master-data/issues` behave per §2/§3.1.
2. Bootstrap from the built-in template reproduces today's demo behaviour
   (INT-01) with `DEMO_SKILLS` deleted from `weekly_demo.py`.
3. Editing master data visibly changes scheduling (INT-02/INT-03) — the
   proof that seeds became data.
4. All suites in §6 implemented and green; `.venv/bin/python -m pytest`
   fully green; benchmark still reports zero hard-constraint violations.
5. Every §3 gap surfaces in the demo response (`data_gaps` /
   `audit_items` / warnings) and in the export review sheets — nothing new is
   silent.
6. README + `使用說明.md` gain a short "master data (admin)" note; wizard copy
   unchanged (frontend copy guard tests stay green).
