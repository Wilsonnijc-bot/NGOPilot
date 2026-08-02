# Fact-Check Report — Specs vs Real Excel Files

**Record type:** dated fact-check; retain and append follow-up corrections rather
than deleting prior findings.<br>
**Date:** 2026-07-01 · **Method:** programmatic re-extraction of all three workbooks (full column range this time), cell-by-cell comparison against every claim in `docs/spec/*.md`. Corrections have been applied directly to the spec files; this report records what changed and what remains unverified.

## 1. Errors found and corrected

### E1 — Worker column count was wrong (37 → 46) ⚠️ significant
The original extraction capped at column 40 (AN) and **missed 9 workers** in columns AO–AX: 志豪, 香, 秀英, 娥, 嘉文, 熙仔(MRC), 梅欽(PT), 奕倫, 炎萍. Verified layout of `恆常服務` row 2:
- **46 named worker columns** across C…AX, with two empty gap columns (G, AQ).
- Columns AY/AZ/BA are **not workers**: they are per-session aggregate counters — `個案數量` and `總數`. Pattern: session 1 rows count `E+RO` and `Esc` cases; session 2 rows count `E+RO` and `D` cases (e.g. Mon AM session 1 = 14 E+RO + 4 Esc = 18 總數). These counters confirm the sheet owner already tracks per-session capacity manually — and give us free ground truth for import validation.
- New tag observed: `(PT)` on 梅欽 — presumably part-time (unconfirmed).
- Fixed in: `../spec/excel_semantics.md` §1.1,
  `../spec/data_dictionary.md` §3/§10, and
  `../evaluation/mock_data_spec.md` §6.

### E2 — Escort demand range was wrong (0–5 → 0–6)
Full January census: **111 requests**; per-half-day histogram: 1×8, 2×10, 3×12, 4×9, 5×1, **6×1**. The transcript's "2–5" and the PDF's "2~5" understate the observed peak. Reserved yellow `ESC` template slots range **1–5** per half-day (not 2–4 as previously written; Mon PM has 5).
- Fixed in: `../spec/data_dictionary.md` §7, `../spec/rulebook.md`
  RB-ESC-01, `../spec/excel_semantics.md` §3/§4, and
  `../evaluation/mock_data_spec.md`.

### E3 — Elder census understated (~230 → ~296 visible)
278 distinct elder aliases parsed from division-sheet assignment cells (all 46 columns) + 18 escort-only names = **~296 distinct visible elders** (NGO claims ~400 — plausible once meal-route-only and HC-only elders are counted).
- Fixed in: `../spec/data_dictionary.md` §10,
  `../spec/excel_semantics.md` §4, and
  `../evaluation/mock_data_spec.md` §6.

### E4 — R93 Saturday team row semantics refined
R93 is **not uniformly** `A : partner-names`. For columns AO–AX it is a bare letter (`A`/`B`); for earlier columns it carries names (`A : 春，家偉`). Reading confirmed: **per-worker Saturday rotation team membership**, with the name-suffix variant's meaning still unknown (partners? coverage?).
- Fixed in: `excel_semantics.md` §1.1 (was already marked `[UNKNOWN]` for the names; now describes both formats).

### E5 — Stacked alternating-week cases in one slot (new semantics)
炎萍's column shows **multiple HC cases stacked in one worker-session slot**, each with a different week pattern (`HC:F玲(EH)(1)` + `HC:Y芬(EH)(3)` in adjacent rows of the same Monday-AM slot). One physical slot serves different elders in different weeks of the month. The importer and the slot model must support N pattern-cases per (worker, weekday, period, session) as long as patterns are disjoint.
- Added to: `excel_semantics.md` §1.1; reflected in the MVP domain model (`FixedService.session_index` + disjoint pattern check).

## 2. Claims re-verified as correct

