import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import PipelineIntroModal from "../components/PipelineIntroModal";
import { PIPELINE_INTROS } from "../lib/pipelineIntroContent";

type AnalysisMeta = {
  provider?: string;
  model?: string;
  latency_ms?: number;
  total_pages?: number;
  total_fields?: number;
  is_mock?: boolean;
  last_error?: string | null;
  page_errors?: { page: number; error: string }[];
};

type UploadResult = {
  template: { id: number; name: string; page_count: number };
  fields: unknown[];
  analysis_meta?: AnalysisMeta;
};

export default function ThetaUpload() {
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  // 分析中計時器，讓使用者看到「GPT 真的在跑」
  useEffect(() => {
    if (!busy) return;
    const t0 = Date.now();
    const id = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 250);
    return () => clearInterval(id);
  }, [busy]);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const pdfs = Array.from(e.dataTransfer.files).filter(
      (f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf")
    );
    if (pdfs.length) {
      setFile(pdfs[0]);
      setErr(null);
    }
  };

  const submit = async () => {
    if (!file) {
      setErr("請選擇 PDF 表單檔案");
      return;
    }
    if (!name.trim()) {
      setErr("請填寫模板名稱");
      return;
    }
    setBusy(true);
    setElapsed(0);
    setErr(null);
    setResult(null);
    try {
      const r = (await api.uploadThetaPdf(name.trim(), file, note.trim() || undefined)) as UploadResult;
      setResult(r);
      // 若整份完全失敗（0 欄位且有錯誤），保留在審查頁讓使用者重試
      const meta = r.analysis_meta;
      if (meta && (meta.total_fields ?? 0) === 0 && meta.last_error) {
        setErr(`GPT 分析全頁失敗：${meta.last_error}`);
      }
    } catch (e: any) {
      setErr(e?.message || "上傳失敗");
    } finally {
      setBusy(false);
    }
  };

  // 分析完成後的中介確認頁（顯示 analysis_meta，讓使用者真的看見 GPT 跑過）
  if (result && !err) {
    const m = result.analysis_meta || {};
    const pageErr = m.page_errors || [];
    return (
      <div className="max-w-4xl mx-auto px-10 py-12">
        <div className="eyebrow">流水線 θ · 步驟 1.5 / 3</div>
        <h1 className="font-serif text-4xl mt-2">GPT 已完成審視</h1>
        <p className="text-ink-400 text-sm mt-3 max-w-xl leading-relaxed">
          下列為 GPT-{(m.model || "").includes("5") ? "5-mini" : "vision"} 對此 PDF 的初步審視結果。
          請點擊下方按鈕進入人工審查，校正欄位後方可儲存為模板。
        </p>
        <div className="rule mt-6"></div>

        <div className="mt-8 grid grid-cols-2 gap-x-10 gap-y-4 text-sm font-mono">
          <Meta k="模板 ID" v={String(result.template.id)} />
          <Meta k="模板名稱" v={result.template.name} />
          <Meta k="提供方" v={`${m.provider || "—"}${m.is_mock ? " (mock)" : ""}`} />
          <Meta k="模型" v={m.model || "—"} />
          <Meta k="總頁數" v={String(m.total_pages ?? "—")} />
          <Meta k="識別欄位" v={String(m.total_fields ?? 0)} highlight />
          <Meta k="分析耗時" v={`${((m.latency_ms ?? 0) / 1000).toFixed(1)} 秒`} />
          <Meta k="失敗頁數" v={String(pageErr.length)} warn={pageErr.length > 0} />
        </div>

        {pageErr.length > 0 && (
          <div className="mt-6 border-l-2 border-cinnabar-500 pl-3 text-xs text-cinnabar-700 leading-relaxed max-h-32 overflow-y-auto">
            <div className="font-serif text-sm mb-1">部分頁面分析失敗：</div>
            {pageErr.slice(0, 5).map((p) => (
              <div key={p.page} className="font-mono">
                · 第 {p.page + 1} 頁：{p.error.slice(0, 120)}
              </div>
            ))}
            {pageErr.length > 5 && <div className="font-mono">… 另外 {pageErr.length - 5} 頁</div>}
          </div>
        )}

        <div className="rule-thin mt-8"></div>
        <div className="flex items-center justify-between mt-6">
          <button className="btn-ghost" onClick={() => { setResult(null); setFile(null); }}>
            重新上傳
          </button>
          <button className="btn-stamp" onClick={() => nav(`/theta/audit/${result.template.id}`)}>
            → 進入人工審查
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto px-10 py-12">
      <PipelineIntroModal intro={PIPELINE_INTROS.theta} />
      {/* 全屏分析中遮罩 — 讓使用者明確看到 GPT 真的在跑 */}
      {busy && (
        <div className="fixed inset-0 bg-paper-100/95 backdrop-blur-sm z-50 flex items-center justify-center">
          <div className="max-w-lg text-center px-8">
            <div className="eyebrow">流水線 θ · 分析中</div>
            <h2 className="font-serif text-3xl mt-3">GPT-5-mini 正在逐頁審視 PDF</h2>
            <div className="rule-thin mt-5"></div>
            <div className="mt-6 font-mono text-sm text-ink-700">
              已耗時 <span className="text-cinnabar-600 text-lg">{elapsed}</span> 秒
            </div>
            <div className="mt-2 text-xs text-ink-400 leading-relaxed">
              依 PDF 頁數通常需 20-120 秒；請勿關閉或重新整理頁面。
              <br />
              GPT 將辨識每一頁的空白欄位、標籤、類型與位置座標。
            </div>
            <div className="mt-6 flex justify-center gap-1">
              <span className="w-2 h-2 bg-cinnabar-500 rounded-full animate-pulse"></span>
              <span className="w-2 h-2 bg-cinnabar-500 rounded-full animate-pulse" style={{ animationDelay: "0.2s" }}></span>
              <span className="w-2 h-2 bg-cinnabar-500 rounded-full animate-pulse" style={{ animationDelay: "0.4s" }}></span>
            </div>
          </div>
        </div>
      )}

      <div className="eyebrow">流水線 θ · 步驟 1 / 3</div>
      <h1 className="font-serif text-4xl mt-2">
        立卷 · 上呈表單
      </h1>
      <p className="text-ink-400 text-sm mt-3 max-w-xl leading-relaxed">
        上傳一份 PDF 空白表單。GPT-5-mini 將自動識別所有需填寫的欄位與位置，
        您可在下一步進行審查與調整。
      </p>
      <div className="rule mt-6"></div>

      <section className="mt-8 space-y-7">
        <Field n="i" label="模板名稱" required>
          <input
            className="input text-lg"
            autoFocus
            placeholder="例：機構 X 入會申請表"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>

        <Field n="ii" label="備註（可選）">
          <input
            className="input"
            placeholder="例：2025 版，共 2 頁"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </Field>

        <Field n="iii" label="上傳 PDF 表單" hint="僅接受 .pdf · ≤ 20MB · ≤ 30 頁">
          <label
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`block border border-dashed cursor-pointer transition-all px-8 py-14 text-center
              ${dragging
                ? "border-cinnabar-500 bg-cinnabar-50/40"
                : "border-ink-900/30 bg-paper-100/40 hover:bg-paper-100/80"}`}
          >
            <input
              type="file"
              accept=".pdf"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0] || null;
                if (f && f.size > 20 * 1024 * 1024) { setErr("PDF 不可超過 20MB"); return; }
                setFile(f);
                setErr(null);
              }}
            />
            {file ? (
              <div className="text-left">
                <div className="font-serif text-lg text-ink-900 mb-2">已選取</div>
                <div className="text-sm text-ink-700 font-mono">{file.name}</div>
                <div className="text-xs text-ink-400 mt-1">
                  {(file.size / 1024).toFixed(0)} KB
                </div>
              </div>
            ) : (
              <div>
                <div className="font-serif text-2xl text-ink-700">⌇  拖入 PDF  ⌇</div>
                <div className="text-xs text-ink-400 mt-2 tracking-wider">
                  拖入此處 · 或 點擊選取
                </div>
              </div>
            )}
          </label>
        </Field>

        {err && (
          <div className="border-l-2 border-cinnabar-500 pl-3 text-sm text-cinnabar-700">{err}</div>
        )}

        <div className="rule-thin"></div>

        <div className="flex items-center justify-between">
          <p className="text-[11px] text-ink-400 leading-relaxed max-w-md">
            上傳後 GPT-5-mini 將逐頁分析 PDF，識別所有空白欄位的標籤、類型與位置。
            <span className="text-cinnabar-500">分析結果必經人工審查方可儲存為模板。</span>
          </p>
          <div className="flex gap-3">
            <button className="btn-ghost" onClick={() => { setFile(null); setErr(null); }} disabled={busy}>
              清空
            </button>
            <button className="btn-stamp" onClick={submit} disabled={busy || !file}>
              {busy ? "分析中…" : "立 · 案"}
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

function Field({
  n, label, required, hint, children,
}: {
  n: string; label: string; required?: boolean; hint?: string; children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-12 gap-4">
      <div className="col-span-2 pt-2">
        <span className="folio">§ {n}</span>
        <div className="font-serif text-ink-900 mt-1">
          {label} {required && <span className="text-cinnabar-500">*</span>}
        </div>
        {hint && <div className="text-[10px] text-ink-400 mt-1">{hint}</div>}
      </div>
      <div className="col-span-10">{children}</div>
    </div>
  );
}

function Meta({ k, v, highlight, warn }: { k: string; v: string; highlight?: boolean; warn?: boolean }) {
  return (
    <div className="flex items-baseline gap-3 border-b border-ink-900/10 pb-1">
      <span className="text-ink-400 text-xs uppercase tracking-wider min-w-[5.5rem]">{k}</span>
      <span className={`flex-1 text-right ${highlight ? "text-cinnabar-600 font-serif text-lg" : warn ? "text-cinnabar-600" : "text-ink-900"}`}>
        {v}
      </span>
    </div>
  );
}
