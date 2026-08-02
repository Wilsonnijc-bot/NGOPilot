import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, BatchOut, RecordOut, VolunteerField } from "../lib/api";
import { StatusStamp } from "../components/StatusStamp";

export default function VolunteerReview() {
  const { batchId } = useParams<{ batchId: string }>();
  const bid = Number(batchId);

  const [batch, setBatch] = useState<BatchOut | null>(null);
  const [records, setRecords] = useState<RecordOut[]>([]);
  const [schema, setSchema] = useState<VolunteerField[]>([]);
  const [activeIdx, setActiveIdx] = useState(0);
  const [draft, setDraft] = useState<Record<string, any>>({});
  const [reviewer, setReviewer] = useState(() => localStorage.getItem("careflow.reviewer") || "");
  const [focusField, setFocusField] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportRes, setExportRes] = useState<any>(null);
  const [pollTimedOut, setPollTimedOut] = useState(false);
  const [pollError, setPollError] = useState(false);
  const pollAttempts = useRef(0);

  useEffect(() => { api.getSchema().then((r) => setSchema(r.fields)); }, []);

  const refresh = useCallback(async () => {
    const [b, r] = await Promise.all([api.getBatch(bid), api.listRecords(bid)]);
    setBatch(b);
    setRecords(r.records);
    return { batch: b, records: r.records };
  }, [bid]);

  useEffect(() => {
    refresh();
    pollAttempts.current = 0;
    setPollTimedOut(false);
    const MAX_ATTEMPTS = 150; // ~5 min at 2s
    const t = setInterval(async () => {
      pollAttempts.current += 1;
      if (pollAttempts.current > MAX_ATTEMPTS) {
        setPollTimedOut(true);
        clearInterval(t);
        return;
      }
      try {
        const { batch } = await refresh();
        setPollError(false);
        if (batch.status !== "extracting" && batch.status !== "uploaded") clearInterval(t);
      } catch {
        setPollError(true);
      }
    }, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  const active = records[activeIdx];
  useEffect(() => {
    if (active) {
      setDraft(active.final_fields || active.ai_extracted || {});
      setFocusField(null);
    }
  }, [active?.id]);

  const submitReview = async (advance = true) => {
    if (!active) return;
    setBusy(true);
    setError(null);
    try {
      if (reviewer.trim()) localStorage.setItem("careflow.reviewer", reviewer.trim());
      const updated = await api.reviewRecord(active.id, draft, reviewer || undefined);
      const next = [...records];
      next[activeIdx] = updated;
      setRecords(next);
      if (advance && activeIdx < records.length - 1) setActiveIdx(activeIdx + 1);
      const b = await api.getBatch(bid);
      setBatch(b);
    } catch (e: any) {
      setError(e?.message || "提交失敗");
    } finally {
      setBusy(false);
    }
  };

  const doExport = async () => {
    // v0.4.0-rc4：不再硬卡「全部審查」，未審查完顯示確認框
    if (!allReviewed) {
      const ok = window.confirm(
        `這個批次尚有 ${records.length - reviewedCount} / ${records.length} 份未審查。\n\n` +
        `不譯别的欄位會原樣匯出。\n\n確定即處匯出嗎？`
      );
      if (!ok) return;
    }
    setBusy(true);
    setError(null);
    try {
      const r = await api.exportBatch(bid);
      setExportRes(r);
      const b = await api.getBatch(bid);
      setBatch(b);
    } catch (e: any) {
      setError(e?.message || "匯出失敗");
    } finally {
      setBusy(false);
    }
  };

  // v0.3.9：刪除當前紀錄（沒價值的頁、紙條、非表格雜訊）
  const deleteCurrent = async () => {
    if (!active) return;
    const ok = window.confirm(
      `確定刪除此頁？\n\n檔名：${active.original_filename}\n\n` +
      `此操作不可復原，會同時刪除照片與所有 AI 抽取結果。`
    );
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await api.deleteRecord(active.id);
      const list = await api.listRecords(bid);
      setRecords(list.records);
      // 自動跳到下一張（若刪掉最後一張就跳前一張）
      const nextIdx = Math.min(activeIdx, list.records.length - 1);
      setActiveIdx(Math.max(0, nextIdx));
      const b = await api.getBatch(bid);
      setBatch(b);
    } catch (e: any) {
      setError(e?.message || "刪除失敗");
    } finally {
      setBusy(false);
    }
  };

  const allReviewed = records.length > 0 && records.every((r) => r.is_reviewed);
  const reviewedCount = records.filter((r) => r.is_reviewed).length;

  if (!batch) return <div className="p-10 text-ink-400">讀取中…</div>;

  if (batch.status === "extracting" || batch.status === "uploaded") {
    return (
      <div className="max-w-2xl mx-auto px-10 py-24 text-center">
        <div className="eyebrow">流水線 α · 步驟 2 / 3</div>
        <h1 className="font-serif text-3xl mt-2">{batch.title}</h1>
        <div className="rule mt-6 max-w-md mx-auto"></div>
        <div className="mt-16">
          <div className="font-serif text-7xl text-cinnabar-500 animate-pulse">墨</div>
          <div className="font-serif text-xl mt-6 text-ink-900">視覺抽取進行中</div>
          <div className="text-sm text-ink-400 mt-2">
            共 {batch.total_photos} 份手稿，每份約 2 ‑ 8 秒。
          </div>
          <div className="folio mt-6">頁面自動刷新 · 請勿關閉</div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-screen">
      {pollError && (
        <div className="bg-amber_ink-50 text-amber_ink-700 text-xs px-4 py-1 border-b border-amber_ink-500/40">
          狀態更新失敗，將自動重試…
        </div>
      )}
      {pollTimedOut && (
        <div className="bg-amber_ink-50 text-amber_ink-700 text-xs px-4 py-1 border-b border-amber_ink-500/40">
          拉取超時，請重新整理頁面以繼續更新狀態。
          <button
            className="ml-3 underline text-amber_ink-700 hover:text-cinnabar-700"
            onClick={() => { pollAttempts.current = 0; setPollTimedOut(false); refresh(); }}
          >
            立即重試
          </button>
        </div>
      )}
      {/* ── 頂條 ────────────────────────────────────────── */}
      <header className="border-b border-ink-900/15 px-8 py-4 bg-paper-50/80 backdrop-blur flex items-center gap-5">
        <Link to="/history" className="folio text-ink-400 hover:text-cinnabar-500">← 案卷</Link>
        <div className="flex-1 min-w-0">
          <div className="eyebrow">流水線 α · 步驟 2 / 3 · 人工審查</div>
          <div className="font-serif text-xl truncate text-ink-900 mt-0.5">{batch.title}</div>
        </div>
        <div className="text-xs text-ink-400">
          <div>進度</div>
          <div className="font-mono text-lg text-ink-900">
            {reviewedCount}<span className="text-ink-400">/{records.length}</span>
          </div>
        </div>
        <StatusStamp status={batch.status} />
        <input
          className="input max-w-[140px] text-sm"
          placeholder="審查者"
          value={reviewer}
          onChange={(e) => setReviewer(e.target.value)}
        />
        <button
          className="btn-stamp"
          disabled={busy || records.length === 0}
          onClick={doExport}
          title={allReviewed ? "" : "尚有未審查項，點击會跳出確認框"}
        >
          {busy ? "處理中" : "用印 · 匯出"}
        </button>
      </header>

      {error && (
        <div className="border-b border-cinnabar-500/50 bg-cinnabar-50/40 text-cinnabar-700 text-sm px-8 py-2">
          {error}
        </div>
      )}
      {exportRes && (
        <div className="border-b border-sage-500/40 bg-sage-50 text-sage-700 text-sm px-8 py-2 flex items-center justify-between">
          <span>
            已匯出 <span className="font-mono">{exportRes.row_count}</span> 列 · {exportRes.exported_file}
          </span>
          <a className="btn-stamp" href={exportRes.download_url}>下載 .xlsx</a>
        </div>
      )}

      {/* ── 三欄主區 ────────────────────────────────────── */}
      <div className="flex-1 grid grid-cols-12 overflow-hidden">
        {/* 左：縮圖 */}
        <aside className="col-span-2 border-r border-ink-900/10 overflow-y-auto bg-paper-100/40 py-3">
          {records.map((r, i) => (
            <button
              key={r.id}
              className={`w-full text-left px-4 py-2.5 transition-colors flex items-start gap-3
                ${i === activeIdx ? "bg-paper-50 border-l-2 border-cinnabar-500" : "border-l-2 border-transparent hover:bg-paper-100/60"}`}
              onClick={() => setActiveIdx(i)}
            >
              <span className="folio pt-0.5">{String(i + 1).padStart(2, "0")}</span>
              <div className="flex-1 min-w-0">
                <div className="aspect-[3/4] bg-paper-200 overflow-hidden relative">
                  <img
                    src={r.photo_url}
                    className="w-full h-full object-cover"
                    alt=""
                    loading="lazy"
                    onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = "none"; }}
                  />
                  {r.is_complete === false && (
                    <span
                      className="absolute top-1 right-1 text-[10px] tracking-widest uppercase px-1.5 py-0.5 bg-amber_ink-500 text-paper-50 font-medium"
                      title={`缺失：${(r.missing_fields || []).join("、")}`}
                    >
                      不完
                    </span>
                  )}
                  {(r.auto_filled_keys?.length || 0) > 0 && (
                    <span
                      className="absolute bottom-1 left-1 text-[10px] tracking-widest uppercase px-1.5 py-0.5 bg-cinnabar-500 text-paper-50 font-medium"
                      title={`AI 補全：${r.auto_filled_keys?.join("、")}`}
                    >
                      AI補
                    </span>
                  )}
                </div>
                <div className="text-[10px] mt-1.5 flex items-center justify-between">
                  {r.is_reviewed ? (
                    <span className="text-sage-500">✓ 已審</span>
                  ) : (
                    <span className="text-amber_ink-500">待審</span>
                  )}
                </div>
              </div>
            </button>
          ))}
        </aside>

        {/* 中：照片 + bbox */}
        <div className="col-span-6 overflow-auto p-8 bg-paper-50/40">
          {active && (
            <PhotoViewer
              photoUrl={active.photo_url}
              bbox={active.ai_bbox || {}}
              focusField={focusField}
              schema={schema}
            />
          )}
        </div>

        {/* 右：表單 */}
        <aside className="col-span-4 overflow-y-auto bg-paper-100/30 border-l border-ink-900/10">
          {!active ? (
            <div className="p-8 text-ink-400">無資料</div>
          ) : (
            <div className="p-7">
              <div className="flex items-center justify-between">
                <div>
                  <div className="eyebrow">手稿 {String(activeIdx + 1).padStart(2, "0")} / {String(records.length).padStart(2, "0")}</div>
                  <div className="font-serif text-lg text-ink-900 mt-1 truncate">
                    {active.original_filename}
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  {active.is_reviewed && <span className="stamp-green">已 審</span>}
                  {(() => {
                    const isLast = records.length <= 1;
                    return (
                      <button
                        onClick={deleteCurrent}
                        disabled={busy || isLast}
                        title={
                          isLast
                            ? "此批次只剩這一張，不能刪除（若整批不需要，請改回首頁刪除整批）"
                            : "這頁不是表格 / 內容沒價值 — 永久刪除此頁與照片"
                        }
                        className="text-[11px] tracking-widest uppercase text-ink-400 hover:text-cinnabar-600 disabled:opacity-30 disabled:cursor-not-allowed border border-ink-900/15 hover:border-cinnabar-500 px-2 py-1 transition-colors"
                      >
                        刪 此 頁
                      </button>
                    );
                  })()}
                </div>
              </div>
              <div className="rule-thin mt-4 mb-5"></div>

              {active.needs_human_input && (
                <div className="border-l-2 border-cinnabar-500 pl-3 mb-3 bg-cinnabar-50/40 py-2 pr-2">
                  <div className="text-[11px] text-cinnabar-600 tracking-widest uppercase mb-1">
                    需 人 工 輸 入
                  </div>
                  <div className="text-xs text-ink-700 leading-relaxed">
                    AI 視覺模型對此照片無法輸出有效內容（影像可能模糊、傾斜或內容不清）。請逐欄手動填入，完成後按「完成審查」即可。
                  </div>
                </div>
              )}
              {active.ai_error && (
                <div className="border-l-2 border-amber_ink-500 pl-3 text-xs text-amber_ink-500 mb-3">
                  AI 抽取警告：{active.ai_error}
                </div>
              )}
              {active.ai_provider === "mock" && (
                <div className="border-l-2 border-amber_ink-500 pl-3 text-[11px] text-ink-400 mb-3 leading-relaxed">
                  目前為 mock 模式（未設 API key）。所有欄位均為合成假資料，用於 UI 展示。
                </div>
              )}
              {active.is_complete === false && (
                <div className="border-l-2 border-amber_ink-500 pl-3 mb-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[11px] text-amber_ink-500 tracking-widest uppercase">
                      信 息 不 完 整
                    </span>
                    {Object.keys(active.suggestions || {}).length > 0 ? (
                      <button
                        className="text-[11px] underline text-cinnabar-500 hover:text-cinnabar-700 disabled:opacity-40"
                        onClick={() => {
                          const sug = active.suggestions || {};
                          const next = { ...draft };
                          Object.keys(sug).forEach((k) => { if (sug[k] != null && sug[k] !== "") next[k] = sug[k]; });
                          setDraft(next);
                        }}
                        disabled={busy}
                        title="把所有 AI 建議一次填入草稿（仍需人工確認 → 確認）"
                      >
                        ✓ 全部採用 AI 建議
                      </button>
                    ) : (
                      <button
                        className="text-[11px] underline text-cinnabar-500 hover:text-cinnabar-700 disabled:opacity-40"
                        onClick={async () => {
                          if (!active) return;
                          setBusy(true);
                          try {
                            const updated = await api.autoCompleteRecord(active.id);
                            const next = [...records]; next[activeIdx] = updated;
                            setRecords(next);
                          } catch (e: any) {
                            setError(e?.message || "補全失敗");
                          } finally { setBusy(false); }
                        }}
                        disabled={busy}
                      >
                        🪄 讓 AI 補 全
                      </button>
                    )}
                  </div>
                  {(active.missing_fields || []).length > 0 && (
                    <div className="text-[11px] text-ink-700 mt-1 leading-relaxed">
                      缺失欄位：{(active.missing_fields || []).map(k => schema.find(s => s.key === k)?.label || k).join("、")}
                    </div>
                  )}
                  {Object.keys(active.partial_fields || {}).length > 0 && (
                    <div className="text-[11px] text-ink-700 mt-1 leading-relaxed">
                      局部模糊：{Object.keys(active.partial_fields || {}).map(k => schema.find(s => s.key === k)?.label || k).join("、")}
                      <span className="text-ink-400 ml-1">（黃底字符為 AI 無法辨識）</span>
                    </div>
                  )}
                </div>
              )}
              {(active.auto_filled_keys?.length || 0) > 0 && (
                <div className="border-l-2 border-cinnabar-500 pl-3 text-[11px] text-cinnabar-700 mb-3 leading-relaxed">
                  AI 推測補全了：{active.auto_filled_keys?.map(k => schema.find(s => s.key === k)?.label || k).join("、")}
                  <span className="text-ink-400 ml-1">· 請人工審核</span>
                </div>
              )}

              <div className="space-y-4">
                {schema.map((f) => (
                  <FieldRow
                    key={f.key}
                    field={f}
                    value={draft[f.key]}
                    confidence={active.ai_confidence?.[f.key] ?? 0}
                    aiValue={active.ai_extracted?.[f.key]}
                    isAutoFilled={(active.auto_filled_keys || []).includes(f.key)}
                    partialSpans={active.partial_fields?.[f.key]}
                    suggestion={active.suggestions?.[f.key]}
                    suggestionConfidence={active.suggestion_confidence?.[f.key]}
                    isMissing={(active.missing_fields || []).includes(f.key)}
                    isReviewed={(active.reviewed_keys || []).includes(f.key)}
                    originalValue={active.qwen_original?.[f.key]}
                    reviewReason={active.reviewed_reasons?.[f.key]}
                    reviewedConfidence={active.reviewed_confidence?.[f.key]}
                    onRevert={async () => {
                      try {
                        const updated = await api.revertReviewedField(active.id, f.key);
                        setRecords((rs) => rs.map((r) => (r.id === updated.id ? updated : r)));
                        // 同步 draft：把該欄位設回原值
                        setDraft({ ...draft, [f.key]: updated.ai_extracted?.[f.key] ?? null });
                      } catch (e) {
                        console.error("revert failed", e);
                      }
                    }}
                    onChange={(v) => setDraft({ ...draft, [f.key]: v })}
                    onFocus={() => setFocusField(f.key)}
                    onBlur={() => setFocusField(null)}
                  />
                ))}
              </div>

              <div className="flex gap-3 mt-7 pt-5 border-t border-paper-300/60">
                <button
                  className="btn-ghost flex-1"
                  disabled={busy || activeIdx === 0}
                  onClick={() => setActiveIdx(activeIdx - 1)}
                >
                  ← 上一張
                </button>
                <button
                  className="btn-stamp flex-1"
                  disabled={busy}
                  onClick={() => submitReview(true)}
                >
                  {active.is_reviewed ? "更新 →" : "確認 →"}
                </button>
              </div>
              <p className="text-[10px] text-ink-400 mt-3 leading-relaxed">
                每次修改自動記入 corrections 表，作 prompt 優化參考。
              </p>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function FieldRow({
  field, value, confidence, aiValue, isAutoFilled, partialSpans, suggestion, suggestionConfidence, isMissing,
  isReviewed, originalValue, reviewReason, reviewedConfidence, onRevert,
  onChange, onFocus, onBlur,
}: {
  field: VolunteerField; value: any; confidence: number; aiValue: any; isAutoFilled?: boolean;
  partialSpans?: [number, number][];
  suggestion?: any;
  suggestionConfidence?: number;
  isMissing?: boolean;
  isReviewed?: boolean;
  originalValue?: any;
  reviewReason?: string;
  reviewedConfidence?: number;
  onRevert?: () => void;
  onChange: (v: any) => void; onFocus: () => void; onBlur: () => void;
}) {
  const conf = useMemo(() => {
    const c = Math.round(confidence * 100);
    if (confidence >= 0.9) return { cls: "conf-high", text: `${c}%` };
    if (confidence >= 0.7) return { cls: "conf-mid", text: `${c}%` };
    if (confidence > 0)    return { cls: "conf-low", text: `${c}%` };
    return { cls: "conf-none", text: "—" };
  }, [confidence]);

  const modified = aiValue !== value && !(aiValue == null && (value == null || value === ""));
  const hasPartial = (partialSpans || []).length > 0 && typeof aiValue === "string";
  const hasSuggestion = suggestion != null && suggestion !== "" && suggestion !== value;
  const isIncomplete = isMissing || hasPartial;
  const hasReview = !!isReviewed;
  const origDisplay = originalValue == null || originalValue === "" ? "（空）" : String(originalValue);

  return (
    <div className={
      hasReview
        ? "border-l-2 border-cinnabar-500 pl-2 -ml-2 bg-cinnabar-500/[0.05] py-1"
        : isIncomplete
        ? "border-l-2 border-amber_ink-500 pl-2 -ml-2 bg-amber_ink-500/[0.04] py-1"
        : ""
    }>
      <div className="flex items-center justify-between text-xs mb-0.5">
        <label className="font-serif text-ink-900 flex items-center flex-wrap gap-1">
          <span className={`conf-dot ${conf.cls}`}></span>
          {field.label}
          {hasReview && (
            <span
              className="ml-0.5 text-[9px] tracking-widest uppercase px-1 py-0.5 bg-cinnabar-500 text-paper-50"
              title={reviewReason ? `DeepSeek 修正：${reviewReason}` : "DeepSeek 二次審查已自動修正"}
            >
              DeepSeek 修正
            </span>
          )}
          {isMissing && !hasReview && (
            <span
              className="text-[9px] tracking-widest uppercase px-1 py-0.5 bg-amber_ink-500 text-paper-50"
              title="必填欄位但為空"
            >
              缺
            </span>
          )}
          {hasPartial && !hasReview && (
            <span
              className="text-[9px] tracking-widest uppercase px-1 py-0.5 bg-amber_ink-500/15 text-amber_ink-500 border border-amber_ink-500/40"
              title="AI 部分字符無法辨識"
            >
              局部模糊
            </span>
          )}
        </label>
        <div className="flex items-center gap-2">
          {isAutoFilled && (
            <span className="text-[9px] tracking-widest uppercase px-1.5 py-0.5 border border-cinnabar-500 text-cinnabar-500">
              AI 推測
            </span>
          )}
          {modified && <span className="text-[10px] text-cinnabar-500 tracking-wider uppercase">修</span>}
          <span className="folio">{conf.text}</span>
        </div>
      </div>
      {field.type === "enum" && field.options ? (
        <select className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} onFocus={onFocus} onBlur={onBlur}>
          <option value="">—</option>
          {field.options.map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : field.type === "number" ? (
        <input type="number" className="input" value={value ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
          onFocus={onFocus} onBlur={onBlur} />
      ) : field.type === "date" ? (
        <input type="date" className="input" value={value || ""} onChange={(e) => onChange(e.target.value || null)} onFocus={onFocus} onBlur={onBlur} />
      ) : (
        <input className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value)} onFocus={onFocus} onBlur={onBlur} />
      )}
      {hasReview && (
        <div className="mt-1 flex items-center gap-2 text-[10.5px] leading-relaxed">
          <span className="text-cinnabar-500 shrink-0">✎ DeepSeek 修正：</span>
          <span className="text-ink-400 truncate flex-1" title={reviewReason}>
            {reviewReason || "已根據上下文補全"}
            {reviewedConfidence != null && (
              <span className="ml-1 text-[9px] opacity-60">({Math.round(reviewedConfidence * 100)}%)</span>
            )}
            <span className="ml-2 opacity-60">· Qwen 原值：{origDisplay}</span>
          </span>
          {onRevert && (
            <button
              type="button"
              className="text-[10px] px-1.5 py-0.5 border border-ink-400 text-ink-400 hover:bg-ink-900 hover:text-paper-50 hover:border-ink-900 transition-colors tracking-widest uppercase shrink-0"
              onClick={onRevert}
              title="把該欄位還原為 Qwen 抽取的原值"
            >
              ↶ 撤回
            </button>
          )}
        </div>
      )}
      {hasPartial && !hasReview && (
        <div className="mt-1 text-[10.5px] text-ink-400 leading-relaxed">
          <span className="opacity-60">AI 原讀：</span>
          <HighlightedText text={String(aiValue ?? "")} spans={partialSpans || []} />
        </div>
      )}
      {hasSuggestion && !hasReview && (
        <div className="mt-1 flex items-center gap-2 text-[10.5px] leading-relaxed">
          <span className="text-cinnabar-500">💡 AI 建議：</span>
          <span className="font-mono text-ink-900 truncate flex-1" title={String(suggestion)}>
            {String(suggestion)}
            {suggestionConfidence != null && (
              <span className="ml-1 text-ink-400 text-[9px]">({Math.round(suggestionConfidence * 100)}%)</span>
            )}
          </span>
          <button
            type="button"
            className="text-[10px] px-1.5 py-0.5 border border-cinnabar-500 text-cinnabar-500 hover:bg-cinnabar-500 hover:text-paper-50 transition-colors tracking-widest uppercase"
            onClick={() => onChange(suggestion)}
          >
            採用
          </button>
        </div>
      )}
    </div>
  );
}

function HighlightedText({ text, spans }: { text: string; spans: [number, number][] }) {
  if (!text) return null;
  const sorted = [...spans].sort((a, b) => a[0] - b[0]);
  const out: React.ReactNode[] = [];
  let cursor = 0;
  sorted.forEach(([s, e], i) => {
    if (s > cursor) out.push(<span key={`p${i}`}>{text.slice(cursor, s)}</span>);
    out.push(
      <mark
        key={`m${i}`}
        className="bg-amber_ink-500/30 text-amber_ink-500 px-0.5 rounded-sm"
        title="AI 無法辨識"
      >
        {text.slice(s, e)}
      </mark>
    );
    cursor = e;
  });
  if (cursor < text.length) out.push(<span key="tail">{text.slice(cursor)}</span>);
  return <>{out}</>;
}

function PhotoViewer({
  photoUrl, bbox, focusField, schema,
}: {
  photoUrl: string;
  bbox: Record<string, number[]>;
  focusField: string | null;
  schema: VolunteerField[];
}) {
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);
  const focusBox = focusField ? bbox[focusField] : null;
  const focusLabel = schema.find((s) => s.key === focusField)?.label;

  return (
    <div className="max-w-2xl mx-auto">
      <div className="relative inline-block bg-paper-100 p-2 shadow-sheet">
        <img
          src={photoUrl}
          alt=""
          className="block max-w-full max-h-[calc(100vh-220px)] object-contain"
          onLoad={(e) => {
            const t = e.currentTarget;
            setImgSize({ w: t.clientWidth, h: t.clientHeight });
          }}
        />
        {imgSize && focusBox && focusBox[2] > 0 && (
          <>
            <div
              className="absolute border-2 border-cinnabar-500 transition-all duration-200 pointer-events-none"
              style={{
                left: 8 + focusBox[0] * imgSize.w,
                top: 8 + focusBox[1] * imgSize.h,
                width: focusBox[2] * imgSize.w,
                height: focusBox[3] * imgSize.h,
                boxShadow: "0 0 0 9999px rgba(252,250,243,0.55)",
              }}
            />
            <div
              className="absolute folio text-cinnabar-500 bg-paper-50 px-1.5 py-0.5 pointer-events-none"
              style={{
                left: 8 + focusBox[0] * imgSize.w,
                top: 8 + focusBox[1] * imgSize.h - 18,
              }}
            >
              {focusLabel}
            </div>
          </>
        )}
      </div>
      <p className="folio mt-3 text-center">
        點右側欄位 ⇢ 照片定位 · 滑鼠移開恢復
      </p>
    </div>
  );
}
