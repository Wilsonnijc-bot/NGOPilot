# Data Dictionary — Fields, Codes and Vocabularies

**Status:** v0.1 · Companion to `excel_semantics.md` (layout/purpose) — this file defines every field and code value an importer must handle.
**Legend:** `[C]` confirmed · `[I]` inferred · `[U]` unknown/needs clarification.

---

## 1. Service / duty code vocabulary

Codes as they appear in cells of 恆常服務, HC 時間表 and 護送個案總表. `canonical_code` is what the system stores (see `canonical_schema.md#servicetype`).

| Raw code | Canonical | Meaning | Skill-gated? | Gender-gated? | Exclusive-bound? | Evidence |
|---|---|---|---|---|---|---|
| `E+RO` | `EX_RO` | Home exercise + rehab training visit (運動訓練). Expansion of E/RO letters `[U]` — likely Exercise + Range-of-motion `[I]` | Yes — designated workers only `[C]` (PDF R-1) | Follows elder requirement `[I]` | **Yes** `[C]` "佢哋會專屬去教佢哋嘅動作", cancel-don't-replace | dominant cell type in division sheet |
| `E` | `EX` | Exercise-only variant `[I]` | as E+RO | — | as E+RO `[I]` | `E：Y慧(IH)`, skill matrix row `E+RO` |
| `RO` | `RO` | Rehab/passive exercise only `[I]` | as E+RO `[I]` | — | `[U]` | `RO:Do(HSS)`, `RO:W棠(HSS)`, `RO:T運(IH)` |
| `HC` | `HC` | Home cleaning (家居清潔) | Yes `[C]` | No `[I]` | Sometimes (`只要娥姐`) `[C]` | own monthly workbook; orange fill |
| `PC` | `PC` | Personal care (個人護理 — 洗腳 etc.) | Yes `[C]` (nursing-type skill) | **Yes** `[C]` (PDF R-2 body-contact) | Case-fixed worker in samples `[I]` | `PC:Ｌ容`, `PC+E:C蓮`, skill row `PC` |
| `B` | `BATH` | Bathing service (沖涼/洗澡) | Yes `[C]` | **Yes** `[C]` | Case-fixed in samples `[I]` | `B:Y美(EH)(六1長周)`, skill row `B` |
| `ESC` (yellow cell) | `ESC_SLOT` | Escort **capacity slot** — worker reserved for escort duty; concrete case assigned weekly | Escort-capable `[C]`; nearly all can `[C]` "陪診都係有冇人…就係分性別啫" | **Yes, by elder/case** `[C]` | Preference notes occur (`盡量安排嫦`) `[C]` | bright-yellow cells |
| `Esc:` | `ESC` | Concrete escort assignment (named elder) | as above | as above | see remarks | `Esc:AY娟(IH)` |
| `D` | `MEAL` | Meal delivery (送飯) | No skill gate — "任何人可做" `[C]` — but **route-qualified** `[C]` (skill matrix routes) | No `[C]` | No | orange-`D` cells; `D(明華)` names route |
| `AMC` / `MRC` / `GC` | `DUTY_AMC` / `DUTY_MRC` / `DUTY_GC` | Centre duty at the named centre | Per-centre qualification `[C]` (skill matrix `X當值+清潔`) | No `[I]` | No, but home-centre affinity `[C]` | coloured duty cells |
| `AMC+CC(主)` / `(協)` | `DUTY_AMC_CC` role=lead/assist | Combined AMC + CC duty, lead vs assist `[I]`; CC = ? `[U]` | `[U]` | — | — | 金/安妮 columns |
| `MRC 清潔` | `DUTY_MRC` role=clean | Centre cleaning duty | `[C]` skill matrix | — | — | 強/璐霖 columns |
| `(帶活動)` | role=activity_lead | Leads activity during duty | `[U]` | — | — | detail cells |
| `(派藥)` | role=medication | Medication dispensing during duty | `[U]` — plausibly certification-gated | — | — | detail cells |
| `執牌(柴灣廚房)` | `KITCHEN` | Kitchen/meal-tag duty at Chai Wan kitchen (執牌 = sorting meal tags `[I]` from admin skill rows 收飯牌/拉車分飯/執牌) | Yes `[C]` skill row | No `[I]` | No | blue cells |
| `跟車` / `中心跟車` | `VAN` | Accompanying the meal/centre van (AM/11:00/return/PM variants) | Yes `[C]` skill rows | `[U]` | No | detail cells, skill matrix |
| `特別探訪服務` | `SPECIAL_VISIT` | Special visit service | `[U]` | `[U]` | `[U]` | 薇(AMC) Mon AM etc. |
| `DECC 康雲計劃` / `康雲計劃` | `PROG_KY` | A named programme (康雲) run at/via DECC `[U what it involves]` | skill row `康云計劃` `[C]` | `[U]` | `[U]` | Wed/Sat cells |
| `電話通知服務更改` | `PHONE_NOTIFY` | Phone-notification duty (service changes) | skill row `[C]` | No | No | Sat PM cells |
| `寫飯紙+報飯數` | `MEAL_ADMIN` | Meal paperwork/count reporting | admin `[I]` | No | No | 薇(AMC) Thu |
| `清潔及維修飯車(柴灣廚房)` / `清潔飯袋` | `KITCHEN_MAINT` | Van/bag cleaning at kitchen | `[I]` | No | No | Fri/Sat cells |
| `OFF` | `OFF` | Day off (Saturday A/B rotation) | — | — | — | Sat cells for 強/璐霖 |
| `支援KLC` | `SUPPORT_KLC` | Support another site (KLC) `[U]` | skill row | `[U]` | `[U]` | skill matrix only |
| `探訪收費量血壓` | `VISIT_BP` | Paid visit / blood-pressure measurement `[I]` | skill row | `[U]` | `[U]` | skill matrix only |

