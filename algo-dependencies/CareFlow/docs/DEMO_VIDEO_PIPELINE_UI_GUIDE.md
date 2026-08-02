# CareFlow Demo Video UI Guide for the Director Agent

Generated from the current CareFlow frontend on 2026-06-29.

This document describes the visible UI for the four CareFlow pipelines in enough detail for a demo video director agent to plan screen recordings, shot order, zooms, captions, and voiceover. It is written from the product surface, not from backend implementation details.

## Global UI Language

CareFlow should be filmed as a calm case-work desk, not a generic AI dashboard.

Core visual traits:

- Warm paper background with subtle dotted paper texture.
- Ink-colored text and thin archival rules.
- Cinnabar red accents for primary actions, stamps, review marks, and important AI/human handoff moments.
- Sage green for completed, live, reviewed, or downloadable states.
- Amber for pending, mock, incomplete, AI-inferred, or caution states.
- Serif headings for document/case language.
- Small monospace `folio` labels for dates, IDs, model names, counters, and case numbers.
- Rectangular low-radius buttons and stamps, not rounded SaaS pills.
- Dense operational layouts that show source evidence, extracted data, review state, and outputs.

The key story to preserve in the video:

1. CareFlow receives real-world documents, audio, or templates.
2. AI drafts or extracts structure.
3. The human reviews, edits, confirms, and exports.
4. The system leaves visible evidence: status stamps, source files, model/provider state, timestamps, confidence marks, and downloads.

## Global Navigation and Opening Shot

### Sidebar

The app has a persistent left sidebar.

Top identity block:

- Red square stamp mark: `護`.
- Chinese wordmark: `護 流`.
- Small folio line: `CAREFLOW · v0.4.5` in the current sidebar UI.
- Tagline in Chinese about returning paperwork time to elder care.

Navigation sections:

- `卷宗`
  - `00 工作台`
  - `01 歷史紀錄`
  - `02 輸出模板`
  - `03 案頭偏好`
- `處理流水線`
  - `α 志工紙本 → Excel`
  - `β 语音转录 → 報告`
  - `γ 福利表 → PDF`
  - `θ 自訂 PDF 表 → 模板`

Footer:

- Green confidence dot.
- `強制人工審查工作流`.
- Model line: `DeepSeek-V4 · Qwen3.6-VL · Fun-ASR`.

Director notes:

- Start with a full desktop shot that shows the sidebar and dashboard together.
- Keep the sidebar visible long enough for viewers to understand the four-pipeline navigation.
- Avoid lingering on the sidebar version number unless the video is explicitly about release/version state.

### Dashboard

Route: `/`

Main visual:

- Eyebrow: `工作台 · Desk`.
- Large serif title: `今日案頭 .`
- Subtitle: `一個社工，一張紙，一杯凍奶茶。我們處理表格，您處理人。`
- Right header shows Hong Kong date and live session time.

Four pipeline cards:

1. `α 志工紙本表 → NGO Excel`
2. `θ 自訂 PDF 表 → 可重用模板`
3. `β 语音转录 → 結構化報告`
4. `γ 政府福利表 → 已填寫 PDF`

Each card has:

- Large faded pipeline symbol.
- Cinnabar status stamp such as `現行版本` or `新版`.
- Serif title/subtitle.
- Short operational description.
- Bottom action text `立即開始 →`.

Lower dashboard:

- `最近案卷` list on the left, with status stamps.
- `系統現況 · 三通道` on the right, showing text, vision, and ASR providers with `live` or `mock` stamps.
- `啟用中 · 輸出模板` showing active Excel template status.

Opening shot recommendation:

- Start at dashboard.
- Slow pan or crop across the four cards.
- Use a caption: "Four workflows, one review-first desk."
- Then enter each pipeline by clicking its card or sidebar item.

## Pipeline Alpha: Volunteer Paper Forms to NGO Excel

Pipeline symbol: `α`  
Primary route: `/volunteer/upload`  
Review route: `/volunteer/review/:batchId`  
History route: `/history` and `/history/:batchId`

### Alpha Story

Alpha turns hand-filled volunteer visit forms into reviewed structured records and Excel exports.

The UI stages are:

1. Create a case batch and receive paper photos.
2. AI vision extraction runs.
3. Human reviews each form against the source photo.
4. The reviewed batch is exported to Excel.
5. The batch appears in history with correction/audit evidence.