| Claim | Verification |
|---|---|
| Weekday blocks 一–五 + `六 更新版`, col A merges rows 3–19 / 21–37 / 39–55 / 57–73 / 75–91 / 94–110 | ✔ exact |
| Half-day sub-blocks of 8 rows (上 3–10, 下 12–19, …), 2 slot-pairs + overflow rows | ✔ exact |
| Canonical session times: 9:00–10:30 (×56+11), 11:00–12:30 (×61), 2:00–3:30 (×88), 4:00–5:30 (×51) dominate; many minor variants | ✔ (spec's "8:30–10:30" loosened to "≈9:00–10:30 with 8:30 variants") |
| Escort sheet header (13 cols): 日期/weekday/上下午/姓名/部門/應診時間/目的地/科目/交通工具/備註/經手人/填寫日期/已檢查(ü) | ✔ exact |
| 部門 codes in escort sheet: IH(57), ED(46), AMC(5), HSS(3), GC(1) — EH absent | ✔ (ED≟EH question stands) |
| HC sheet `52026`: Week1–5 blocks; Week 1 header `更改後日期/下次日期`, Weeks 2–5 just `更改` | ✔ exact |
| HC 節數 corruption: 6 cells hold Excel dates (`2024-01-05` ×5 = pattern `1,5`(?), `2025-01-05` ×1) | ✔ exact — count is 6 |
| 個案轉移紀錄_2025: 12 columns as documented, 9 data rows, full real names, TBC/`待定(9月?)` values | ✔ exact |
| 新同工跟服務紀錄表: 6 workers with join dates; categories 送飯(13 routes)/跟車/行政工作/當值/服務 at rows 2/15/20/26/32 | ✔ exact |
| Fill-colour semantics census (yellow ESC, per-centre duty colours, gray departing, cyan incomplete) | ✔ (colour census re-run unchanged) |
| Declared sheet dims inflated (A1:BA981, content ends row 113) | ✔ — importer must not trust `max_row` |
| Transfer log columns, skill matrix `v` semantics, escort bottom `取消/更改` section | ✔ |

## 3. Overconfidence downgrades (now explicitly "Requires NGO confirmation")

These statements were previously presented with more certainty than the evidence supports; wording softened in place:

1. **AM/PM session times as "hard slots"** — the time census shows a long tail of variants (8:30-10:00, 4:15-5:45, 14:30 starts…). Sessions are a *convention*, not a grid. → `excel_semantics.md`, `canonical_schema.md` note.
2. **"Escort occupies the whole half-day"** — inferred from the 4-slot baseline and same-worker ESC in both session rows; never stated by the NGO. MVP keeps the assumption, flagged. (RB-ESC-08 / Q-B5.)
3. **EH = EHCCS, IH = IHCCS expansions** — plausible only. (Q-C3 extended.)
4. **AMC=灣仔, MRC=灣仔, GC=北角 mapping** — pure assumption (Q-C2).
5. **`(1,3)` = 1st/3rd occurrence of that weekday in month** — the HC sheet's own Week1–5 column grid supports occurrence-counting, but 五週月 (`長周`) behaviour unknown (Q-A4).
6. **Baseline "4 per half-day"** — the transcript says 4, the counters show reserved ESC slots of 1–5 varying by weekday/period. Treat the baseline as **per-(weekday, period) template counts**, not a constant 4. → `rulebook.md` RB-ESC-01 updated; mock generator uses per-slot counts.
7. **Gray column = departed** — consistent with transfer notes but the NGO never said it. Stays `[INFERRED]`.

## 4. Facts that remain unverifiable from the files

These remain tracked in
[`../ngo/clarification_packet.md`](../ngo/clarification_packet.md).

Worker/elder gender (Q-A1) · full skill matrix beyond 6 new staff (Q-A2) · duty required counts vs observed counts (Q-A3) · Saturday A/B calendar anchor (Q-A5) · degraded-mode drop order (Q-A6) · meanings of `長周`, `BL`, `半張紙`, `香/丘/雪華/寶珍` route names, `HW/CC/(B)/(PT)/(V)` tags, `ED`, `HSS` · public-holiday behaviour · duty role certifications (派藥 etc.).

## 5. Spec files touched by this fact-check

- `excel_semantics.md` — E1, E4, E5, §3/§4 numbers
- `data_dictionary.md` — E1, E2, E3, `(PT)` tag
- `rulebook.md` — RB-ESC-01 evidence corrected (1–5 reserved slots, 0–6 demand)
- `../evaluation/mock_data_spec.md` — sizing table corrected (46 workers, ~296 elders, 0–6 demand)
