# Canonical Domain Model

**Status:** v0.1 reverse-engineering reference · Layout-independent conceptual
model. `schema.json` is its machine-readable design companion, not a schema
generated from the current Pydantic runtime. Phase 1A/1B additive fields are
defined by their active specs and code until this reference is deliberately
versioned forward.
Column key — **Src**: where the value comes from today · **Excel?**: can it be extracted from the current three workbooks (✔ / ◐ partial / ✘ no) · **Ask?**: NGO clarification required before trusting it.

Design principles:

1. **Effective-dating everywhere.** Staff depart mid-year, cases transfer with `生效日期`, times change "6/3 開始". Every relationship row carries `effective_from` / `effective_to` rather than being overwritten.
2. **Separate demand from assignment.** A `FixedService`/`EscortRequest` describes what an elder needs; a `ScheduleEntry` describes who does it on a date. The Excel files conflate these; the model must not.
3. **Half-day period + session slot.** The operational grid is (date × {AM, PM}); each half-day holds up to 2 sessions (observed canonical times 8:30–10:30 / 11:00–12:30 / 14:00–15:30 / 16:00–17:30). Conflicts are checked at session level when times are known, at period level otherwise.
4. **Nothing silently invented.** Fields whose values cannot come from Excel or the transcript default to `null` + `needs_clarification` flag, never to a guessed value.
5. **Pseudonymisation at the boundary.** Real names live only in an isolated lookup (`PersonAlias`) owned by the NGO deployment; all other tables carry opaque IDs + display aliases.

---

## 1. Employee

Care worker (前線照顧員). Case managers/clerical staff are `staff_role != care_worker` rows of the same table.

| Field | Type | Req | Src | Excel? | Ask? | Validation |
|---|---|---|---|---|---|---|
| `id` | string `W###` | ✔ | system | — | | unique |
| `display_alias` | string | ✔ | roster header nickname | ✔ | | unique among active |
| `tags` | string[] | | header `(HW)(CC)(AMC)…` | ✔ | ✔ meaning | vocabulary open |
| `gender` | enum `M/F` | ✔ for solver | **not in any file** | ✘ | **✔ blocking** | required before gender rules activate |
| `staff_role` | enum `care_worker/case_manager/clerical/driver` | ✔ | inferred from where name appears | ◐ | ✔ | |
| `home_team` | enum `EH/IH/AMC/MRC/GC/HSS/…` | | header tag / duty pattern | ◐ | ✔ | FK OrgUnit |
| `work_start` / `work_end` | time | ✔ | R108 hours row | ✔ | | start<end; per-worker |
| `works_saturday_team` | enum `A/B/none` | | R93 + Sat block | ◐ | ✔ semantics | |
| `daily_hours` | number | | title "每日8小時", `(7小時)` notes | ◐ | ✔ | |
| `employment_type` | enum `full/part/departed` | ✔ | header fill colour (gray=departed) | ◐ | ✔ | |
| `effective_from` / `effective_to` | date | | join dates in skill matrix; gray columns | ◐ | | |
| `notes` | string | | misc annotations | ✔ | | keep raw |

## 2. Elder

| Field | Type | Req | Src | Excel? | Ask? | Validation |
|---|---|---|---|---|---|---|
| `id` | string `E####` | ✔ | system | — | | unique |
| `display_alias` | string | ✔ | masked name (`Y珍`) | ✔ | | not guaranteed unique → resolution table |
| `real_name_ref` | FK PersonAlias | | NGO-side only | ◐ (some leak) | ✔ privacy protocol | never exported |
| `owning_unit` | enum `EH/IH/ED/AMC/MRC/GC/HSS…` | ✔ | `(unit)` suffix / 部門 / 單位 | ✔ | ✔ ED/HSS meaning | FK OrgUnit |
| `gender` | enum `M/F` | ✔ for gender rules | **not in files** | ✘ | **✔ blocking** | |
| `district` | string | ✔ for travel rules | detail cells `(柴灣)` | ◐ | ✔ confirm per elder | district vocabulary |
| `estate` | string | | detail cells (明華, 勵德…) | ◐ | | estate→district lookup |
| `service_requirements` | derived view | — | assignments | ✔ | | see FixedService |
| `mobility_notes` | string | | escort 備註 (輪椅…) | ◐ | | raw text |
| `status` | enum `active/hospitalised/paused/exited` | ✔ | not tracked in files | ✘ | ✔ | drives cancellation logic |
| `notes` | string | | | ✔ | | |

## 3. ServiceType

Reference table; seed rows in `data_dictionary.md` §1.

