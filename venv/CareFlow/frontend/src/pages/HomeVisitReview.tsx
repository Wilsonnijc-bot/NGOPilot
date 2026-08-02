import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, VisitSessionOut } from "../lib/api";
import { STATUS_LABELS } from "../lib/visitStatus";

export default function HomeVisitReview() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const nav = useNavigate();
  const id = Number(sessionId);
  const [s, setS] = useState<VisitSessionOut | null>(null);
  const [reviewer, setReviewer] = useState("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);
  const seededRef = useRef<boolean>(false);

  const load = async () => {
    try {
      const data = await api.getVisitSession(id);
      setS(data);
      if (data.slot_content_final && !seededRef.current) {
        setDraft(data.slot_content_final);
        seededRef.current = true;
      }
    } catch (e: any) {
      setErr(e?.message || "讀取失敗");
    }
  };

  useEffect(() => {
    load();
  }, [id]);

  // poll when ai is still working
  useEffect(() => {
    if (!s) return;
    const inProgress =
      s.status === "uploaded" || s.status === "extracting" || s.status === "rendering";
    if (!inProgress) return;
    const intervalId = window.setInterval(load, 3000);
    return () => window.clearInterval(intervalId);
  }, [s?.status]);

  // re-seed draft once slot_content_final arrives
  useEffect(() => {
    if (s?.slot_content_final && !seededRef.current) {
      setDraft(s.slot_content_final);
      seededRef.current = true;
    }
  }, [s?.slot_content_final]);

  // Escape closes transcript modal
  useEffect(() => {
    if (!showTranscript) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") setShowTranscript(false); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [showTranscript]);

  const slots = useMemo(
    () => s?.template_contract?.dynamic_slots || [],
    [s?.template_contract],
  );
  const fixedBlocks = s?.template_contract?.fixed_blocks || [];

  const submitReview = async () => {
    if (!s) return;
    setBusy(true);
    setErr(null);
    try {
      const updated = await api.reviewVisitSession(s.id, draft, reviewer || undefined);
      setS(updated);
    } catch (e: any) {
      setErr(e?.message || "用印失敗");
    } finally {
      setBusy(false);
    }
  };

  const burn = async () => {
    if (!s) return;
    if (!confirm("確認閱後即焚？逐字稿會以隨機位元覆寫並刪除，不可復原。")) return;
    setBusy(true);
    try {
      await api.burnTranscript(s.id);
      await load();
      setShowTranscript(false);    } catch (e: any) {
      setErr(e?.message || "焚毀失敗");
      await load();    } finally {
      setBusy(false);
    }
  };

  if (!s) {
    return (
      <div className="max-w-3xl mx-auto px-10 py-16 text-center text-ink-400 text-sm">
        {err ? <span className="text-cinnabar-500">{err}</span> : "讀取案宗中…"}
      </div>
    );
  }

  const lbl = STATUS_LABELS[s.status] || { zh: s.status, cls: "stamp-ink" };
  const inFlight = s.status === "uploaded" || s.status === "extracting";

  return (
    <div className="max-w-7xl mx-auto px-10 py-10">
      <div className="flex items-baseline justify-between">
        <div>
          <div className="folio">流水線 β · 案宗 {String(s.id).padStart(3, "0")}</div>
          <h1 className="font-serif text-4xl mt-2 leading-none">{s.title}</h1>
          {s.note && <div className="text-sm text-ink-400 mt-1">{s.note}</div>}
        </div>
        <div className="text-right space-y-1">
          <span className={lbl.cls}>{lbl.zh}</span>
          <div className="folio">
            {s.ai_provider || "—"} · {s.ai_model || "—"}
            {s.ai_latency_ms != null && ` · ${s.ai_latency_ms}ms`}
          </div>
        </div>
      </div>
      <div className="rule mt-5"></div>

      {/* AI 抽取中 */}
      {inFlight && (
        <div className="mt-12 text-center text-sm text-ink-400">
          <div className="folio mb-3">AI · 進行中</div>
          <p>正在抽取錄音逐字、分析模板契約、生成草稿…</p>
          <p className="folio mt-2">本頁每 3 秒自動刷新。</p>
        </div>
      )}

      {s.status === "failed" && (
        <div className="mt-10 border border-cinnabar-500 p-4 text-sm">
          <div className="eyebrow text-cinnabar-500 mb-1">AI 失敗</div>
          <div className="font-mono text-[11px] text-ink-700 whitespace-pre-wrap">{s.ai_error}</div>
        </div>
      )}

      {!inFlight && s.status !== "failed" && (
        <div className="mt-10 grid grid-cols-1 lg:grid-cols-12 gap-10">
          {/* 左：欄位編輯 */}
          <section className="lg:col-span-7">
            <div className="flex items-center justify-between mb-4">
              <div className="eyebrow">人手覆核 · 動態欄位（{slots.length}）</div>
              <button
                className="folio text-cinnabar-500 hover:underline"
                onClick={() => setShowTranscript(true)}
                disabled={s.transcript_burned}
              >
                {s.transcript_burned ? "逐字稿已焚" : "閱 · 錄音稿摘要"}
              </button>
            </div>
            <p className="text-[11px] text-ink-400 mb-5 leading-relaxed">
              下列每一欄皆為 AI 草擬，請仔細覆核並修正後再用印。AI 草稿以
              <span className="text-cinnabar-500"> 朱色標記</span> 提示「需審核」。
            </p>
            <div className="space-y-5">
              {slots.length === 0 && (
                <div className="text-sm text-ink-400">本模板未抽出動態欄位。</div>
              )}
              {slots.map((slot: any, idx: number) => {
                // Renderer + mock keep slot_content keyed by slot_id; only fall
                // back to label when an older contract omitted slot_id.
                const key: string = slot.slot_id || slot.label;
                const displayLabel: string = slot.label || slot.slot_id || `欄位 ${idx + 1}`;
                const aiVal = s.slot_content?.[key] || "";
                const val = draft[key] ?? aiVal;
                const edited = val !== aiVal;
                return (
                  <div key={`${key}-${idx}`} className="border-l-2 border-paper-300 pl-4 hover:border-cinnabar-500 transition-colors">
                    <div className="flex items-baseline justify-between mb-1">
                      <label className="font-serif text-base text-ink-900">{displayLabel}</label>
                      <span className="folio">
                        {edited ? <span className="text-cinnabar-500">已修正</span> : <span className="text-ink-400">AI 草稿</span>}
                      </span>
                    </div>
                    {slot.description && (
                      <div className="text-[11px] text-ink-400 mb-1">{slot.description}</div>
                    )}
                    {slot.section_hint && !slot.description && (
                      <div className="text-[11px] text-ink-400 mb-1">所屬段落：{slot.section_hint}</div>
                    )}
                    <textarea
                      className="w-full bg-transparent border-b border-ink-900/30 focus:border-cinnabar-500 outline-none py-1 text-sm leading-relaxed resize-y min-h-[3em] font-serif"
                      value={val}
                      onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                    />
                  </div>
                );
              })}
            </div>

            {/* 動作列 */}
            <div className="mt-10 border-t border-ink-900/15 pt-6 flex items-end justify-between">
              <div>
                <label className="folio block mb-1">覆核人</label>
                <input
                  className="input w-64"
                  placeholder="社工姓名"
                  value={reviewer}
                  onChange={(e) => setReviewer(e.target.value)}
                />
              </div>
              <div className="flex items-center gap-4">
                {err && <span className="text-sm text-cinnabar-500">{err}</span>}
                <button className="btn-stamp" onClick={submitReview} disabled={busy}>
                  {busy ? "用印中…" : s.status === "confirmed" ? "重 · 用 印" : "用 印 · 渲 染 DOCX"}
                </button>
              </div>
            </div>

            {s.status === "confirmed" && s.download_url && (
              <div className="mt-6 border border-sage-500/40 bg-sage-50/40 px-4 py-3 flex items-center justify-between">
                <div>
                  <div className="eyebrow text-sage-700">已用印 · 可下載</div>
                  <div className="font-mono text-[11px] text-ink-700 mt-1">{s.generated_file}</div>
                </div>
                <a className="folio text-cinnabar-500 hover:underline" href={s.download_url} target="_blank" rel="noreferrer">
                  下載 DOCX →
                </a>
              </div>
            )}
          </section>

          {/* 右：模板契約預覽 */}
          <aside className="lg:col-span-5">
            <div className="eyebrow mb-4">模板契約 · 固定區塊（{fixedBlocks.length}）</div>
            <div className="border border-paper-300 bg-paper-50 p-5 max-h-[60vh] overflow-y-auto">
              {fixedBlocks.length === 0 && (
                <div className="text-sm text-ink-400">此模板未識別到固定區塊。</div>
              )}
              <div className="space-y-3 text-sm leading-relaxed text-ink-400">
                {fixedBlocks.map((b: any, idx: number) => {
                  // Support both schemas: {label,content} (older LLM) and
                  // {block_id,text} (current extractor + mock).
                  const labelText = b.label || "";
                  const bodyText = b.content || b.text || "";
                  return (
                    <div key={idx} className="font-serif">
                      {labelText && <span className="text-ink-900">{labelText}：</span>}
                      {bodyText}
                    </div>
                  );
                })}
              </div>
            </div>
            <p className="folio mt-3">
              固定區塊將原樣寫回 DOCX；動態欄位填入您覆核後的內容。
            </p>

            <div className="mt-8 eyebrow mb-2">案宗 · 元資訊</div>
            <table className="w-full text-[11px] font-mono">
              <tbody>
                <tr><td className="text-ink-400 py-1">建立</td><td>{new Date(s.created_at).toLocaleString("zh-HK")}</td></tr>
                <tr><td className="text-ink-400 py-1">更新</td><td>{new Date(s.updated_at).toLocaleString("zh-HK")}</td></tr>
                <tr><td className="text-ink-400 py-1">錄音</td><td className="truncate max-w-[15rem]">{s.audio_filename || "—"}</td></tr>
                <tr><td className="text-ink-400 py-1">模板</td><td className="truncate max-w-[15rem]">{s.template_filename || "—"}</td></tr>
                <tr><td className="text-ink-400 py-1">覆核人</td><td>{s.reviewer || "—"}</td></tr>
                <tr><td className="text-ink-400 py-1">逐字稿</td><td>{s.transcript_burned ? <span className="stamp-mute">已焚</span> : <span className="stamp-amber">加密在 vault</span>}</td></tr>
              </tbody>
            </table>
          </aside>
        </div>
      )}

      <div className="mt-12">
        <Link to="/home-visit" className="folio text-ink-400 hover:text-cinnabar-500">← 返回案宗列表</Link>
      </div>

      {/* 逐字稿摘要 modal */}
      {showTranscript && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 bg-ink-900/40 z-50 flex items-center justify-center p-8" onClick={() => setShowTranscript(false)}>
          <div className="bg-paper-50 max-w-2xl w-full border border-ink-900/30 shadow-xl p-8" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-baseline justify-between mb-4">
              <div>
                <div className="eyebrow">機密 · 錄音稿摘要</div>
                <div className="folio mt-1">至多 200 字 · 全文需主管授權</div>
              </div>
              <button className="folio text-ink-400 hover:text-cinnabar-500" onClick={() => setShowTranscript(false)}>關 ×</button>
            </div>
            <div className="rule-thin mb-4"></div>
            <div className="font-serif text-sm leading-relaxed text-ink-900 max-h-[40vh] overflow-y-auto whitespace-pre-wrap">
              {s.transcript_snippet || (s.transcript_burned ? "（逐字稿已焚）" : "（無摘要）")}
            </div>
            <div className="rule-thin mt-5 mb-4"></div>
            <div className="flex items-center justify-between">
              <span className="folio text-ink-400">覆核完成後請即焚</span>
              <button
                className="btn-stamp"
                onClick={burn}
                disabled={busy || s.transcript_burned}
              >
                {s.transcript_burned ? "已 · 焚" : "閱 後 · 即 焚"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
