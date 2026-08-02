# Rulebook — Scheduling Business Rules

**Status:** v0.1 · Extracted from `docs/transcript.docx` (auto-transcribed Cantonese/Mandarin meeting), the three Excel workbooks, and `docs/wan chai requirements.pdf` (an earlier requirements digest whose rules R-1…R-9 we cross-reference as `PDF R-n`).

**Classification** — E: explicitly stated · S: strongly implied · W: weakly inferred · U: unclear, needs clarification.
**Kind** — HARD: must hold in any published roster (violation ⇒ infeasible or human-approved exception) · SOFT: optimized, may be traded off.
**Priority scale** — P0: never violate · P1: violate only with explicit human approval (AuditItem) · P2: strong soft (high penalty) · P3: normal soft · P4: tie-breaker.

Transcript quotes are reproduced as-is from a noisy auto-transcription; wording is approximate but meaning was verified against the PDF digest where possible.

---

## A. Assignment feasibility

### RB-SKILL-01 · Skill matching — E · HARD · P0
- **Business meaning:** a worker may only be assigned a service they are qualified for; not every worker can do every service ("如果個工作員…技能可以做的東西有一點不同").
- **Formal:** `assign(w, task) ⇒ WorkerSkill(w, task.service_code).level ∈ {qualified, lead}`.
- **Evidence:** transcript ln 8, 14, 18–19; PDF R-1 table; Excel: 新同工跟服務紀錄表 tick matrix.
- **Open:** full skill matrix exists only for 6 new staff; the other ~44 must be collected (blocking).

### RB-SKILL-02 · Meal delivery is universal — E · HARD (as an exemption) · P0
- **Business meaning:** anyone may deliver meals ("in general 送飯就係任何人").
- **Formal:** `service_code = MEAL` bypasses the skill gate (but not RB-SKILL-03).
- **Evidence:** transcript ln 49–50; PDF R-1 (送饭: 任何人可做).

### RB-SKILL-03 · Meal routes are route-qualified — S · HARD · P1
- **Business meaning:** meal delivery is organised in named routes (灣仔1…寶珍) and new staff are signed off per route; an unfamiliar route needs shadowing.
- **Formal:** `assign(w, MEAL@route) ⇒ WorkerRouteQualification(w, route).qualified` — violable with human approval (someone must deliver).
- **Evidence:** 新同工跟服務紀錄表 送飯 section (13 routes, per-worker ticks).
- **Open:** is route qualification a hard rule for experienced staff, or onboarding-only? (U)

### RB-SKILL-04 · Centre duty is per-centre qualified — S · HARD · P1
- **Formal:** `assign(w, DUTY_X) ⇒ WorkerSkill(w, DUTY_X)`; most workers qualify ("中心当值 通用，多数员工可做" PDF R-1) but the matrix has per-centre rows (AMC當值+清潔 / MRC / GC).
- **Open:** duty **roles** (派藥 medication, 帶活動 activity-lead, 換片) may need extra certification — U.

### RB-GEND-01 · Gender match for body-contact services — E · HARD · P0
- **Business meaning:** bath / personal-care (and some escorts) require worker gender to match elder gender or the elder's stated requirement ("涉及身体接触的服务…员工性别须与长者性别或长者要求相符" PDF R-2; transcript ln 50 "陪診都係…分性別").
- **Formal:** `task.gender_requirement ≠ any ⇒ gender(w) = task.gender_requirement`, where requirement = elder's explicit requirement, else elder gender for `gender_sensitive` services.
- **Open:** neither worker nor elder gender exists in the files (blocking data request). If gender is unknown at solve time the pair is **ineligible** and flagged `gender_ok_unverified` (safe default).

### RB-GEND-02 · Escort gender is per-case — E · HARD · P0
- **Business meaning:** escorts are open to any escort-capable worker, "就係分性別啫" — the only differentiator is gender when the case demands it.
- **Formal:** as RB-GEND-01, using `EscortRequest.gender_requirement`.
- **Open:** how is the requirement decided today — same-gender by default, or only when elder asks? (U)