### Stage A1: Create Batch and Upload Photos

Screen: `立卷 · 收 紙`

Visible header:

- Eyebrow: `流水線 α · 步驟 1 / 3`
- Serif title: `立卷 · 收 紙`
- Description explains that the user creates a case cover and drops in hand-filled paper photos.
- Thin black rule below the intro.

Form layout:

- Two-column label/content grid with small `§` folio markers.
- `§ i 案卷標題` required, prefilled with a date-style title such as `2026-06-29 志工探訪批次`.
- `§ ii 志工隊` with placeholder `例：中大義工隊`.
- `§ iii 探訪日期` date input.
- `§ iv 備註` text area.
- `§ v 收文` upload zone with hint `JPG / PNG，可一次拖入多張`.

Upload zone states:

- Empty state: large serif text `⌇ 將紙頁 ⌇`, helper `拖入此處 · 或 點擊選取`.
- Drag-over state: border turns cinnabar and background becomes pale red.
- After files selected: text changes to `已收文 N 份`, then a two-column list of filenames with folio numbers `01`, `02`, etc.

Bottom action row:

- Small note: AI vision extraction starts after upload; all results require human review before Excel export.
- Auto-complete state shown as `自動補全：已開啟` or `未開啟`, with a `設定 →` link.
- Buttons:
  - `清空` ghost button.
  - `立 · 案` cinnabar stamp button.
  - Busy state: `收文中…`.

Shot direction:

- Show a drag-and-drop action with 3-5 paper form images.
- Zoom into the upload zone as it changes from empty to filename list.
- Then zoom to the cinnabar `立 · 案` button.
- Voiceover should say: "The workflow begins as a case file, not as a black-box upload."

### Stage A2: AI Vision Extraction Loading State

Screen appears after upload while batch status is `uploaded` or `extracting`.

Visible layout:

- Centered narrow page.
- Eyebrow: `流水線 α · 步驟 2 / 3`.
- Batch title.
- Black rule.
- Large pulsing cinnabar serif character: `墨`.
- Text: `視覺抽取進行中`.
- Counter: `共 N 份手稿，每份約 2 - 8 秒。`
- Folio helper: `頁面自動刷新 · 請勿關閉`.

Shot direction:

- This is a strong visual transition. Capture the pulsing `墨` character for 2-3 seconds.
- Use it as a bridge between upload and review.
- Do not overstate this as final automation. The next shot must show human review.

### Stage A3: Human Review Workspace

Screen: `/volunteer/review/:batchId`

This is the most important Alpha UI.

Overall layout:

- Full-height review screen.
- Sticky top bar.
- Three-column workspace:
  - Left: page thumbnail strip.
  - Center: source photo viewer with bounding-box focus.
  - Right: editable structured field panel.

Top bar:

- Back link: `← 案卷`.
- Eyebrow: `流水線 α · 步驟 2 / 3 · 人工審查`.
- Batch title in serif.
- Review progress: `進度 reviewed/total`.
- Batch status stamp, e.g. `待審`, `已審`, `已匯出`.
- Reviewer input placeholder: `審查者`.
- Primary button: `用印 · 匯出`; busy state `處理中`.

Left thumbnail strip:

- Each record has a folio number, e.g. `01`, `02`.
- Thumbnail image in paper-colored frame.
- Active thumbnail has paper background and cinnabar left border.
- Per-record state:
  - `✓ 已審` in sage for reviewed.
  - `待審` in amber for pending.
  - `不完` badge if incomplete.
  - `AI補` badge if AI auto-filled fields.

Center source viewer:

- Original form photo shown on paper sheet with shadow.
- When the user focuses a field in the right panel, a cinnabar bounding box appears on the photo.
- The rest of the image is dimmed with a paper-colored overlay.
- A small folio label names the focused field.
- Footer helper: `點右側欄位 ⇢ 照片定位 · 滑鼠移開恢復`.

Right review panel:

- Header: `手稿 01 / 05`, original filename.
- `已 審` stamp appears after review.
- `刪 此 頁` button for useless/non-form pages.
- Warnings can appear:
  - `需 人 工 輸 入` if the vision model could not produce valid content.
  - `AI 抽取警告`.
  - Mock-mode explanation.
  - `信 息 不 完 整` with missing fields and partial blur notes.
  - `AI 推測補全了... · 請人工審核`.

