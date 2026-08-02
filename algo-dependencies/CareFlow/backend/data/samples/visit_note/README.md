# Home-Visit Mock Samples

用於 `POST /api/home-visit/sessions/mock-demo` 的離線示範。

- `mock_template.docx` — 機構家訪紀錄模板（複製自 tests/visit_note）
- `mock_visit.mp3` — 靜音 MP3 placeholder；mock 模式下不會被解碼，
  ASR 直接落回 `tests/visit_note/transcript_example.txt` 的廣東話樣本。
- `mock_transcript.txt` — 與 transcriber fallback 同步的逐字稿（離線備援）。