**Rule of thumb for the importer:** any assignment cell not matching this vocabulary → import as `UNPARSED` with raw text, create a low-confidence `AuditItem` (never silently drop or guess).

---

## 2. Organisational unit / team codes

| Code | Where seen | Meaning | Confidence |
|---|---|---|---|
| `EH` | HC 時間表 單位; elder-unit suffix `(EH)` in division sheet; transfer log | Home-care team #1 — plausibly 改善家居及社區照顧服務 (EHCCS) | `[I]` |
| `IH` | same | Home-care team #2 — plausibly 綜合家居照顧服務 (IHCCS) | `[I]` |
| `ED` | escort 部門 | `[U]` — possibly Elderly Day care unit, or variant spelling of EH | `[U]` |
| `AMC` | everywhere | Centre 1 (transcript: Wan Chai has two centres) — activity/care centre | `[C code]`, full name `[U]` |
| `MRC` | everywhere | Centre 2 | `[C code]`, full name `[U]` |
| `GC` | everywhere | Centre 3 (North Point?) | `[C code]`, location mapping `[U]` |
| `HSS` | elder-unit suffix; escort 部門 | `[U]` — appears as a team owning elders |
| `DECC` | 康雲計劃 cells | District Elderly Community Centre | `[I]` |
| `V` suffix (`MRCV`, `GCV`, `AMCV`, `CCSV`, `(V)`) | elder unit suffixes | Elder is a member/volunteer-funded case of that centre? | `[U]` |
| `CC` | worker tags 菲菲(CC); `AMC+CC` | `[U]` — possibly day-care centre or care-worker grade |
| `HW` / `(B)` | worker tags | `[U]` — HW plausibly home-worker grade | `[U]` |
| `KLC` | skill matrix | Another service site | `[U]` |

Which physical centre is in which district (2×Wan Chai, 1×North Point `[C transcript]`) → mapping of {AMC, MRC, GC} to districts is `[U]`.

---

## 3. Workbook A · 恆常服務 — field dictionary

| Field (position) | Type | Req | Example | Notes |
|---|---|---|---|---|
| Worker name (R2, per column) | string nickname + `(TAG)` | ✔ | `匯珠(HW)` | Header fill = active/departed status `[I]` |
| Weekday (col A merged) | enum 一–六 | ✔ | `三` | Sat block = `六 更新版` |
| Period (col B merged) | enum 上/下 | ✔ | `上` | |
| Assignment cell | code grammar (§1) | opt | `E+RO:Y容(EH)` | empty = unassigned/free `[I]` |
| — elder ref | masked name + `(unit)` | with field codes | `Y容(EH)` | join key: masked name `[U reliability]` |
| — HC week pattern | `(1,3)` etc. | HC only | `HC:C蓮(IH) (3)` | vocabulary §5 |
| Detail cell | time/district/manager | opt | `9:00-10:30(筲箕灣)倩兒` | trailing name = case manager `[I]` |
| — time | `H:MM-H:MM` or bare time | opt | `13:00:00` | bare time = start only `[I]` |
| — district | `(district)` | opt | `(柴灣)` | vocabulary §6 |
| Working hours (R108) | `H:MM-H:MM` per worker | ✔ | `8:30-17:30` | differs per worker `[C]` |
| Sat team (R93) | `A : names` / `B : names` | opt | `A : 春，家偉` | semantics `[U]` |
| Cell comment | free text | opt | `6/3 開始改時間` | effective-dated changes |