Field rows:

- Each field label appears in serif with a confidence dot.
- Confidence colors:
  - Sage dot: high confidence.
  - Amber dot: medium/incomplete.
  - Cinnabar dot: low confidence.
  - Muted dot: no confidence.
- Confidence percentage appears in folio text.
- Field input can be text, date, number, or select.
- Changed values show a cinnabar `修` marker.
- AI-inferred fields show `AI 推測`.
- Missing fields show `缺`.
- Partial unreadable spans show `局部模糊`; original text can contain amber highlighted marks.
- DeepSeek second-review corrections show a red left rail, `DeepSeek 修正` badge, reason text, original Qwen value, and a `↶ 撤回` button.
- AI suggestions show `AI 建議` with an `採用` button.

Bottom review actions:

- `← 上一張`.
- `確認 →` for unreviewed records.
- `更新 →` for already reviewed records.
- Footnote: corrections are recorded for prompt improvement.

Shot direction:

- Use a wide shot to establish the three-column review layout.
- Then crop sequentially:
  - Left thumbnails and progress.
  - Center image with bbox.
  - Right field row with confidence and correction.
  - Confirm button.
- Demonstrate clicking a field so the bounding box appears on the form photo.
- Demonstrate one manual edit and one `採用` AI suggestion if sample data supports it.
- Make the human-review message explicit: AI extracts, human confirms.

### Stage A4: Excel Export and History

Export feedback in review screen:

- After `用印 · 匯出`, a sage success banner appears.
- Text: `已匯出 N 列 · exported_file`.
- Button: `下載 .xlsx`.

History list:

- Route `/history`, tab `α 志工紙本`.
- Header: `歷史 案 卷`.
- Filters for keyword, status, team, date range.
- Table columns:
  - checkbox
  - `№`
  - case title
  - volunteer team
  - date
  - photo count
  - review count
  - status
  - created time
  - action link `查 →`
- Multi-select action: `合 · 匯`.
- Combined-export success shows row count and `下載 .xlsx`.

History detail:

- Route `/history/:batchId`.
- Header shows case title, team, visit date, total photos, review count.
- Status stamp, download button, and `續審`.
- Correction summary: `本卷 · 人工修正`, total corrections, field-level AI value to final value.
- Record cards show photo, `信息不完整` or `AI 補全` badges, reviewed/pending stamps, key fields, and reviewer timestamp.

Shot direction:

- End Alpha with the green export banner and `.xlsx` download.
- Optional second ending: history detail page showing correction trail, to prove auditability.

## Pipeline Beta: Audio Transcription to Structured Report

Pipeline symbol: `β`  
Primary route: `/home-visit`  
Review route: `/home-visit/sessions/:sessionId`

### Beta Story

Beta turns an audio recording and a DOC/DOCX report template into a reviewed structured report. It emphasizes privacy, encrypted transcript handling, human review, and final DOCX rendering.

The UI stages are:

1. Create a visit or meeting session.
2. Upload audio and a report template.
3. AI transcribes and drafts dynamic fields.
4. Human reviews generated fields against a limited transcript snippet.
5. The system renders a DOCX.
6. The transcript can be burned after review.

### Stage B1: Create Audio Session

Screen: `/home-visit`

Visible header:

- Folio: `流水線 β`.
- Large serif title: `语音转录 → 結構化報告`.
- Subtitle explains that audio and institutional templates are uploaded, AI drafts content, and every field requires human review before rendering.
- Thin rule.

Main upload area:

- Left column: `新案 · 立案`.
- Mode segmented control:
  - `家访语音`
  - `会议纪要`
  - Selected mode is ink-black with paper text.
- `i · 個案標題` input.
  - Home visit placeholder: `例：陳婆婆 2026-05 月度家訪`.
  - Meeting placeholder: `例：服務隊 2026-05 月度會議`.
- `ii · 備註（可選）`.
- Two side-by-side upload boxes:
  - `iii · 錄音`, accepts `.mp3 / .wav / .m4a`; empty label `⌇ 拖入錄音 ⌇`; folio `支援廣東話 · fun-asr`.
  - `iv · 報告模板`, accepts `.docx / .doc`; empty label `⌇ 拖入表格模板 ⌇`; folio `機構自家版式 · 完整保留`.

