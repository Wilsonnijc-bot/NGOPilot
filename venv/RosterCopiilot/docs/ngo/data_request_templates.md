# NGO Data Request Templates 資料收集模板

**Status:** living template definition · Five Excel templates for the NGO to
fill. This Markdown defines their columns; generated `.xlsx` files are delivery
artifacts. Every column maps to `../spec/canonical_schema.md`. Pre-fill what can
be extracted safely so the NGO only corrects and completes missing facts.

---

## Template 1 — Employee skill table 員工技能表 → `Employee`, `WorkerSkill`, `WorkerRouteQualification`

One row per worker (~50 rows pre-filled with extracted aliases).

| Column | 欄名 | Values | Maps to |
|---|---|---|---|
| A | 編號 (系統) | W001… (pre-filled) | Employee.id |
| B | 花名/簡稱 | pre-filled from roster headers | display_alias |
| C | 性別 | 男/女 | gender **(blocking)** |
| D | 所屬隊伍 | EH/IH/AMC/MRC/GC/其他 | home_team |
| E | 上班時間 | e.g. 8:30-17:30 (pre-filled from R108) | work_start/end |
| F | 星期六更 | A / B / 不返 | works_saturday_team |
| G | 全職/兼職 | 全/兼(時數) | employment_type |
| H–N | 技能: 送飯 / 護送 / 家居清潔 / 洗腳沖涼(PC/B) / 運動訓練(E+RO) / 中心當值(AMC) / (MRC) / (GC) | ✓ / ✗ / 學緊 | WorkerSkill |
| O | 可帶活動? 可派藥? | ✓/✗ each | duty roles |
| P–…| 送飯路線: 灣仔1 / 灣仔2 / 灣仔3 / 鰂+西+太古 / 筲箕灣 / 柴灣1 / 柴灣2 / 小西灣 / 香 / 丘 / 勵德 / 雪華 / 寶珍 | ✓/✗ | RouteQualification |
| last | 備註 (如「不可加Case」等限制) | free text | overrides |

## Template 2 — Elder service requirement table 長者服務需要表 → `Elder`, `FixedService`

One row per elder-service (pre-filled ~480 rows from the division sheet + HC sheet).

| Column | 欄名 | Values | Maps to |
|---|---|---|---|
| A | 編號 (系統) | E0001… | Elder.id |
| B | 稱呼 (現用代號) | pre-filled e.g. Y珍 | display_alias |
| C | 所屬單位 | EH/IH/ED/中心會員 | owning_unit |
| D | 性別 | 男/女 | gender **(blocking)** |
| E | 地區 | 灣仔/北角/… (pre-filled where known) | district |
| F | 屋苑/大廈 (可選) | e.g. 勵德邨 | estate |
| G | 服務 | E+RO/HC/PC/沖涼/送飯/護送 | FixedService.service_code |
| H | 星期幾 + 上/下午 | e.g. 四下 | weekday/period |
| I | 時間 | e.g. 14:00-15:30 | start/end |
| J | 節數 | 逢週/1,3/2,4/單月/… | week_pattern |
| K | 指定照顧員 | pre-filled | assigned_worker |
| L | **只可以佢 / 最好係佢 / 邊個都得** | 圈一個 | is_exclusive + strength |
| M | 性別要求 | 要同性/要女/要男/冇 | gender_requirement |
| N | 備註 | free text | notes |

## Template 3 — Service code dictionary 服務代號字典 → `ServiceType`

Pre-filled with every code we found; NGO corrects the blanks.

| Column | 欄名 | Example row |
|---|---|---|
| A | 代號 (照表格寫法) | `E+RO` |
| B | 全名/意思 | ＿＿＿ (請填) |
| C | 邊個做得 | 指定同事/有技能同事/任何人 |
| D | 分唔分性別 | 分/唔分/視乎長者 |
| E | 同事請假時 | 取消/搵人代/改期 |
| F | 佔幾耐 | 一節(1.5h)/半日/全日 |
| G | 優先次序 (1最緊要) | ＿ |
| H | 備註 | |

Rows pre-filled: E+RO, E, RO, HC, PC, B, ESC, D, AMC/MRC/GC當值, AMC+CC(主/協), 執牌(柴灣廚房), 跟車(各種), 派藥, 帶活動, 特別探訪服務, 康雲計劃, 電話通知服務更改, 寫飯紙+報飯數, 清潔飯袋, MRC清潔, 支援KLC, 探訪收費量血壓, **加: 我哋唔識嘅代號一覽 (長周/BL/半張紙/香/丘/雪華/寶珍/HW/CC/(B)/(V)/ED/HSS)** — 請解釋.

## Template 4 — Centre duty rules table 中心當值規則表 → `CenterDutyRequirement`

One block per centre; rows = weekday × 上/下午 (pre-filled with counts we observed — please correct to what is *required*).

| Column | 欄名 | Values |
|---|---|---|
| A | 中心 | AMC/MRC/GC |
| B | 星期 | 一…六 |
| C | 上/下午 | |
| D | 需要人數 (總) | number |
| E | 其中: 帶活動 / 派藥 / 清潔 / 主 / 協 | numbers |
| F | 最少人數 (低過呢個要即刻通知) | number |
| G | 邊啲同事優先 (熟手) | names |
| H | 輪換要求 | 按日/按週/平均就得 |
| I | 備註 (e.g. MRC 星期六照開?) | |

## Template 5 — Real change case examples 真實變動例子 → benchmark validation

The transcript promised "俾我們幾個case" — this template captures them so our benchmarks replay reality. Please give **5–10 recent real cases**:

| Column | 欄名 | Example |
|---|---|---|
| A | 日期 | 2026-05-12 |
| B | 發生咩事 | 娥上午請假 / 陳婆婆入院 / 當日多咗個護送 |
| C | 幾時知 | 前一日 5pm / 當日朝早 |
| D | 影響咗邊啲服務 | Y珍 HC(一上), L明護送… |
| E | 你哋當時點改 | HC取消; 護送改咗俾嫦; 嫦原本當值由金補 |
| F | 有冇通知邊個 | 長者屋企人 / 同事群組 |
| G | 用咗幾耐時間處理 | 45分鐘 |
| H | 如果系統幫手, 你最想佢做咩 | 自動搵到金補當值 |

Column E is the gold standard our rescheduler is scored against; column G quantifies the time-saving claim; column H is free product research.

---

### Handling notes
- Templates are pre-filled from extracted data with low-confidence cells shaded amber (matching source ambiguity items) — the NGO corrects shaded cells first.
- Returned files should update the scheduler snapshot/config. The existing workbook import API can help with development fixtures, but it is not the normal product workflow.
- Templates never contain real elder names; the NGO may key rows by their own codes (Q-D6 answer decides the alias regime).