| Field | Type | Req | Notes |
|---|---|---|---|
| `code` | string (`EX_RO`, `HC`, `PC`, `BATH`, `ESC`, `MEAL`, `DUTY_AMC`…) | ✔ | canonical vocabulary |
| `label_zh` / `label_en` | string | ✔ | |
| `category` | enum `home_visit/escort/center_duty/logistics/admin/off` | ✔ | drives which constraints apply |
| `requires_skill` | bool | ✔ | Ask? per code — table in data dictionary has `[U]` cells |
| `gender_sensitive` | bool | ✔ | true for BATH/PC, per-case for ESC `[C]` |
| `exclusive_by_default` | bool | ✔ | true for EX_RO `[C]` |
| `default_priority` | int (1=highest) | ✔ | from transcript priority cascade; **Ask** exact ordering below duty/escort |
| `occupies` | enum `session/half_day/full_day` | ✔ | ESC=half_day `[I]`, home visits=session `[I]` — **Ask** |
| `cancellable_when_worker_absent` | bool | ✔ | EX_RO: cancel; others: replace `[C]` |

## 4. WorkerSkill

| Field | Type | Req | Src | Excel? | Ask? |
|---|---|---|---|---|---|
| `worker_id` | FK | ✔ | | | |
| `service_code` | FK ServiceType | ✔ | skill matrix rows E+RO/PC/B/HC/ESC/當值… | ◐ (only 6 new staff covered) | **✔ full 50-worker matrix needed** |
| `level` | enum `qualified/training/lead` | | `v` ticks; (主)/(協) | ◐ | ✔ |
| `evidence` | string | | e.g. `新同工跟服務紀錄表!C7` | ✔ | |
| `effective_from/to` | date | | join dates | ◐ | |

Absence of a tick is **not** evidence of inability — untracked pairs default to `unknown`, which the solver treats as ineligible until confirmed (safe default) and surfaces as clarification items.

## 5. WorkerRouteQualification

Meal-delivery and van duties are qualified per named route.

| Field | Type | Req | Src | Excel? | Ask? |
|---|---|---|---|---|---|
| `worker_id` | FK | ✔ | | | |
| `route_code` | enum (灣仔1…寶珍, van duties) | ✔ | skill matrix | ◐ | ✔ full matrix |
| `qualified` | bool | ✔ | `v` | ◐ | |

## 6. OrgUnit / Center

| Field | Type | Req | Src | Excel? | Ask? |
|---|---|---|---|---|---|
| `code` | enum `AMC/MRC/GC/EH/IH/ED/HSS/DECC/KLC` | ✔ | files | ✔ | ✔ full names |
| `kind` | enum `center/home_team/external` | ✔ | transcript (3 centres + 2 home teams) | ◐ | ✔ |
| `district` | string | ✔ for travel | transcript (2×灣仔, 1×北角) | ✘ mapping | **✔ which code is where** |

## 7. FixedService

A recurring commitment: elder × service × weekday × period/session × (usually) fixed worker.

| Field | Type | Req | Src | Excel? | Ask? | Validation |
|---|---|---|---|---|---|---|
| `id` | string `FS####` | ✔ | system | — | | |
| `elder_id` | FK | ✔ | assignment cell | ✔ | | |
| `service_code` | FK | ✔ | cell prefix | ✔ | | |
| `weekday` | 1–6 | ✔ | row block / `時間` col | ✔ | | |
| `period` | `AM/PM` | ✔ | row block / `一上` | ✔ | | |
| `session_index` | 1/2/null | | which slot-pair in the block | ◐ | ✔ are sessions hard slots? | |
| `start_time`/`end_time` | time | | detail cell | ✔ | | within worker hours |
| `week_pattern` | enum (see dictionary §5) | ✔ | `節數`, `(1,3)` | ✔ (with un-mangling) | ✔ 長周/BL/definition of week-of-month | |
| `assigned_worker_id` | FK | usual | column position / 照顧員 | ✔ | | must satisfy skill+gender |
| `is_exclusive` | bool | ✔ | EX_RO default; notes `只要娥姐` | ◐ | ✔ per-case confirmation | |
| `alternate_group` | string | | 單月/雙月 pairs (廖祥輝/李巧珍) | ◐ | | mutual exclusion by month parity |
| `district` / `estate` | string | ✔ for travel | detail cell | ◐ | | |
| `case_manager_alias` | string | | trailing name in detail cell | ◐ | ✔ | |
| `priority` | int | ✔ | ServiceType default | — | | |
| `effective_from/to` | date | | comments, transfer log | ◐ | | |
| `source_ref` | string | ✔ | e.g. `恆常服務!H3` | ✔ | | traceability |
| `source_confidence` | enum `high/medium/low` | ✔ | reverse-engineering evidence / config / support parser | — | | low ⇒ AuditItem |

## 8. EscortRequest