Actions:

- Cinnabar button: `送 件 立 案`.
- Busy state: `建立中…`.
- Secondary bordered button: `✦ 一鍵 Mock 示範`; busy state `Mock 示範生成中…`.
- Small folio note: creation automatically starts transcription and draft generation.

Privacy right column:

- Eyebrow: `隱私 · 信則`.
- Cinnabar left rule.
- Four numbered privacy principles:
  - transcript encrypted in backend vault;
  - worker sees structured fields and short transcript snippet;
  - burn transcript after review;
  - all AI output requires human review before DOCX rendering.

Session list below:

- Eyebrow: `案宗 · 流轉`.
- Count: `共 N 件`.
- Table columns:
  - `#`
  - `個案標題`
  - `狀態`
  - `錄音 · 模板`
  - `覆核人`
  - `最後更新`
  - action `覆核 →`
- Status stamps include `已收件`, `AI 抽取中`, `待覆核`, `已用印`, `已焚錄音稿`.

Shot direction:

- Show both upload boxes together to communicate "audio plus template".
- Zoom into the privacy column. It is visually distinctive and important.
- Prefer using `一鍵 Mock 示範` for video if the real AI run is too slow.

### Stage B2: AI In-Progress Session Page

Screen: `/home-visit/sessions/:sessionId`

Visible state when status is `uploaded` or `extracting`:

- Header: `流水線 β · 案宗 001`.
- Large session title.
- Status stamp on right, e.g. `AI 抽取中`.
- Provider/model/latency folio line if available.
- Center message:
  - Folio `AI · 進行中`.
  - `正在抽取錄音逐字、分析模板契約、生成草稿…`
  - Folio `本頁每 3 秒自動刷新。`

Shot direction:

- Use this as a short process bridge.
- Do not spend too long on this screen unless the video wants to emphasize real waiting/processing.

### Stage B3: Human Review and Template Contract

Screen after AI finishes and status is not failed.

Overall layout:

- Two-column grid:
  - Left: dynamic field review.
  - Right: template contract preview and metadata.

Header:

- Folio: `流水線 β · 案宗 001`.
- Large title.
- Optional note below title.
- Right side status stamp: `待覆核`, `已用印`, etc.
- Provider/model/latency line, e.g. `deepseek · model · 12345ms`.

Left column:

- Eyebrow: `人手覆核 · 動態欄位（N）`.
- Link/button: `閱 · 錄音稿摘要`.
- If burned, the link reads `逐字稿已焚`.
- Instruction states every field is AI-drafted and must be reviewed.
- Dynamic slot editor:
  - Each slot has a left border.
  - Serif slot label.
  - Optional description or section hint.
  - Folio state:
    - `AI 草稿` before edit.
    - `已修正` after edit.
  - Textarea uses serif text and underline focus style.

Action row:

- Reviewer input: `覆核人`, placeholder `社工姓名`.
- Cinnabar button:
  - `用 印 · 渲 染 DOCX`.
  - Busy state: `用印中…`.
  - If confirmed: `重 · 用 印`.

Confirmed state:

- Sage bordered success panel.
- Eyebrow: `已用印 · 可下載`.
- Generated file path/name in monospace.
- Link: `下載 DOCX →`.

Right column:

- Eyebrow: `模板契約 · 固定區塊（N）`.
- Bordered paper box with fixed blocks from the template.
- Folio note: fixed blocks are written back unchanged; dynamic slots use reviewed content.
- Metadata table:
  - created time
  - updated time
  - audio filename
  - template filename
  - reviewer
  - transcript state, usually `加密在 vault` or `已焚`.

Shot direction:

- Use one wide shot showing left dynamic fields and right fixed template contract.
- Crop into one textarea; edit a sentence so `AI 草稿` changes to `已修正`.
- Then show the `用 印 · 渲 染 DOCX` button and final green download panel.

### Stage B4: Transcript Snippet Modal and Burn

Modal opens from `閱 · 錄音稿摘要`.

Modal design:

- Dark translucent ink overlay.
- Paper modal with border.
- Header:
  - Eyebrow `機密 · 錄音稿摘要`.
  - Folio `至多 200 字 · 全文需主管授權`.
  - Close control `關 ×`.
- Body:
  - Serif transcript snippet, scrollable.
  - If burned: `（逐字稿已焚）`.