### RB-EXCL-01 · Exclusive worker–elder binding — E · HARD · P0
- **Business meaning:** exercise-training elders are taught by their dedicated worker ("做開嗰個同事就會跟嗰個同事，就唔會調動… 佢哋會專屬去教佢哋嘅動作"); elders may refuse others ("有啲我又唔中意你… 你唔好再叫佢嚟啦").
- **Formal:** `FixedService.is_exclusive ⇒ assigned_worker is the only eligible worker`.
- **Evidence:** transcript ln 26–27; PDF R-3; Excel notes `只要娥姐`.

### RB-EXCL-02 · Exclusive service + absent worker ⇒ cancel, never substitute — E · HARD · P0 (cancellation itself requires human confirmation, P1)
- **Business meaning:** "有啲服務，佢係專屬佢嘅服務咧，就會取消咯" — when the bound worker is on leave, the service is cancelled, not reassigned ("直接取消，不尝试替换" PDF R-3).
- **Formal:** `leave(w,d) ∧ FixedService(f).assigned=w ∧ f.is_exclusive ⇒ entry(f,d).status=cancelled + AuditItem(kind=exclusive_cancellation)`.
- **Open:** must the NGO confirm each cancellation before it is communicated? (assumed yes → human review trigger).

### RB-EXCL-03 · Note-based bindings count as exclusivity — S · HARD · P1
- **Business meaning:** free-text notes create real bindings: `只要娥姐` (HC sheet), `安排啊茵`, `安排栢如` (escort table).
- **Formal:** the reverse-engineered rule maps `只要X`/`安排X` (imperative) → `must`; `建議安排X`/`盡量安排X` → `prefer` (see RB-ESC-07). A support parser may extract these hints from sample remarks. `must` behaves like RB-EXCL-01.
- **Open:** confirm the must/prefer keyword mapping with the NGO.

### RB-EXCL-04 · Only the exclusive services cancel; the rest of an absent worker's load is redistributed — E · HARD · P0
- **Evidence:** transcript ln 7–8 (leave ⇒ some work covered by colleagues, 專屬 services cancelled); PDF R-8 steps 1–3.
- **Formal:** partition absent worker's entries into exclusive (cancel per RB-EXCL-02) and non-exclusive (reassign per RB-LEAVE-02).

## B. Time & capacity

### RB-TIME-01 · No double-booking — S · HARD · P0
- **Business meaning:** one worker cannot be in two places at once; the grid has at most 2 sessions per half-day and each holds one task.
- **Formal:** for each (w, date, period, session): ≤1 entry; when explicit times exist, intervals (incl. travel buffer, RB-GEO-01) must not overlap; `occupies=half_day` tasks (ESC) exclude both sessions.
- **Evidence:** structure of 恆常服務; PDF open question on max sessions/day confirms sessions are the unit.
- **Open:** can a worker ever take 3 short tasks in a half-day? Extra rows in some blocks suggest occasionally yes (U).

### RB-TIME-02 · Per-worker working hours — E · HARD · P0
- **Business meaning:** workers have individual daily hours (R108: `8:30-17:30`, `9:00-17:00`, `(7小時)`), "上班時間…差不多" but not identical.
- **Formal:** `entry.start_time ≥ w.work_start ∧ entry.end_time ≤ w.work_end`; count of assigned sessions ≤ daily capacity.
- **Open:** lunch break protection (跟車 cells mention `午膳+AMC中午回程`) — is 13:00–14:00 blocked for everyone? (U)