## 4. Workbook B · HC 時間表 — field dictionary

| Field | Type | Req | Example | Validation / traps |
|---|---|---|---|---|
| `Case` | masked elder name; optional `CODE:` prefix in 其他服務 | ✔ | `Y珍`, `B:Y美` | full names appear in footnotes |
| `單位` | enum EH/IH (+HSS seen once) | ✔ | `IH` | |
| `節數` | week pattern (§5) | ✔ | `1,3` | **may be Excel-mangled into a date** — `2024-01-05` ⇒ `1,5` `[I]`; import must un-mangle & flag |
| `時間` | weekday-digit+period | ✔ | `四下` | `一`–`六` × `上/下` |
| `照顧員` | worker nickname(s) | ✔ | `娥`, `寶芝/娥` | `/` = alternatives `[U]` |
| `日期` | date | usually | `2026-05-07` | blank = untracked/weekly case `[I]` |
| `更改後日期/下次日期` | free text | opt | `只要娥姐`, `16:00-17:30`, `BL` | multi-purpose exception channel; `BL` `[U]` |

## 5. Week-pattern vocabulary (節數)

| Raw | Canonical `week_pattern` | Meaning | Confidence |
|---|---|---|---|
| `1` / `2` / `3` / `4` / `5` | `W1`… | week N of month | `[C]` |
| `1,3` / `2,4` / `1,5` | `W1,W3`… | listed weeks of month | `[C]` |
| weekly (implied by presence in division sheet without pattern) | `WEEKLY` | every week | `[I]` |
| `單月` / `雙月` | `ODD_MONTH` / `EVEN_MONTH` | odd/even calendar months | `[C]` (footnote `雙數月份/單數月份`) |
| `1長周` | `W1_LONG` | `[U]` "long week" — possibly months where that weekday occurs 5 times | `[U]` |
| `三2` (in `HC: B森(IH)(三2)`) | weekday=三, `W2` | weekday embedded in pattern | `[I]` |
| Excel dates (`2024-01-05`) | un-mangle → `W1,W5` | corruption artifact | `[I]` — always flag for review |

Open issue `[U]`: is "week of month" defined by ISO week, by counting occurrences of that weekday (1st Monday, 3rd Monday…), or by the NGO's own week grid (the HC sheet's Week1–5 columns suggest occurrence-counting)? Default assumption: **k-th occurrence of the weekday in the month** — must be confirmed.

## 6. District / location vocabulary (from detail cells & routes)

Observed districts (service area = Hong Kong Island north-east belt `[C]`): 灣仔, 銅鑼灣, 跑馬地, 天后, 炮台山, 北角, 鰂魚涌, 太古/太古城, 康怡, 康山, 西灣河, 太安樓, 筲箕灣, 愛蝶灣, 杏花邨, 柴灣, 小西灣, 環翠邨, 興華邨, 峰華邨, 明華(大廈), 興民邨, 樂翠臺, 健康村, 勵德(邨), 南豐, 海怡, 鴨脷洲, 西環, 新翠. Estates/buildings and districts are mixed in one channel — the canonical model stores `district` + optional `estate` and a lookup table maps estate→district `[I]`.

Meal routes (route-qualification units) `[C from skill matrix]`: 灣仔1, 灣仔2, 灣仔3, 鰂+西+太古, 筲箕灣, 柴灣1, 柴灣2, 小西灣, 香, 丘, 勵德, 雪華, 寶珍.

