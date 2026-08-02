# Excel Semantics — Reverse Engineering of the NGO Workbooks

**Status:** v0.1 · Derived from the three workbooks in `docs/`, the meeting transcript (`docs/transcript.docx`), and `docs/wan chai requirements.pdf`.
**Legend:** `[CONFIRMED]` = directly observable in the files or stated in the transcript · `[INFERRED]` = strongly implied by structure/patterns · `[UNKNOWN]` = cannot be reliably inferred, listed in `../ngo/clarification_packet.md`.

The NGO is 循道衛理中心 社區照顧服務 (Methodist Centre, Community Care Service — title of the division sheet). It operates **five teams** `[CONFIRMED in transcript]`: three physical centres (2 in Wan Chai, 1 in North Point) plus two home-care service teams; ~50 front-line care workers serve ~400 elders per week, Mon–Sat, with the weekly roster published every Friday for the following week.

---

## 1. Workbook A — `照顧員工作分工表2026(HKU).xlsx` (Care Worker Work Division Table)

The **master weekly roster template**. This is the artifact the transcript calls "分工表" and the one the NGO most wants automated.

### 1.1 Sheet `恆常服務` (Regular Services)

| Aspect | Assessment |
|---|---|
| Business purpose | The recurring weekly template: which worker does what, every weekday AM/PM, plus Saturday | 
| I/O role | **Input** (fixed commitments per worker) **and Output template** (the published roster keeps this exact layout) — it is both the database and the report |
| Entities extractable | Employee (columns), FixedService (E+RO/HC/PC/B cells), CenterDutyRequirement (AMC/MRC/GC cells), EscortSlot placeholders (ESC cells), MealRouteDuty (D cells), KitchenDuty (執牌), WorkerAvailability (hours row, OFF, A/B weeks) |
| Parse confidence | **Medium.** The cell grammar is regular enough to parse ~90% of cells; the remaining ~10% are free-text notes, transition annotations, and one-off duties |

**Layout `[CONFIRMED]`:**

- **R1**: title + `星期一至五(每日8小時)` (Mon–Fri, 8h/day).
- **R2**: one column per worker — **46 named worker columns across C…AX** (empty gap columns at G and AQ), plus three **aggregate counter columns AY/AZ/BA (`個案數量` / `總數`)** that are *not* workers: per session they count E+RO cases vs Esc cases (session 1) or E+RO vs D cases (session 2), e.g. Mon AM session 1 = 14 E+RO + 4 Esc = 18. Header format: `Name(TAG)` — e.g. `輝(HW)`, `菲菲(CC)`, `鳳(AMC)`, `強(MRC)`, `志明(B)(HW)`, `梅欽(PT)` (PT = part-time? `[U]`). Header fill colour: **yellow = active worker; gray (`FFD8D8D8`/`FF999999`/`FFD9D9D9`) = departed / departing / post in transition** `[INFERRED]` — gray columns (`文健`, `添`, `強`, `璐霖`, `健忠`, `安妮`) contain handover notes like `轉家偉做`, `6/12 轉文偉`, `轉文偉TBC`. *(Fact-check E1: an earlier revision of this document said 37 columns — the extraction had capped at column 40 and missed 志豪, 香, 秀英, 娥, 嘉文, 熙仔(MRC), 梅欽(PT), 奕倫, 炎萍.)*
- **Column A** (merged blocks): weekday `一`…`六`. Saturday block is labelled `六 更新版` ("updated version").
- **Column B** (merged blocks): period `上`/`下` (AM/PM).
- **Within each half-day block, each worker column holds up to 2 session slots**, each slot spanning a *pair of rows*:
  - Row 1 of the pair: the **assignment cell** — service code + case + unit, e.g. `E+RO:Y容(EH)`, `HC:C蓮(IH) (3)`, `AMC`, `ESC`, `D`, `執牌(柴灣廚房)`.
  - Row 2 of the pair: the **detail cell** — time range, district, responsible case manager, e.g. `9:00-10:30(筲箕灣)倩兒`, `(派藥)`, `13:00:00`.
  - Canonical session times `[INFERRED from repetition]`: AM session 1 ≈ 8:30–10:30, AM session 2 ≈ 11:00–12:30, PM session 1 ≈ 14:00–15:30, PM session 2 ≈ 16:00–17:30. Deviations are written explicitly in the detail cell.
  - Occasional extra rows within a block hold a 3rd item or worker-specific notes (`8:30-12:30`, `(轉家偉做)`).