### RB-TIME-03 · Week shape: Mon–Fri full service, Saturday reduced by A/B rotation, Sunday closed — E/S · HARD · P0
- **Evidence:** title `星期一至五(每日8小時)`; Saturday block `六 更新版` with `OFF` cells and R93 A/B team lists; escort table has empty Sat/Sun rows (occasional Saturday escorts exist, e.g. 2026-01-17).
- **Formal:** Saturday availability = `works_saturday_team matches week parity`; Sunday: no scheduling.
- **Open:** exact A/B alternation anchor (which weeks are "A weeks"?) — U (blocking for Saturday rosters).

### RB-CAP-01 · Slot capacity locks — E(note) · HARD · P1
- **Business meaning:** `不可加Case` on 嫦's Tue AM = this worker-slot must not receive additional assignments even if free.
- **Formal:** `ManualOverride(action=forbid_assignment, pin={worker, weekday, period})` honoured by solver.

## C. Fixed services & patterns

### RB-FIX-01 · Fixed services occur at their fixed weekday/period/time with their fixed worker — E · HARD · P1
- **Business meaning:** "每一個同事…已經有啱固定嘅安排"; fixed services are pre-committed appointments with elders.
- **Formal:** for each active FixedService occurrence in the week: create task pinned to (weekday, period, time); assigned worker = template worker unless a ChangeEvent intervenes.
- **Evidence:** division sheet is exactly this template; PDF I-2.

### RB-FIX-02 · Week-of-month patterns govern non-weekly services — E · HARD · P0
- **Business meaning:** HC (and some B/PC/Esc) run on patterns: weeks 1,3 / 2,4 / single weeks / odd/even months.
- **Formal:** occurrence exists in week k of month m iff `week_pattern.matches(k, m)`; see `data_dictionary.md` §5.
- **Open:** definition of "week of month" (k-th occurrence of weekday vs calendar week grid) — U, blocking for HC generation; meaning of `長周`, `BL` — U.

### RB-FIX-03 · Alternate-month pairs — E(footnote) · HARD · P0
- **Business meaning:** `**廖祥輝雙數月份/李巧珍單數月份` — two elders share a slot, alternating by month parity.
- **Formal:** `alternate_group` members are mutually exclusive per month parity.

### RB-FIX-04 · Effective-dated template changes — S · HARD · P0
- **Business meaning:** cells carry `11月開始轉家偉做`, comment `6/3 開始改時間`, transfer log `生效日期` — assignments change on effective dates, sometimes tentatively (`TBC`).
- **Formal:** template resolution at week W uses rows where `effective_from ≤ W < effective_to`; `TBC` rows are surfaced as review items, not applied.

## D. Escort rules

### RB-ESC-01 · Escort capacity baseline: ~4 per half-day, template-varying — E · SOFT (capacity planning) · P2
- **Business meaning:** "我哋固定的情況…每一天每一個上午或下午都有4個的名額" — the template pre-reserves escort-capable workers per half-day (the bright-yellow ESC cells).
- **Formal:** baseline = per-(weekday, period) count of reserved ESC template slots (observed 1–5, e.g. Mon AM 4, Mon PM 5, Thu PM 1), **not a constant 4**; actual = count of EscortRequests (observed 0–6 per half-day); the reserved-slot workers are the default candidate pool.
- **Evidence:** transcript ln 33–39 (says "4" and "2–5"); PDF I-2; yellow ESC cell census + AZ counter column (fact-check E2: observed demand peaks at 6, reserved slots at 5 — the transcript understates both).

### RB-ESC-02 · Demand below baseline frees workers into the priority cascade — E · HARD (behaviour) · P0
- **Business meaning:** "如果少過四個…呢啲同事就會編排去做其他工作", first to centre duty ("首先他们要去当职").
- **Formal:** unneeded ESC_SLOT holders become free capacity; refill per RB-PRIO-01; each refill generates an explanation + review item (info level).
- **Evidence:** transcript ln 34–37, 42–44; PDF R-7 case A.