| Field | Type | Req | Src | Excel? | Ask? |
|---|---|---|---|---|---|
| `id` | string `ER####` | ✔ | system | — | |
| `service_date` | date | ✔ | col A | ✔ | |
| `period` | `AM/PM` | ✔ | col C | ✔ | |
| `elder_id` | FK | ✔ | 姓名+部門 | ✔ (via name resolution) | |
| `appointment_time` | time | | 應診時間 | ✔ (tolerant parse) | |
| `pickup_lead_minutes` | int | | 備註 patterns (`提早一小時`) | ◐ | |
| `destination_code` | FK Gazetteer | | 目的地 | ◐ | ✔ gazetteer |
| `subject` | string | | 科目 | ✔ | |
| `transport` | string | | 交通工具 | ✔ | |
| `gender_requirement` | enum `M/F/any` | ✔ default any | **not explicit** | ✘ | ✔ how is it decided today? |
| `preferred_worker_id` | FK | | 備註 (`建議安排菲菲`) | ◐ regex | |
| `preference_strength` | enum `must/prefer` | | `只要`→must, `建議/盡量`→prefer | ◐ | ✔ |
| `remarks_raw` | string | ✔ keep | 備註 | ✔ | |
| `handler_alias` | string | | 經手人 | ✔ | |
| `logged_on` | date | | 填寫日期 | ◐ | |
| `status` | enum `requested/scheduled/cancelled/changed` | ✔ | bottom change-log section | ◐ | |
| `source_ref` | string | ✔ | cell ref | ✔ | |

## 9. CenterDutyRequirement

What each centre needs per weekday/period. **Not explicit anywhere** — reconstruct by counting duty cells per (centre, weekday, period, role) in the division sheet, then confirm with NGO.

| Field | Type | Req | Src | Excel? | Ask? |
|---|---|---|---|---|---|
| `center_code` | FK | ✔ | | ✔ | |
| `weekday` | 1–6 | ✔ | | ✔ | |
| `period` | AM/PM | ✔ | | ✔ | |
| `role` | enum `general/lead/assist/activity/medication/cleaning` | ✔ | cell suffixes | ◐ | ✔ |
| `required_count` | int | ✔ | **counted, not declared** | ◐ | **✔ blocking for duty coverage rule** |
| `min_count` | int | | | ✘ | ✔ degradation floor |

## 10. WorkerAvailability

Effective per-slot availability, derived: base hours − leave − OFF-Saturday − blocked slots.

| Field | Type | Req | Src | Excel? |
|---|---|---|---|---|
| `worker_id` | FK | ✔ | | |
| `date` | date | ✔ | | |
| `period` | AM/PM | ✔ | | |
| `available` | bool | ✔ | derived | — |
| `reason` | enum `working/leave/off_rotation/blocked/capacity_lock` | ✔ | `OFF`, `不可加Case` | ◐ |

## 11. LeaveEvent

| Field | Type | Req | Src | Excel? | Ask? |
|---|---|---|---|---|---|
| `id` | string | ✔ | system | — | |
| `worker_id` | FK | ✔ | manual entry (today: verbal/Teams) | ✘ | |
| `date` | date | ✔ | | ✘ | |
| `scope` | enum `full_day/AM/PM` | ✔ | PDF I-3 | ✘ | |
| `leave_type` | enum `AL/SL/other` | | | ✘ | ✔ does type matter? |
| `reported_at` | datetime | ✔ | | ✘ | drives same-day vs planned flow |

## 12. ServiceCancellationEvent

| Field | Type | Req | Src | Ask? |
|---|---|---|---|---|
| `id` | string | ✔ | system | |
| `elder_id` | FK | ✔ | Teams message / escort change-log | |
| `date_from` / `date_to` | date | ✔ / null | | open-ended for hospitalisation |
| `service_scope` | enum `all/specific` + `service_codes[]` | ✔ | PDF I-3 | |
| `reason` | enum `hospitalised/personal/deceased/other` + text | ✔ | | ✔ does reason change re-use of freed slot? |
| `reported_at` | datetime | ✔ | | |

## 13. EscortQuotaOverride

| Field | Type | Req | Notes |
|---|---|---|---|
| `date` | date | ✔ | |
| `period` | AM/PM | ✔ | nominal baseline 4 `[C]`; reserved template slots observed 1-5 and demand observed 0-6 |
| `required_count` | int ≥0 | ✔ | actual demand for that half-day |
| `source` | enum `escort_table_count/manual` | ✔ | normally derived by counting EscortRequests |

## 14. ScheduleEntry

One worker × date × period(/session) × task. The atom of a roster.