- **R93** `[INFERRED]`: per-worker Saturday rotation team membership. Two formats coexist: bare letter (`A` / `B`, columns AO–AX) and letter + names (`A : 春，家偉` / `B：少芬、玉`). The letter is the worker's team; **the meaning of the appended names (partner list vs. covered-by list) is `[UNKNOWN]`.**
- **Stacked alternating-week cases** `[CONFIRMED, fact-check E5]`: one worker-session slot can hold several cases with *disjoint* week patterns — e.g. 炎萍 Mon AM lists `HC: F玲(EH)(1)` and `HC: Y芬(EH)(3)` in adjacent rows of the same slot (week-1 and week-3 cases sharing the slot). Importer and slot model must allow N pattern-cases per (worker, weekday, period, session) with disjoint patterns.
- **R94–R107**: Saturday roster (alternating by A/B week — `OFF` appears for some workers; `電話通知服務更改` phone-notification duty appears Sat PM).
- **R108** `[CONFIRMED]`: per-worker daily working hours, e.g. `8:30-17:30`, `9:00-17:00`. Not uniform. Annotations: `(7小時)`, `(云一人做)`, `(HC：少0.5小時)` (HC counts 0.5h less — meaning `[UNKNOWN]`).
- **R109–110**: `A: D=7` / `B: D=7` — `[INFERRED]` 7 meal-delivery slots on Saturday per rotation team; exact meaning `[UNKNOWN]`.

**Cell grammar `[CONFIRMED by pattern]`:**

```
assignment_cell := center_duty | field_service | slot_placeholder | other_duty
center_duty     := ("AMC"|"MRC"|"GC") [" "time] ["(帶活動)"|"+CC(主)"|"+CC(協)"|" 清潔"|"(派藥)"|"(協)"]
field_service   := code ":" elder_name "(" unit ")" [" (" week_pattern ")"] [note]
code            := "E+RO" | "E" | "RO" | "HC" | "PC" | "PC+E" | "B" | "Esc"
slot_placeholder:= "ESC"          # escort capacity slot, elder filled weekly
other_duty      := "D" ["(route)"] | "執牌(柴灣廚房)" | "跟車" | "派藥" | "特別探訪服務"
                 | "DECC 康雲計劃" | "康雲計劃" | "電話通知服務更改" | "OFF"
                 | "清潔及維修飯車(柴灣廚房)" | "清潔飯袋(柴灣廚房)" | "寫飯紙+報飯數"
detail_cell     := [time_range] ["(" district ")"] [case_manager] | "(" annotation ")" [time]
```