- Footer:
  - Folio `覆核完成後請即焚`.
  - Button `閱 後 · 即 焚`, then `已 · 焚`.

Burn confirmation:

- Browser confirm dialog: transcript will be overwritten and deleted, irreversible.

Shot direction:

- This modal is one of the clearest privacy shots in the app.
- Capture opening the snippet, then the burn button.
- If filming an irreversible demo, use mock data.
- Voiceover: "The full transcript is not casually exposed; the review surface uses a snippet and supports burn-after-review."

### Stage B5: Beta History

History tab: `/history?p=beta`.

Visible table:

- Eyebrow: `语音转录 → 結構化報告`.
- Helper: all Beta voice sessions; click to review or download DOCX.
- Columns:
  - `№`
  - title
  - status
  - model
  - latency
  - created time
  - download or inspect action
- Burned transcripts show small text `逐字稿已銷毀`.

Shot direction:

- Use as a closing shot after DOCX render and burn.
- Show that completed sessions remain auditable without keeping raw transcript text visible.

## Pipeline Gamma: Welfare Form to Filled PDF

Pipeline symbol: `γ`  
Primary route: `/welfare-form`

### Gamma Story

Gamma turns elder profile information into a filled PDF welfare form. It can use a mock elder profile, extract a profile from raw social-worker notes or images, select either preset templates or custom Theta templates, preview field mappings, allow manual corrections, and generate a filled PDF with an embedded preview.

The UI stages are:

1. Choose or extract elder profile data.
2. Select a preset or custom form template.
3. Preview field mapping and sources.
4. Optionally let DeepSeek infer missing fields.
5. Manually override any value.
6. Generate and preview/download the PDF.

### Stage G1: Welfare Form Landing

Screen: `/welfare-form`

Visible header:

- Eyebrow: `流水線 γ · 政府福利表`.
- Large title: `福 利 表 套 組`.
- Description says the user can choose preset forms or custom templates uploaded through `θ`, and that the system maps elder facts into form fields.
- Thin rule.

If mock profile is missing:

- Amber left-rail warning: missing `data/mock_elder_profile.json`.

Shot direction:

- Start with the header and two-column layout below.
- Mention this pipeline is the "fill the government/NGO form" workflow.

### Stage G2: Advanced Elder Profile Extraction

Collapsible panel:

- Bordered paper panel.
- Header button:
  - Eyebrow: `流水線 γ · 進階`.
  - Title: `從原始文字 AI 抽取長者資料`.
  - Helper: paste social-worker notes, medical history, or case intro; AI extracts structured `ElderProfile`.
  - Right side shows `▾` or `▴`.
  - If a profile is active: `✓ 已套用：name`.

When expanded:

- Tabs:
  - `純文字`
  - `照片`
- Text mode:
  - Large monospace textarea.
  - Placeholder includes example elder information: name, HKID, date of birth, phone numbers, address.
- Image mode:
  - Dashed upload panel with `拖入照片 · 或 點擊選取`.
  - If image chosen: preview image, filename, size, and note that Vision LLM will read HKID/application forms/social-worker notes.
- Right control column:
  - `資料來源` select:
    - `社工筆記`
    - `病人卡`
    - `家屬訪談`
    - `個案介紹`
    - `身份證照`
    - `申請表照`
    - `其他`
  - Cinnabar button `AI 抽取`; busy `AI 抽取中...`.
  - Link `清除，恢復用 mock` when profile is active.

Extraction success panel:

- White panel with sage border.
- Title: `✓ 已抽取 — 將套用至下方表格`.
- Badge: `mock 模式` or `DeepSeek LLM`.
- Grid of extracted facts:
  - Chinese name
  - English name
  - HKID
  - date of birth
  - sex
  - marital status
  - home phone
  - mobile phone
  - address
  - confidence and notes

Shot direction:

- Show the panel closed, then expand it.
- Film either text extraction or image extraction; text is easier to read on video.
- After extraction, crop into the green success panel to show structured profile fields.

### Stage G3: Template Selection

Below the profile panel, layout splits into:

- Left template list, 4 columns wide.
- Right mapping preview, 8 columns wide.

Left template list:

- Custom Theta section appears if custom templates exist:
  - Eyebrow: `自訂模板 θ`.
  - Helper text explains templates came from Theta and are mapped to elder fact storage.
  - Each card can show a `θ` badge in top-right.
