# Clarification Packet for the NGO 澄清問題清單

**Status:** living NGO working document · unresolved answers must remain here
until confirmed, then be copied into `../spec/rulebook.md` with evidence and
confidence. Questions are bilingual and designed for quick answers.
Cross-references: rule IDs from `../spec/rulebook.md`; template definitions in
`data_request_templates.md`.

Send with: the 5 fill-in templates + the one-page privacy note (§E).

---

## A. Blocking questions 必答（未答系統無法正確排班）

**Q-A1. Worker & elder gender 同事及長者性別** (RB-GEND-01)
- *Why:* gender rules for bath/PC/escort cannot run at all — the current files never record gender. *Affects:* eligibility of every gender-sensitive assignment.
- *Ask:* please fill Template 1 (員工表) and Template 2 (長者表) gender columns.
- ☐ 已填妥模板 ☐ 部分服務其實不分性別（請註明邊啲）

**Q-A2. Full skill matrix 全體同事技能表** (RB-SKILL-01)
- *Why:* the tick matrix only covers 6 new staff; the other ~44 workers' abilities are unknown — the safe default (treat unknown as "cannot") would paralyse scheduling. *Affects:* the entire eligibility model.
- *Ask:* Template 1, one row per worker, tick each service + meal routes.
- ☐ 已填妥 ☐ 大部分同事乜都做到，只有以下例外：＿＿＿

**Q-A3. Centre duty requirements 中心當值人數要求** (RB-DUTY-01, RB-U-10)
- *Why:* we can count who *is* on duty in the sample, but not how many are *required*, per role (帶活動/派藥/清潔/主/協). Duty is your #1 priority rule, so wrong numbers = wrong everything. *Affects:* duty coverage constraint + under-coverage alerts.
- *Ask:* Template 4 (中心當值規則表): per centre × weekday × 上/下午 × role, 需要幾多人? 最少幾多人先算安全 (min)?
- ☐ 已填妥 ☐ 三間中心一樣，每半日需 ＿ 人 ☐ 另需特定證書崗位（派藥等）：＿＿＿

**Q-A4. Week-of-month definition & special patterns 節數定義** (RB-FIX-02, RB-U-06)
- *Why:* HC schedules depend on it; ambiguity = cleaning happening on the wrong week. *Affects:* HC task generation.
- "第1,3週" 係指: ☐ 該月第1、第3個「星期一」(按當日星期幾計) ☐ 月曆第1、第3行 ☐ 其他:＿＿
- 「1長周」/「BL」/「單月/雙月」確實意思: ＿＿＿

**Q-A5. Saturday A/B rotation anchor 星期六A/B更** (RB-TIME-03, RB-U-09)
- *Why:* we see teams A/B and OFF cells but not which calendar weeks are A-weeks. *Affects:* Saturday availability.
- ☐ 單數週=A、雙數週=B（ISO週）☐ 有固定日曆（請附）☐ 其他:＿＿

**Q-A6. Degraded mode 人手不足時點算** (RB-U-03)
- *Why:* when demand > supply the system must know what to drop first vs. what to escalate. *Affects:* infeasibility policy, unassigned ranking.
- 當日人手唔夠時，可接受嘅次序（1=最先犧牲）：＿送飯改期 ＿家居清潔改期 ＿E+RO改期 ＿中心當值減一人 ＿護送轉包/改期 ＿加班（如有）
- ☐ 以上都唔可以自動決定，全部要人手審批（系統只提建議）

**Q-A7. Entity master lists 名單核對**
- *Why:* nicknames/masked names collide across files; we need one authoritative list of workers and elders with stable IDs. *Affects:* all data joins.
- *Ask:* Templates 1 & 2 serve as the master lists; please confirm every alias we extracted (we will send the extracted list for ticking).

## B. Important optimization-quality questions 重要（影響排得好唔好）