### RB-ESC-03 · Demand above baseline pulls extra qualified workers and must show chain impact — E · HARD (behaviour) · P1
- **Business meaning:** a 5th escort must be found from workers with free/lower-priority time; the system must show "整個工作流程會出現怎樣的狀況" — the displaced work chain.
- **Formal:** create extra ESC task; candidate pool = escort-qualified ∧ gender-ok ∧ available-or-displaceable (displaceable = assigned to a task with lower priority that has other candidates); output the full displacement chain as AuditItems.
- **Evidence:** transcript ln 38–42; PDF R-7 case C.

### RB-ESC-04 · Escort lead time ≈ ≤1 week; same-day surprises are manual — E · process rule
- **Business meaning:** "大概一個星期前就知道最多"; same-day disruptions are edited by hand ("突發間都係人手修改").
- **Formal:** weekly solve consumes the escort table snapshot; intra-week events go through the repair flow (see `rescheduling_algorithm.md`), and tiny changes may bypass the system entirely (RB-CHG-01).

### RB-ESC-05 · Escort appointment times are immovable — E · HARD · P0
- **Business meaning:** medical appointments cannot be delayed ("护送／陪诊（时间固定，不可延误）" PDF R-6).
- **Formal:** ESC tasks are fixed-time; worker must be free from `appointment_time − pickup_lead − travel` to end of appointment (duration unknown → occupies the half-day, RB-TIME-01).

### RB-ESC-06 · Pickup lead time from remarks — S · HARD · P1
- **Business meaning:** remarks specify `提早一小時接長者`, `8:30到長者家` etc.; the escort effectively starts earlier than the appointment.
- **Formal:** `effective_start = appointment_time − pickup_lead_minutes` (default lead: U — propose 45 min, confirm).

### RB-ESC-07 · Escort worker preferences — E(notes) · must=HARD P1 / prefer=SOFT P3
- **Business meaning:** `建議安排菲菲陪診`, `盡量安排照顧員嫦陪診(有關藥物)`, `安排啊茵`.
- **Formal:** `preference_strength=must` ⇒ eligibility restricted to that worker (deviation needs approval); `prefer` ⇒ soft bonus for that worker.

### RB-ESC-08 · One escort worker per request; a worker takes ≤1 escort per half-day — W · HARD · P1
- **Rationale:** each request lists a single elder/time; no evidence of doubling up; occupies=half_day assumption.
- **Open:** can one worker chain two same-hospital escorts in one half-day? (U — matters for capacity).

## E. Centre duty

### RB-DUTY-01 · Every centre staffed every operating half-day — E · HARD · P0 (down to `min_count`; below that P1 with approval)
- **Business meaning:** "三間中心…每天都需要有人當值"; duty is the top of the priority cascade; it also acts as the absorber of spare capacity ("當值系冇cover嘅…咪攝晒落去").
- **Formal:** for each (centre, weekday, period, role): assigned count ≥ required_count (from CenterDutyRequirement); shortfall ⇒ under-coverage AuditItem (high severity).
- **Evidence:** transcript ln 27–29, 43–47; PDF R-5; division sheet duty cells.
- **Open:** required_count per centre/period/role is only countable, not declared (blocking).

### RB-DUTY-02 · Duty rotation fairness — E · SOFT · P3
- **Business meaning:** "輪著來，平均一點" — centre-duty load should even out across workers over time.
- **Formal:** minimize spread of per-worker duty counts over a rolling horizon (future formulation: `../future/optimization_model.md` §5.4).

### RB-DUTY-03 · Centre affinity — E · SOFT · P3
- **Business meaning:** "有一啲…會熟啲嘅" — A同事 usually AMC, B同事 usually MRC; workers should mostly serve their familiar centre, without freezing rotation entirely.
- **Formal:** bonus for `home_team = centre`; tension with RB-DUTY-02 resolved by weights (fairness within the affine pool first — U confirm).

### RB-DUTY-04 · Spare capacity defaults to centre duty — E · HARD (behaviour) · P0
- **Business meaning:** freed workers go to duty first, then cascade ("如果他們不用去護送，他們就去當值").
- **Formal:** the refill step of every repair starts at DUTY tasks with unmet counts; if all met, continue down RB-PRIO-01.