- Preset section:
  - Eyebrow: `預設套組`.
- Template cards:
  - Serif display name.
  - Optional English display name.
  - Badges/details:
    - `AcroForm` or `坐標模板`.
    - page count.
    - field count.
    - `未開放` if not ready.
  - Selected card has stronger ink border and paper background.

If no custom templates:

- Dashed panel invites user to go to `θ 流水線上傳自訂 PDF →`.

Shot direction:

- If the video includes Theta first, return to Gamma and show a newly created `θ` custom template appearing in this list.
- This is the strongest way to show that Theta feeds Gamma.

### Stage G4: Mapping Preview and Manual Override

Right mapping header:

- Eyebrow with selected template ID.
- Large template display name.
- Checkbox: `缺欄位用 DeepSeek 推測`.

Loading state:

- `⌇ 載入欄位中 ⌇`.

Mapping summary:

- `共 N 欄`
- `直接 N`
- `預設 N`
- `AI N`
- `缺 N`

Mapping table:

- Columns:
  - `欄位`
  - `值`
  - `來源`
- Each field row:
  - Field display label in ink.
  - Field key in tiny monospace.
  - Editable value input.
  - Source badge:
    - `直接`
    - `預設`
    - `AI 推測`
    - `缺`
    - `手改` after manual override.
  - Optional `reason` line with lightbulb text.

Manual changes:

- Edited values turn amber and bold.
- `清除手改 (N)` link appears.
- Clear action asks for confirmation.

Shot direction:

- Film toggling `缺欄位用 DeepSeek 推測`, then show `AI` count or `AI 推測` badge if data supports it.
- Manually edit one field so the source changes to `手改`.
- Crop into the mapping summary and source badges. This communicates provenance better than voiceover alone.

### Stage G5: Generate PDF and Preview

Action:

- Cinnabar button `生成 PDF`.
- Busy state `生成中...`.

Success panel:

- Left sage rail.
- Serif title: `✓ PDF 已生成`.
- Stats grid:
  - strategy
  - latency
  - filled count
  - ticked count
  - empty values if any, shown in amber
- Download row:
  - Cinnabar button `下載 PDF`.
  - Output filename in small monospace.
- Embedded iframe preview:
  - White PDF preview area.
  - Border around the preview.
  - Height around 600px, so it becomes a large visual payoff.

Shot direction:

- End Gamma with the generated PDF preview filling most of the screen.
- Crop into one filled field in the iframe if readable.
- Voiceover: "The user can still override any mapped value before the PDF is generated."

## Pipeline Theta: Custom PDF Form to Reusable Template

Pipeline symbol: `θ`  
Primary route: `/theta/upload`  
Audit route: `/theta/audit/:templateId`

### Theta Story

Theta is the template factory for Gamma. It turns any blank PDF form into a reusable CareFlow template by detecting fillable fields, letting a human review bounding boxes and field labels, and then saving the template for future welfare-form filling.

The UI stages are:

1. Upload a blank PDF and name the template.
2. GPT-5-mini analyzes each page.
3. A summary page shows provider/model/field count/page errors.
4. Human reviews and edits detected fields on the PDF.
5. The template is saved and later appears in Gamma's custom template list.

### Stage T1: Upload Custom PDF

Screen: `/theta/upload`

Visible header:

- Eyebrow: `流水線 θ · 步驟 1 / 3`.
- Title: `立卷 · 上呈表單`.
- Description: upload a blank PDF form; GPT-5-mini will identify fields and positions; user reviews next.
- Thin rule.

Form fields:

- `§ i 模板名稱`, required.
  - Placeholder: `例：機構 X 入會申請表`.
- `§ ii 備註（可選）`.
  - Placeholder: `例：2025 版，共 2 頁`.
- `§ iii 上傳 PDF 表單`, hint `僅接受 .pdf · ≤ 20MB · ≤ 30 頁`.

Upload zone:

- Empty: `⌇ 拖入 PDF ⌇`, helper `拖入此處 · 或 點擊選取`.
- Drag-over: cinnabar border and pale red background.
- After file selected:
  - `已選取`.
  - filename in monospace.
  - file size.

Bottom note and actions:

- Note: GPT-5-mini analyzes the PDF and results require human review before saving as a template.
- Buttons:
  - `清空`.
  - `立 · 案`.
  - Busy state: `分析中…`.

Shot direction:

- Use a clean PDF filename and readable template name.
- Show the file drop and selected state.
- Click `立 · 案` and cut immediately to the overlay.

### Stage T2: Full-Screen GPT Analysis Overlay

Appears while upload/analysis is busy.

Visual:

- Full viewport overlay with pale paper background and slight blur.
- Centered content.
- Eyebrow: `流水線 θ · 分析中`.
- Large serif headline: `GPT-5-mini 正在逐頁審視 PDF`.
- Thin rule.
- Timer: `已耗時 N 秒`, with elapsed seconds in cinnabar.
- Explanation: typically 20-120 seconds depending on page count; do not close/refresh.
- Three small cinnabar pulsing dots.

Shot direction:

- This is the clearest "AI is actually running" state in CareFlow.
- Hold for 3-4 seconds to show elapsed timer movement.
- Avoid making it feel magical; immediately follow with human review requirement.

### Stage T3: GPT Analysis Result Summary

Screen: `流水線 θ · 步驟 1.5 / 3`

Visible header:

- Title: `GPT 已完成審視`.
- Description says GPT vision produced an initial review and the user must enter manual review to correct fields before saving.
- Thin rule.

Metadata grid:

- `模板 ID`
- `模板名稱`
- `提供方`
- `模型`
- `總頁數`
- `識別欄位` highlighted
- `分析耗時`
- `失敗頁數`, warning if nonzero

Partial error block:

- If some pages fail, a cinnabar left-rail panel lists page errors.

Bottom actions:

- Ghost button `重新上傳`.
- Cinnabar button `→ 進入人工審查`.

Shot direction:

- Crop into `識別欄位` and `分析耗時`.
- If there are page errors, show them briefly as a resilience point, not as a failure.
- Click `進入人工審查`.

### Stage T4: Three-Column PDF Field Audit

Screen: `/theta/audit/:templateId`

Overall layout:

- Full-height audit screen.
- Sticky top bar.
- Three-column workspace:
  - Left: PDF page thumbnails.
  - Center: PDF page image with interactive bounding boxes.
  - Right: field editor and page field list.

Top bar:

- Back link: `← 工作台`.
- Eyebrow: `流水線 θ · 步驟 2 / 3 · 審查欄位`.
- Template name in serif.
- Count: `共 N 欄位`, optionally `本頁 N`.
- `已儲存` sage stamp after save.
- Cinnabar button: `確認 · 儲存模板`; busy `儲存中…`.

Left page thumbnails:

- One thumbnail per PDF page.
- Folio page numbers `01`, `02`, etc.
- Active page has cinnabar left border.
- Each thumbnail shows field count: `N 欄位`.

Center PDF canvas:

- PDF page rendered as an image on paper surface.
- Detected fields appear as red-brown/cinnabar bounding boxes.
- Selected field:
  - More vivid cinnabar border.
  - Pale red fill.
  - Large dimming overlay around the box.
  - Label above box becomes larger and fully opaque.
  - Eight small resize handles appear.
- Unselected field:
  - Thin muted border.
  - Small label above box, truncated after about eight characters.
  - Hover makes label more visible.
- Interaction note under canvas:
  - `拖曳方框調整位置 · 拉動邊角調整大小 · 點空白處新增欄位`.

Optional double-box mode:

- If fields have refined coordinates, a checkbox appears:
  - `顯示 LLM 原始 bbox（藍虛線）vs 向量微調後（紅實線）`
  - Right side: `已微調 X / N`
- Ghost original boxes are dashed and non-interactive.

Right field editor:

- Eyebrow: `欄位編輯器`.
- Header: `頁 X · N 欄位`.
- If nothing selected:
  - Instructions: click a field box to edit, or click blank area to add.
- Selected field editor:
  - `欄位 #N`.
  - Delete button: `刪除此欄位`.
  - `標籤名稱` input.
  - `識別碼 (key)` input, monospace.
  - `欄位類型` select with:
    - text
    - number
    - date
    - checkbox
    - signature
    - select
  - `AI 信心值` bar with percentage.
  - `位置 (bbox)` numeric x/y/w/h.
- Page field list:
  - `此頁欄位列表`.
  - Each item shows label, type, and key.
  - Selected item has cinnabar left rail.