Escort destinations (gazetteer needed `[U]`): PY/PYNEH?, PYNED, QM (瑪麗), RH (律敦治), TSK (鄧肇堅), F, 貝夫人, 東華東院, 東區醫院/東區尤德, 大口環, 鄧志昂, 灣仔診所, 西灣河普通科門診, 筲箕灣門診, private clinics, banks, supermarkets.

## 7. Workbook C · 護送個案總表 — field dictionary

| Field | Type | Req | Example | Validation / traps |
|---|---|---|---|---|
| `日期` (A, merged/day) | date (formula from driver cell) | ✔ | 2026-01-08 | read resolved values; merged = fill-down |
| weekday (B) | 週一–週日 | ✔ | `週四` | redundant; cross-check |
| `上/下午` (C) | 上午/下午 | ✔ | `上午` | pre-created empty rows exist; demand 0–6 per half-day observed (Jan: 111 requests; hist 1×8, 2×10, 3×12, 4×9, 5×1, 6×1) |
| `姓名` | masked elder name | ✔ for a request | `H娥` | inconsistent masking |
| `部門` | enum ED/IH/AMC/GC/HSS | ✔ | `ED` | §2 |
| `應診時間` | time | usually | `10:15` | traps: `10:00前`, `02:30` meaning 14:30 in a PM row |
| `目的地` | free text | ✔ | `PY` | gazetteer §6 |
| `科目` | free text | opt | `骨科` | blank for errands |
| `交通工具` | free text | opt | `的士來回` | mixed modes possible |
| `備註` | free text | opt | `提早一小時接長者` | **contains constraints**: lead time, fasting, equipment, worker preference (`建議安排菲菲陪診`) — extract patterns, keep raw |
| `經手人` | nickname(s) | opt | `嫦 / Bowie` | request handler, **not** assigned escort `[I]` |
| `填寫日期` | messy date | opt | `30oct2025` | tolerant parse, keep raw |
| `已檢查(ü)` | flag | opt | — | unused in sample |
| Bottom section `取消/更改覆診資料` | change-log rows | — | — | same columns + `取消/更改`; empty in sample |

## 8. Workbook A · 個案轉移紀錄 — field dictionary

| Field | Type | Notes |
|---|---|---|
| `個案名稱` | **full real name** | privacy: must be pseudonymised on import |
| `所屬單位` | EH/IH | |
| `個案經理` / `更改個案經理` | nickname | `/` = unchanged |
| `原訂照顧員` / `更改照顧員` | nickname | `(TBC)` = tentative |
| `原訂服務日期` / `更改服務日期` | weekday text | `星期三` |
| `原訂服務時間` / `更改服務時間` | time range text | `09:00-10:30`, `4:00-5:30(待定)` |
| `生效日期` | date **or fuzzy text** | `2025-03-24` or `待定(9月?)` — keep raw + parsed nullable date |

## 9. Workbook A · 新同工跟服務紀錄表 — field dictionary

| Field | Type | Notes |
|---|---|---|
| Column header | `nickname(join-date 入職)` | join date formats vary (`25/10/21`, `8/11/2021`) |
| Row group (col A) | 送飯/跟車/行政工作/當值/服務 | category of work item |
| Row item (col B) | work item (§1, §6 routes) | |
| Cell | `v` / blank | `v` = shadowed/qualified `[C]`; blank ≠ proven-unqualified `[U]` |

## 10. People registries (as reconstructable today)

- **Workers (46 named columns C…AX, gaps at G/AQ; ~50 claimed):** only nickname + tag + working hours + implicit skills/assignments. Tags seen: HW, CC, AMC, MRC, (B), **(PT)** `[U — part-time?]`. **Gender is nowhere** — must be requested (blocking for gender constraints). Columns AY/AZ/BA are aggregate counters (`個案數量`: E+RO vs Esc per session 1, E+RO vs D per session 2; `總數`), not workers. ~11 case managers / clerical staff appear only in detail cells (倩兒, Tiffany, Wing, 康*, 梓毅, Rebecca, Carol, Skylar, 嘉偉*, 重情, Korie, Croseby, Mavis, Bowie, Jan…; * = names that also appear as care workers — role ambiguity `[U]`).
- **Elders (~296 distinct visible: 278 aliases in division-sheet assignment cells + 18 escort-only names `[C count]`; ~400 claimed):** masked name + unit + district (via detail cells) + service needs (via assignments). Gender, address, exact IDs `[U]`.