## F. Priorities, geography, workload

### RB-PRIO-01 · Global priority cascade — E · structural
- **Business meaning:** "應該每一個服務都要 set 個 priority，佢就會一路排落去".
- **Order (confirmed):** 1) centre duty 2) escort 3) fixed home services (E+RO/HC/PC/B, 送飯) 4) other floating/admin tasks. (PDF R-6.)
- **Open:** ordering *within* tier 3 (is 送飯 below E+RO?); where 執牌/跟車/康雲計劃 sit — U. ServiceType.default_priority encodes the answer.

### RB-GEO-01 · Minimise travel time within a worker's day — E · SOFT · P2
- **Business meaning:** "盡量讓同事不會東奔西跑… 唔係地點係個 traveling 嘅時間" — optimize travel *time*, not distance labels.
- **Formal:** penalty = Σ TravelMatrix[district(task_i), district(task_{i+1})] over consecutive tasks per worker-day; also enforce feasibility buffer between timed tasks (HARD when times known).
- **Evidence:** transcript ln 23–25; PDF R-4.

### RB-GEO-02 · No ping-pong routing — E · SOFT · P2
- **Business meaning:** avoid 灣仔→筲箕灣→灣仔 patterns ("唔會俾…去完A…又翻嚟").
- **Formal:** extra penalty when a worker-day district sequence revisits a district after leaving it (captured naturally by the travel-matrix sum; add a revisit surcharge).
- **Open:** are escort destinations part of geography optimization, or only home visits? (PDF open question — U.)

### RB-GEO-03 · Workers self-travel by public transport — E · context
- **Formal:** no vehicle-capacity constraint; travel time matrix reflects public transport (的士 for escorts is per-case, from 交通工具).

### RB-LOAD-01 · Workload balance — S · SOFT · P3
- **Business meaning:** fairness is explicit for duty (RB-DUTY-02) and implied generally ("平均一點"); no explicit quota per worker beyond hours.
- **Formal:** minimize variance of assigned-session counts per worker per week (secondary to all P2 objectives).

## G. Change handling & process

### RB-LEAVE-01 · Leave makes the worker's slots unavailable and their tasks pending — E · HARD · P0
- **Formal:** `leave(w, d, scope)` ⇒ availability false for scope; entries → `affected`; exclusive → RB-EXCL-02; rest → RB-LEAVE-02. (PDF R-8.)

### RB-LEAVE-02 · Replacement candidates must satisfy all hard rules; prefer same district, then priority-displacement — E/S · HARD+SOFT
- **Formal:** candidates = qualified ∧ gender-ok ∧ available ∧ not-forbidden; rank by (travel penalty delta, workload delta, affinity); if none free, consider displacement of strictly lower-priority tasks (chain depth ≤ 2, W — confirm) with full chain shown for approval.

### RB-CANC-01 · Elder cancellation frees the worker; freed time refills by cascade — E · HARD (behaviour) · P0
- **Business meaning:** hospitalisation etc. cancels the visit; the worker gets new work that day — "一般來說…直接去中心當值… 或者送飯都可以分給那位同事，但大概都是安排他去中心當值".
- **Formal:** cancel occurrence(s) for the scope; freed (w, slot) refills starting at duty gaps (RB-DUTY-04); each refill is a suggestion (needs_review), not silent.

### RB-CANC-02 · Hospitalisation is open-ended — E · HARD · P0
- **Business meaning:** "清潔…已經編咗個時間表啦，直至到停佢" — recurring services pause until told otherwise.
- **Formal:** `ServiceCancellationEvent(date_to = null)` suppresses all future occurrences until closed; weekly solve lists still-open suspensions for review.