- Bottom button: `+ 手動新增欄位`.

Shot direction:

- Use a wide shot to show the three-column audit workspace.
- Then demonstrate:
  - Click a red bounding box.
  - Drag or resize a box slightly.
  - Edit field label or type on the right.
  - Show confidence bar and bbox coordinates.
  - Save with `確認 · 儲存模板`.
- If double-box mode exists, briefly show the checkbox and ghost boxes; explain as "AI proposal vs refined coordinates."

### Stage T5: Template Becomes Reusable

There is no separate flashy success page. The value is shown in two places:

1. Theta audit page:
   - `已儲存` stamp appears.
   - The template remains editable.
2. Gamma welfare-form page:
   - Custom template appears under `自訂模板 θ`.
   - It can be selected and used for field mapping and PDF generation.
3. History:
   - `/history?p=theta` lists custom PDF templates.
   - Columns include template name, page count, field count, status, created time, and `審 →`.

Shot direction:

- For a full demo story, after saving in Theta, navigate to Gamma and show the saved `θ` template card.
- This creates a clear "template factory feeds form filling" narrative.

## Suggested Video Structure

For a concise 3-5 minute demo:

1. Open on Dashboard and sidebar.
2. Alpha: upload paper photos, show `墨` extraction state, show three-column human review, export Excel.
3. Beta: create audio session with template, show privacy rules, show review fields and transcript modal, render DOCX.
4. Theta: upload PDF, show GPT analysis overlay, show bbox audit, save template.
5. Gamma: select the Theta template or preset form, extract elder profile, preview mappings, generate PDF.
6. Close on History page showing completed case records and downloads.

For a longer 6-8 minute demo:

1. Dashboard orientation.
2. Brand/UI explanation: paper desk, stamps, folios, mandatory review.
3. Alpha complete flow.
4. Beta complete flow including burn.
5. Theta complete flow.
6. Gamma complete flow using the Theta-created template.
7. History and diagnostics/settings as proof of operational readiness.

## Director's Visual Checklist

Capture these UI moments if possible:

- Dashboard four pipeline cards in one shot.
- Sidebar with the four pipeline nav items.
- Alpha upload zone changing from empty to filename list.
- Alpha pulsing `墨` extraction state.
- Alpha three-column review with photo bbox and editable fields.
- Alpha export success banner with `.xlsx` download.
- Beta privacy rules panel.
- Beta audio and DOCX upload boxes side by side.
- Beta AI-in-progress text.
- Beta dynamic field review with fixed template contract preview.
- Beta transcript snippet modal and burn button.
- Beta DOCX download success panel.
- Theta full-screen GPT analysis overlay with timer.
- Theta analysis result summary with total fields and latency.
- Theta PDF bounding-box editor with selected field handles.
- Theta save stamp.
- Gamma elder profile extraction success panel.
- Gamma custom `θ` template list.
- Gamma mapping table with source badges.
- Gamma manual override changing a row to `手改`.
- Gamma generated PDF iframe preview.
- History page tabs for Alpha, Beta, and Theta.

## What Not to Show or Imply

Do not imply:

- AI output is final without human review.
- CareFlow is a fully autonomous clinical decision system.
- The transcript is freely visible to all users.
- The PDF/Excel output is generated before review.
- Theta templates are ready without field audit.
- Mock mode equals real extraction quality.

Avoid filming:

- Real private elder data.
- API keys or backend environment screens.
- Browser credential prompts or Basic Auth credentials.
- Long idle waits without captions.
- Version stamps as a focal point unless they are intentionally part of the story.

## Recommended Captions

Use concise captions over the screen recording:

- `Upload real-world paperwork`
- `AI extracts a draft`
- `Human review is mandatory`
- `Confidence and corrections stay visible`
- `Export only after review`
- `Audio is transcribed into structured report fields`
- `Transcript snippet is privacy-limited`
- `Burn transcript after review`
- `GPT detects PDF form fields`
- `Human audits every bounding box`
- `Custom templates feed welfare-form autofill`
- `Every mapped field can be overridden`
- `Final PDF preview and download`

## Final Narrative Line

CareFlow's UI is not about replacing judgment. It is a paper-warm review desk where AI handles first drafts, and care workers keep control over every record, field, transcript, template, and export.