**Fill-colour semantics `[INFERRED from colour census, corroborated by transcript "黃色的就是空的浮動的"; the transcript also says colours mark the different centres]:**

| Fill (ARGB) | Count | Meaning |
|---|---|---|
| `FFF4CCCC` light red | 304 | E+RO home exercise visits |
| `FFD9EAD3` light green | 162 | MRC centre duty |
| `FFFFE599` gold | 133 | AMC centre duty |
| `FFA4C2F4` light blue | 50 | GC centre duty |
| `FFF9CB9C` light orange | 85 | `D` meal delivery |
| `FFFFFF00` bright yellow | 58 | **`ESC` floating escort slots** — the cells re-filled every week |
| `FF9FC5E8` blue | 49 | 執牌 kitchen duty (Chai Wan kitchen) |
| `FFFF9900` orange | 17 | `HC` home cleaning (has week patterns) |
| grays | ~150 | departed/transitioning workers, structural headers |
| `FF00FFFF` cyan | 3 | **incomplete cells** (e.g. `HC:` with no case) — low-confidence data |

Colour is therefore a *semantic channel*: the importer must read fills, and the exporter must reproduce them (see `excel_io_contract.md`).

**Embedded facts that are data, not formatting `[CONFIRMED]`:**
- Exclusivity notes: `只要娥姐` ("only wants 娥"), `不可加Case` ("no more cases may be added" — a per-worker-slot capacity lock on 嫦 Tue AM).
- Transition notes: `E+RO:李長康(11月開始轉家偉做)`, `(轉文偉TBC)` — pending case transfers with effective dates, duplicating the 個案轉移紀錄 sheet.
- A cell comment (`F48: '6/3 開始改時間'`) — schedule change effective dates live in comments too.
- Some elder names are **full real names** (胡兆榮, 李長康, 吳瑞聰, 曹濟群, 雷瑞榮, 麥鈞枋, 鄭功秀, 譚德耀, 李定) while most are masked (`Y容`) — masking is inconsistent; privacy handling must not assume it.

**What cannot be reliably inferred `[UNKNOWN]`:**
- Worker gender (never recorded anywhere in the three workbooks).
- Worker full IDs (only nicknames).
- Meaning of worker header tags: `HW`, `CC`, `(B)`, `AMC`, `MRC` — plausibly team/attachment markers (HW=home worker, AMC/MRC=centre attachment) but unverified.
- Required headcount per centre per period (must be counted from occurrences, but we cannot distinguish "required" from "happens to be assigned").
- Whether the two sessions inside a half-day are hard slots or just conventional times.
- Full semantics of `AMC+CC(主/協)` (lead/assist a combined duty? CC = day-care centre?), `康雲計劃`, `執牌`, `特別探訪服務`.
- Which weekday block variant applies during public holidays.

### 1.2 Sheet `個案轉移紀錄_2025` (Case Transfer Log 2025)

| Aspect | Assessment |
|---|---|
| Business purpose | Audit log of case reassignments between workers (e.g. when worker 娟 left, her 8 cases were re-homed) |
| I/O role | **Audit log** (append-only record) |
| Entities | CaseTransfer events → our `ManualOverride`/`AuditItem` ancestors |
| Parse confidence | **High** (flat table) |

Columns `[CONFIRMED]`: `#`, `個案名稱` (elder, **full real name**), `所屬單位` (EH/IH), `個案經理` (case manager), `更改個案經理`, `原訂照顧員` (original worker), `更改照顧員` (new worker, often `X(TBC)`), `原訂服務日期` (weekday), `更改服務日期`, `原訂服務時間`, `更改服務時間`, `生效日期` (effective date — may be fuzzy text like `待定(9月?)`).

Notable: `/` means "unchanged"; `TBC` states tentative decisions; effective dates can be non-dates. This sheet proves the NGO already *thinks* in terms of change events with before/after values — our `AuditItem` schema mirrors it deliberately.

### 1.3 Sheet `新同工跟服務紀錄表` (New Staff Service-Shadowing Record)

| Aspect | Assessment |
|---|---|
| Business purpose | Onboarding/skill acquisition matrix: which new worker has been trained on (跟 = shadowed) each work item |
| I/O role | **Reference table** → source of `WorkerSkill` and `WorkerRouteQualification` |
| Parse confidence | **High** (tick matrix), but only covers 6 new staff, not all 50 |

Rows are work items grouped by category `[CONFIRMED]`:
- `送飯` routes: 灣仔1, 灣仔2, 灣仔3, 鰂+西+太古, 筲箕灣, 柴灣1, 柴灣2, 小西灣, 香, 丘, 勵德, 雪華, 寶珍 — **meal delivery is route-qualified, not just skill-qualified.** (香/丘/雪華/寶珍 look like building or elder-cluster names `[INFERRED]`.)
- `跟車`: 上午跟車, 11:00跟車, 跟車回程, 下午跟車, 送樹祥回家 (named one-off).
- `行政工作`: 半張紙, 收飯牌, 拉車，分飯, 執牌, 電話聯絡跟車, 電話通知服務更改.
- `當值`: AMC當值+清潔, MRC當值+清潔, GC當值+清潔, MRC換片(保健員教), MRC PC(OT Coaching), 接長者 — **centre duty is per-centre qualified.**
- `服務`: 探訪收費量血壓, E+RO, PC, B, HC, ESC, 康云計劃, 支援KLC.

Columns: worker nickname + join date (e.g. `業(25/10/21入職)`). Value `v` = qualified/shadowed; blank = not (or not yet recorded — **absence is not reliable evidence of inability** `[UNKNOWN]`).

---

## 2. Workbook B — `2026_HC 時間表(HKU).xlsx` (HC = Home Cleaning Timetable)

Single sheet named `52026` = **May 2026** `[INFERRED from R1 "5月" and dates]`. One sheet per month is the presumed convention; the transcript confirms HC dates are (painfully) hand-planned month by month ("每個月去定一個日子 … 好痛苦啊").

