# Mock Data Specification

**Status:** v0.2.0 implementation-aligned · Design for a realistic synthetic dataset that reproduces the *statistical shape and pathologies* of the real workbooks — not toy examples. Generated deterministically (`seed=2026`) by `backend/app/mockdata/generator.py`. Current metric definitions are in `evaluation_metrics.md`; aspirational optimizer cases are archived separately as `../future/target_benchmark_cases.json`.

Fidelity targets come from the observed files: worker/elder counts and name style, session-time conventions, escort volume distribution, colour semantics, week patterns **including corrupted ones**, and inconsistent masking (so the importer's flagging paths get exercised).

---

## 1. Population

### 1.1 Employees (52)

| Segment | Count | Notes |
|---|---|---|
| Home-visit generalists (HW-style) | 22 | skills: E+RO(≈70% of them), HC(≈50%), MEAL(all), ESC(all), 1–2 duty centres |
| Centre-attached (AMC/MRC/GC tags) | 12 | 4 per centre; duty skills at own centre + MEAL; 6 also ESC |
| Escort-heavy generalists | 6 | the yellow-slot holders; ESC + MEAL + 1 duty centre |
| Bath/PC specialists | 4 | BATH+PC+HC; 3 female, 1 male (gender-sensitive coverage pressure) |
| Kitchen/logistics | 4 | KITCHEN, VAN, MEAL routes only |
| New joiners (partial skill matrix) | 4 | some skills `unknown` → exercises data-gap flow |
| **Departed mid-year** | 2 (extra) | gray-column simulation; cases transferring with TBC |

Attributes: gender 42F/10M `[reflects sector reality; confirms gender scarcity for male-required cases]`; work hours mixed `8:30–17:30`(60%), `9:00–17:30`(25%), `9:00–17:00`(10%), one `(7小時)` part-timer; Saturday team A/B split 50/50, 4 workers `none`; nicknames in the real style (單字/雙字 + optional tag).

### 1.2 Elders (320)

| Segment | Count | Services |
|---|---|---|
| E+RO recipients | ~168 | 1–2 sessions/week, fixed worker, ~30% marked exclusive-strict |
| HC recipients | ~80 | week patterns: 40% `1,3`/`2,4`, 35% single week, 15% weekly, 5% 單月/雙月, 5% corrupted-into-date patterns |
| Meal-only | fill to 320 | attached to routes, no individual scheduling |
| Bath/PC | 25 | all gender-constrained (20 F-req, 5 M-req — M-req creates scarcity) |
| Escort users | 70 (overlapping) | drawn from all segments; 8 recurrent (weekly 覆診) |
| Alternate-month pair | 2 | 單月/雙月 shared slot |
| Preference notes | 12 | `只要X` (4), `建議安排X` (8) |

Units: EH 45%, IH 35%, ED 8%, AMC/MRC/GC/HSS members 12%. Districts sampled from the real vocabulary (灣仔…小西灣) with estate labels on 30%; 5 elders with district **missing** (importer gap). Gender 70F/30M; 6 elders gender **unknown** (data-gap flow).

### 1.3 Organisation

3 centres: AMC (灣仔), MRC (灣仔), GC (北角) `[assumed mapping — flagged]`; 2 home teams EH/IH; 1 kitchen (柴灣廚房). Travel matrix: 30-zone HK Island belt, minutes 5–55, asymmetry ignored; 灣仔↔柴灣 = 40 min (the ping-pong pain pair).

## 2. Demand fabric (one reference month, 2026-06)

- **FixedServices:** ≈480 rows → ≈560 weekly occurrences (E+RO 320, HC 95 pattern-expanded ≈45/wk, BATH/PC 30, MEAL route duties 70, misc 45).
- **CenterDutyRequirements** (counted-from-Excel style): AMC AM=4 (1 lead, 1 assist, 1 medication, 1 activity), AMC PM=3; MRC AM=3, PM=3 (+2 cleaning Mon/Wed/Fri PM); GC AM=2, PM=2; Saturday: MRC only, 6 general slots. Total ≈ 130 duty units/week.
- **Escort requests (week of 2026-06-08, the benchmark week):** Mon 4+2, Tue 3+3, Wed 5+2 (**over quota AM**), Thu 2+2 (**under quota**), Fri 4+3, Sat 1+0. Attributes sampled from the real gazetteer (PY, RH, QM, 東華東院…), 20% with `提早X分鐘` remarks, 3 with preference notes, 2 with messy time strings (`10:00前`, `02:30` PM).
- **Escort quota baseline:** nominal 4/period, but real reserved slots vary by weekday/period (observed 1-5) and real demand can peak at 6.

## 3. Injected pathologies (importer & reviewer test surface)

1. 6 week-pattern cells corrupted to Excel dates (`1,5` → `2024-01-05`).
2. 4 elders with full (fake) real names unmasked; 3 duplicate masked aliases (`C蓮` ×2 different units + 1 same-unit near-collision) — name-resolution flow.
3. 2 workers appear only in detail cells (case managers) — role ambiguity.
4. 1 cyan incomplete cell (`HC:` without case), 3 free-text-only cells (`康雲計劃` variants), 1 cell comment carrying an effective-dated time change.
5. 2 TBC transfers in the transfer log; 1 `生效日期 = 待定(9月?)`.
6. Missing skill rows for the 4 new joiners (`unknown`, not false).
7. One `不可加Case` capacity lock; one `(轉X做)` inline transfer note.

## 4. Change-event scripts (the benchmark week)

| # | Day | Event | Expected pressure |
|---|---|---|---|
| EV1 | Tue | Full-day leave, escort-heavy worker (holds 2 ESC + 1 duty) | escort reassign + duty refill |
| EV2 | Tue | Half-day AM leave, E+RO exclusive worker (3 exclusive visits) | 3 exclusive cancellations |
| EV3 | Wed | 5th escort AM (over quota) | displacement chain depth 1–2 |
| EV4 | Thu | Elder hospitalised (HC `2,4` + weekly E+RO + Fri escort) | open-ended suspension + escort auto-cancel + refills |
| EV5 | Thu | Escort demand drops 2→2 (already under) + duty gap at GC (EV1 ripple) | release ordering + cross-centre pull |
| EV6 | Fri | Batch: 2 leaves + 1 cancellation + 1 extra escort simultaneously | §9 batch ordering, depends_on groups |
| EV7 | any | Elder cancels single HC occurrence, freed worker has no gap | idle-release info path |

## 5. Dataset packaging

- `mock/canonical.json` — full dataset conforming to `schema.json`.
- `mock/excel/` — optional support fixtures rendered into NGO-like workbook formats (with colours, merges, pathologies) so parser regressions can be tested against ground truth: `分工表_mock.xlsx`, `HC時間表_mock.xlsx`, `護送總表_mock.xlsx`.
- `mock/events/*.json` — EV1–EV7 as ChangeEvent payloads.
- `backend/scripts/run_benchmark.py` — executable current benchmark and
  assertions. `../future/target_benchmark_cases.json` is a future test design,
  not a file consumed by the runner.
- Support parser invariant: fixture parses should preserve canonical facts modulo injected pathologies; each pathology should yield an explicit source ambiguity. This is a parser regression check, not the product success metric.

## 6. Sizing sanity check vs reality

| Dimension | Real (observed/claimed) | Mock |
|---|---|---|
| Workers | 46 columns visible / ~50 claimed | 52 (+2 departed) |
| Elders | ~296 distinct visible / ~400 claimed | 320 |
| Weekly assignment cells | ~600–800 | ≈700 |
| Escorts per half-day | 0–6 observed, reserved slots 1–5 | 0–6, baseline 4 |
| Centres | 3 (+kitchen, +2 home teams) | 3 (+1, +2) |
| Duty slots/week | unknown (countable ≈120–150) | 130 |