| Field | Type | Req | Validation |
|---|---|---|---|
| `id` | string | ✔ | |
| `schedule_version_id` | FK | ✔ | |
| `date` / `weekday` / `period` / `session_index` | as above | ✔ | weekday consistent with date |
| `worker_id` | FK nullable | | null ⇔ `status=unassigned` |
| `service_code` | FK | ✔ | |
| `elder_id` | FK nullable | | required for home_visit/escort |
| `origin_fixed_service_id` / `origin_escort_request_id` | FK nullable | | exactly one for demand-backed entries |
| `center_code` / `route_code` / `destination_code` | nullable | | per category |
| `start_time`/`end_time` | time | | overlap check per worker |
| `source` | enum `template/weekly_fill/system_reassigned/manual/import` | ✔ | |
| `status` | enum `scheduled/needs_review/affected/cancelled/unassigned` | ✔ | |
| `explanation` | string | | human-readable reason for system choices |
| `constraint_flags` | string[] | | e.g. `gender_ok_unverified`, `skill_unknown` |

## 15. ScheduleVersion

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | string | ✔ | |
| `week_start` | date (Monday) | ✔ | |
| `parent_version_id` | FK nullable | | rescheduling lineage |
| `kind` | enum `baseline/repair/manual_edit/import` | ✔ | |
| `created_by` | enum `system/user:<id>` | ✔ | |
| `trigger_event_ids` | FK[] | | LeaveEvent etc. that caused a repair |
| `status` | enum `draft/under_review/published/superseded` | ✔ | published Friday `[C]` |
| `metrics` | object | | see `../evaluation/evaluation_metrics.md` |
| `diff_summary` | object | | entries added/removed/changed vs parent |

## 16. AuditItem

See `audit_item_schema.json` for the full JSON Schema (single source of truth). Core: `id, version_id, kind, severity, status(pending/approved/rejected/edited), reason, evidence_refs[], original_entry, suggested_entry, alternatives[], decision{by, at, note, edited_entry}, downstream_impact[]`.

## 17. ManualOverride

A human decision that must survive re-solves.

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | string | ✔ | |
| `scope` | enum `entry/week/recurring` | ✔ | recurring overrides feed back into FixedService |
| `pin` | object `{worker_id?, elder_id?, date?, weekday?, period?, service_code?}` | ✔ | pattern the solver must honour |
| `action` | enum `pin_assignment/forbid_assignment/cancel/free_text` | ✔ | |
| `reason` | string | ✔ | required — future explainability |
| `created_by` / `created_at` | | ✔ | |
| `effective_from/to` | date | | |
| `origin_audit_item_id` | FK nullable | | traceability chain |

## 18. ExportJob

| Field | Type | Req | Notes |
|---|---|---|---|
| `id` | string | ✔ | |
| `schedule_version_id` | FK | ✔ | |
| `format` | enum `division_sheet/escort_sheet/hc_sheet/review_pack` | ✔ | see `excel_io_contract.md` |
| `options` | object | | include_audit, mark_changes… |
| `status` | enum `queued/done/failed` | ✔ | |
| `file_ref` | string | | |
| `created_at` | datetime | ✔ | |

## 19. Supporting tables

- **PersonAlias** `{id, kind: worker/elder, alias, real_name(encrypted, NGO-side only), verified: bool}` — the only place real names may exist; excluded from all exports and model calls.
- **SourceEvidenceBatch** `{id, source_kind, source_ref, captured_at, stats, ambiguities[], confidence_summary}` — support parser/import runs and manual config loads remain traceable without making workbook upload the product workflow.
- **Gazetteer** `{code, label, kind: hospital/clinic/bank/shop/other, district, typical_duration?}` — escort destinations.
- **TravelMatrix** `{from_district, to_district, minutes}` — seeded from HK Island transit estimates, NGO-adjustable; drives the travel penalty.
- **ChangeEvent** — supertype envelope `{id, type: leave/cancellation/escort_quota/escort_new/duty_gap/manual, payload, reported_at, processed_in_version_id}` unifying §11–13 for the rescheduler event queue.

## 20. Entity relationships (summary)

```
Employee 1─n WorkerSkill n─1 ServiceType
Employee 1─n WorkerRouteQualification
Employee 1─n ScheduleEntry n─1 ScheduleVersion
Elder    1─n FixedService n─1 ServiceType
Elder    1─n EscortRequest
FixedService 1─n ScheduleEntry (occurrences)
EscortRequest 1─0..1 ScheduleEntry
CenterDutyRequirement 1─n ScheduleEntry (fills)
ChangeEvent n─1 ScheduleVersion (trigger)
AuditItem n─1 ScheduleVersion; AuditItem 0..1─1 ManualOverride (on decision)
OrgUnit 1─n Employee; OrgUnit 1─n Elder (owning_unit)
```