| Aspect | Assessment |
|---|---|
| Business purpose | Expand recurring HC (and a few PC/B/Esc) patterns into concrete dates for one month |
| I/O role | **Intermediate view / output** — derivable from FixedService week patterns + calendar; also carries per-month exceptions |
| Entities | FixedService (HC), week-pattern vocabulary, per-occurrence date overrides |
| Parse confidence | **Medium–low**: layout is 5 side-by-side week blocks with irregular use; several 節數 cells were mangled by Excel |

**Layout `[CONFIRMED]`:** R1 month; R2 merged `Week 1`…`Week 5` blocks (7 columns each); R3 per-block headers: `Case | 單位 | 節數 | 時間 | 照顧員 | 日期 | 更改後日期/下次日期`. Below ~R24 a section `其他服務` (other services) lists PC/B/Esc items in the same block layout.

**Column semantics:**
- `Case`: masked elder name (`Y珍`); in 其他服務 the code is prefixed: `PC:Ｌ容`, `B:Y美`, `Esc:ＡＹ娟(IH)`.
- `單位`: EH / IH (the two home-care teams `[INFERRED]`: EH = 改善家居及社區照顧服務 EHCCS, IH = 綜合家居照顧服務 IHCCS — expansion `[UNKNOWN]`, abbreviations to be confirmed).
- `節數` (week pattern): `1`, `2`, `3`, `4`, `1,3`, `2,4` = weeks of month; `1長周` `[UNKNOWN — "long week"?]`; footnote `**廖祥輝雙數月份/李巧珍單數月份` = even-month / odd-month alternation between two elders `[CONFIRMED]`. **Data corruption:** values like `2024-01-05 00:00:00` are `1,5`-style patterns auto-converted to dates by Excel `[INFERRED with high confidence]` — the importer must detect and reverse this, and flag for review.
- `時間`: weekday-digit + period, e.g. `一上` = Mon AM, `四下` = Thu PM. Occasionally an explicit range appears in `更改` instead (`8:30-10:00`).
- `照顧員`: worker nickname; `寶芝/娥` = either/both `[UNKNOWN]`.
- `日期`: planned concrete date for that week's occurrence. Sometimes blank (e.g. rows also present in the weekly division sheet — T嫻 has no dates).
- `更改後日期/下次日期`: free-text exception channel — new date, time override (`16:00-17:30`), exclusivity (`只要娥姐`), `單月`, `BL` (`[UNKNOWN]`).

**What cannot be inferred:** why some HC cases live here but not in the division sheet and vice versa; what happens when a pattern week has a public holiday; whether `日期` is authoritative over 節數 when they disagree.

---

## 3. Workbook C — `護送個案總表(2026)(HKU).xlsx` (Escort Case Master Table)

Single sheet `1月` (January) — one sheet per month `[INFERRED]`. This is the "浮動最大的" (most floating) table per the transcript; requests arrive ~≤1 week ahead via Teams messages and are typed in here.

| Aspect | Assessment |
|---|---|
| Business purpose | Collect every escort/accompaniment appointment (medical visits, banking, shopping) per day and half-day |
| I/O role | **Input** (demand) + operational log; bottom section is a **change/cancellation audit log** |
| Entities | EscortRequest, ServiceCancellationEvent (bottom section), implicit worker-preference constraints in remarks |
| Parse confidence | **High** for the main grid; **low** for constraint extraction from free-text 備註 |

**Layout `[CONFIRMED]`:**
- R3 title + a single **driver cell** `2026-01-01` annotated `<- 只需改此格日期` ("only change this cell") → dates in column A are formula-derived from it.
- R5 headers: `日期 | (weekday) | 上/下午 | 姓名 | 部門 | 應診時間 | 目的地 | 科目 | 交通工具 | 備註 | 經手人 | 填寫日期 | 已檢查(ü)`.
- Column A/B merged per calendar day (including Sat/Sun rows that stay mostly empty); column C = 上午/下午. Empty AM/PM rows are pre-created for every day.
- **Demand per half-day observed: 0–6 requests** (January census: 111 requests; histogram 1×8, 2×10, 3×12, 4×9, 5×1, 6×1) — the transcript's "baseline 4, fluctuates 2–5" **understates the observed peak of 6** (fact-check E2).
- Bottom section from R148: `取消 / 更改覆診資料` with headers `覆診日期 | 姓名 | 部門 | 應診時間 | 目的地 | 科目 | 交通工具 | 取消/更改 | 經手人 | 填寫日期` — the escort change log (empty in the sample except an `e.g.` row).