### RB-CHG-01 · Weekly batch is systematic; micro-changes stay manual — E · process rule
- **Business meaning:** "每個禮拜嗰個大嘢就係希望可以程式去處理… 突發都係人手修改" — the system owns the Friday batch; tiny intra-week tweaks may be typed directly into the sheet/UI without a solver run.
- **Formal:** manual edits are recorded as ManualOverride(entry-scope) so the next solve won't undo them; no re-solve is forced.

### RB-CHG-02 · Minimum-change repair — S · SOFT · P2
- **Business meaning:** a published roster is a commitment to elders and workers; repairs after changes should move as few entries as possible (the NGO's mental model in the transcript is local patching, never full re-shuffles).
- **Formal:** repair objective adds `λ · change_distance(new, baseline)`; published entries not affected by the event are pinned unless releasing them is the only way to restore feasibility (then: approval required).

### RB-PUB-01 · Weekly cadence, published Friday for next week — E · process rule · P0
- **Evidence:** "每個星期我們星期五…發放給同事下一個星期的工作安排".
- **Formal:** solve window = next Mon–Sat; publication freezes a ScheduleVersion (`status=published`).

### RB-PUB-02 · Output must keep the existing Excel format and distribution — E · HARD (product) · P0
- **Business meaning:** staff read the roster on Google Drive in the current layout; v1 must not change their consumption format ("維持佢哋現有嘅格式").
- **Formal:** see `excel_io_contract.md` — export reproduces 恆常服務 layout incl. colours; changed cells are marked.

### RB-PRIV-01 · Pseudonymise before anything leaves the NGO — E · HARD (compliance) · P0
- **Business meaning:** elder full names are sensitive; the NGO masks names before sharing ("全部變咗陳小明… 或者用英文嘅字去代").
- **Formal:** PersonAlias table isolates real names; exports/API/AI calls carry aliases only; support parser/config validation flags full-name leaks (observed in the samples!) and re-masks.

### RB-DATA-01 · Ambiguity never resolves silently — project meta-rule · HARD · P0
- **Formal:** any unparsed cell, un-mangled week pattern, unknown code, unverifiable gender/skill ⇒ `parse_confidence=low` + AuditItem. The solver treats unknown eligibility as ineligible (fail-safe), surfacing the gap instead of guessing.

---

## H. Unclear rules requiring clarification (tracked, not implemented)

| ID | Question | Blocking? |
|---|---|---|
| RB-U-01 | Max tasks/sessions per worker per day; overtime rules (PDF flags as high) | Yes — capacity model |
| RB-U-02 | Duty rotation granularity: rotate by day or by week? (PDF high) | Yes — fairness constraint shape |
| RB-U-03 | Degraded mode when demand > supply: which services drop first? (PDF high) | Yes — infeasibility policy |
| RB-U-04 | Meal delivery time windows (PDF medium) | No — default to session times |
| RB-U-05 | Do escort destinations count in geography penalty? (PDF medium) | No — default yes with low weight |
| RB-U-06 | Week-of-month definition; `長周`, `BL`, `1長周` | Yes — HC generation |
| RB-U-07 | Public holiday behaviour (no evidence anywhere) | Yes for live use |
| RB-U-08 | Case-manager approval role: who approves audit items? | No — assume roster owner |
| RB-U-09 | Are Saturday A/B teams tied to specific week parity or a published calendar? | Yes for Saturday |
| RB-U-10 | Duty roles (派藥/帶活動/主/協): certification-gated? interchangeable? | Yes — duty modelling |
| RB-U-11 | Escort chaining (RB-ESC-08) and average escort duration | No — conservative default |
| RB-U-12 | Does cancellation reason change refill behaviour (e.g. deceased vs hospitalised)? | No — same refill, different elder status |

**Count:** 38 operative rules (A–G) + 12 tracked unknowns. Rules map to the
current deterministic gate/ranking/repair behaviour where implemented; the
future CP-SAT mapping is recorded in `../future/optimization_model.md`. P1
rules also map to review triggers in `human_review_policy.md`.