**Q-B1. Priority within home services** (RB-PRIO-01): 中心當值 > 護送 之後，E+RO / HC / PC / 沖涼 / 送飯 / 執牌 / 跟車 嘅先後次序? 請排序: ＿＿＿
**Q-B2. Daily capacity** (RB-U-01): 每半日最多幾多個任務? 上下午之間要唔要預留午膳 (13:00–14:00)? ☐ 要,全體 ☐ 視乎崗位 ☐ 唔使
**Q-B3. Duty rotation granularity** (RB-U-02): 當值輪換係 ☐ 按日 ☐ 按週 ☐ 冇正式輪換,平均就得
**Q-B4. Travel expectations** (RB-GEO-01): 同事一日內跨區次數可接受上限? ☐ ≤1次長途 ☐ ≤2次 ☐ 冇硬性,越少越好; 護送目的地計唔計入「東奔西跑」? ☐ 計 ☐ 唔計
**Q-B5. Escort duration & chaining** (RB-ESC-08): 一個護送一般佔 ☐ 成個半日 ☐ 視乎科目(請俾平均時數:＿); 同一同事可唔可以一個半日跟兩個護送? ☐ 可以(同院) ☐ 唔可以
**Q-B6. Default pickup lead** (RB-ESC-06): 冇註明時, 提早幾耐接長者? ＿分鐘
**Q-B7. Exclusive bindings census** (RB-EXCL-01): Template 2 has a 專屬同事 column — please also mark *strictness*: 只可以佢 / 最好係佢.
**Q-B8. Fairness horizon** (RB-DUTY-02): 「平均一點」睇幾耐? ☐ 每週 ☐ 每月 ☐ 每季
**Q-B9. Preference keyword map** (RB-EXCL-03/ESC-07): 我哋將「只要X/安排X」當硬性、「建議/盡量」當彈性 — 啱唔啱? ☐ 啱 ☐ 修改:＿＿
**Q-B10. Public holidays** (RB-U-07): 公眾假期當日 ☐ 全部停 ☐ 部分服務照做(邊啲?):＿＿

## C. MVP-mockable questions 可暫時假設（請有空再答）

For each we state our default; correct us when convenient.

| # | Question | Our default |
|---|---|---|
| Q-C1 | Meaning of tags HW/CC/(B) on worker names | treat as team labels, no scheduling effect |
| Q-C2 | Full names of AMC/MRC/GC + which is in 北角 | AMC=灣仔, MRC=灣仔, GC=北角 |
| Q-C3 | ED vs EH in escort sheet 部門 | ED treated as separate day-care unit |
| Q-C4 | `(V)`/`MRCV` suffixes on elders | membership marker, no constraint |
| Q-C5 | 執牌/跟車/康雲計劃 staffing counts | as counted from sample |
| Q-C6 | Meal route time windows | AM session 2 (11:00–12:30) |
| Q-C7 | `(HC：少0.5小時)`, `A: D=7` annotations | informational only |
| Q-C8 | Case manager approval role | roster owner approves everything |
| Q-C9 | 更改後日期 vs 節數 conflicts in HC sheet | explicit date wins, flagged |
| Q-C10 | Do cancelled-service workers ever go home early instead of refill? | no — refill or idle-at-centre |

## D. Deployment / privacy questions 部署與私隱

**Q-D1. Where should the system run?** ☐ 中心一部指定電腦（我哋建議 — 資料不出中心）☐ 雲端（香港區）☐ 未定,先睇demo
**Q-D2. Real-name handling** (RB-PRIV-01): 系統內部需要對返真名先出到通知/表格。☐ 真名只存喺中心電腦（加密）☐ 連系統都唔好存真名,我哋自己對照 ☐ 其他:＿＿
**Q-D3. Google Drive**: 想唔想系統自動上載排班表到而家用開嘅Drive資料夾? ☐ 想(請俾資料夾權限) ☐ 唔想,人手上載
**Q-D4. AI usage & cost**: 每週排班本身唔使AI（零成本）。以下選用功能會產生按量費用: 訊息自動變更登記、備註自動解讀。☐ 都要 ☐ 只要第一項 ☐ 暫時唔要
**Q-D5. Who are the users?** 邊幾位同事會用個系統(出更表/審批)? 名單+角色:＿＿＿
**Q-D6. Data sharing for development**: 開發期間可否繼續用改名後嘅一個月數據? 改名規則: ☐ 跟而家(姓氏留字母) ☐ 全部代號 ☐ 由我哋提供對照表

## E. One-page privacy note (attach)

We only ever receive pseudonymised data; real names stay on your machine in an encrypted store; weekly scheduling runs fully offline with no external calls; optional AI features are off by default and never see real names. (Full text to be drafted with the NGO's wording preferences.)

---

### Answer logistics
Preferred: fill the templates in Excel (they mirror your existing formats) and return via the shared WhatsApp/Drive channel. We will import answers directly — every template column maps 1:1 to a field in `canonical_schema.md`.