**Column semantics:**
- `姓名`: masked elder name (`H娥`), occasionally full (`T曉霖`, `AY麗娟`) — inconsistent masking again.
- `部門`: elder's owning team — observed values `ED`, `IH`, `AMC`, `GC`, `HSS` `[CONFIRMED as codes; meaning of ED and HSS `[UNKNOWN]`; note EH appears in other workbooks but not here — is ED≡EH?]`.
- `應診時間`: appointment time. Mostly real times; data-quality traps observed: `10:00前` (before 10:00), `02:30:00` meaning 14:30 `[INFERRED from PM row]`.
- `目的地`: destination, heavily abbreviated — `PY` (律敦治/鄧肇堅? more likely 東區尤德夫人那打素醫院 = PYNEH; `PYNED` also appears), `QM` (瑪麗醫院), `RH` (律敦治醫院), `TSK` (鄧肇堅醫院), `F`, `貝夫人` (violet Peel?), free-text private clinics. **Destination gazetteer is `[UNKNOWN]` and needed for travel-time optimization.**
- `科目`: specialty/purpose (內科, 骨科, 抽血, 銀行事務, 購物, 領取物資…). Blank for non-medical escorts.
- `交通工具`: 的士來回, 巴士來回, 小巴, 愛心小巴, 易達巴, 步行來回, MTR, 輪椅來回, mixed (`的士去/回程小巴+MTR`).
- `備註`: free text carrying **real scheduling constraints**: pickup lead time (`提早一小時接長者`), fasting flags, equipment (`帶備鞋套`, `中心借輪椅`), sequencing (`覆診完成後先回家才繼續下午覆診`), and **worker binding/preference**: `建議安排菲菲陪診`, `盡量安排照顧員嫦陪診(有關藥物)`, `安排啊茵`, `照顧員:匯珠代購`.
- `經手人`: handler(s), usually `care worker / clerical staff` pairs — evidence of who took the request, not who escorts `[INFERRED]`.
- `填寫日期`: request logging date. Formats wildly inconsistent: real dates, `21/10/2025`, `30oct2025`, `2025/8/1` — parse with a tolerant date parser, keep raw string.
- `已檢查(ü)`: checked flag (column exists; unused in sample).

**What cannot be inferred:** whether an escort occupies the worker's whole half-day or a time window (transcript implies whole half-day slots via the 4-slot baseline `[INFERRED]`); the gender requirement (never explicit — only derivable from elder gender + service type, both absent here); how the 4/period baseline maps to specific workers (the division sheet's yellow `ESC` cells show *which workers* hold escort capacity on each weekday/period `[INFERRED]`).

---

## 4. Cross-workbook consistency observations

1. **Join keys are nicknames.** Workers appear as column headers (division sheet), 照顧員 (HC sheet), 經手人 (escort sheet), 原訂照顧員 (transfer log) — always nicknames; elders as masked names, inconsistently. There is **no shared ID system**; entity resolution must be built and human-verified (see `excel_io_contract.md` §6).
2. **The same fact lives in ≥2 places** (HC cases appear in both the division sheet and HC timetable; transfers in both the transfer log and inline notes). The canonical model must pick one source of truth per fact and treat the rest as views.
3. **Free text is a constraint channel.** Exclusivity, pickup lead times, capacity locks (`不可加Case`) and effective-dated changes are all embedded in notes/comments. The importer surfaces every unparsed note as a low-confidence `AuditItem` rather than dropping it.
4. **The escort baseline is visible structurally as per-slot reserved counts, not a constant 4**: bright-yellow `ESC` cells in the division sheet range **1–5 per weekday-period** (Mon AM 4, Mon PM 5, Tue AM 2 … Thu PM 1) across workers 菲菲, 燕, 志豪, 香, 芝, 偉業, 少芬, 翠君, 仲坪, 秀英, 嘉文… — the NGO pre-reserves specific workers as escort capacity, with counts varying by weekday/period `[CONFIRMED counts, INFERRED semantics]`. The AZ counter column tallies the same numbers.
5. **Both "who" and "when" change mid-year.** Gray columns, `TBC` transfers, and comment-dated time changes mean any import must be **effective-dated**, not a snapshot.
