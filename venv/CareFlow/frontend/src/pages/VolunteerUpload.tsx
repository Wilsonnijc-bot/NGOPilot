import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import PipelineIntroModal from "../components/PipelineIntroModal";
import { PIPELINE_INTROS } from "../lib/pipelineIntroContent";
import { settingsStore } from "../lib/settings";

export default function VolunteerUpload() {
  const nav = useNavigate();
  const [title, setTitle] = useState(
    () => `${new Date().toISOString().slice(0, 10)} 志工探訪批次`
  );
  const [team, setTeam] = useState("");
  const [visitDate, setVisitDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [autoComplete, setAutoComplete] = useState(settingsStore.getAutoComplete());
  useEffect(() => settingsStore.subscribe(() => setAutoComplete(settingsStore.getAutoComplete())), []);

  const submit = async () => {
    if (files.length === 0) {
      setErr("請至少選一張照片");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const batch = await api.createBatch({
        title,
        volunteer_team: team || undefined,
        visit_date: visitDate || undefined,
        note: note || undefined,
      });
      await api.uploadPhotos(batch.id, files, true, autoComplete);
      nav(`/volunteer/review/${batch.id}`);
    } catch (e: any) {
      setErr(e?.message || "上傳失敗");
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const fs = Array.from(e.dataTransfer.files).filter((f) => f.type.startsWith("image/"));
    if (fs.length) setFiles((prev) => [...prev, ...fs]);
  };

  return (
    <div className="max-w-4xl mx-auto px-10 py-12">
      <PipelineIntroModal intro={PIPELINE_INTROS.alpha} />
      <div className="eyebrow">流水線 α · 步驟 1 / 3</div>
      <h1 className="font-serif text-4xl mt-2">
        立卷 · 收 紙
      </h1>
      <p className="text-ink-400 text-sm mt-3 max-w-xl leading-relaxed">
        為本次探訪建立案卷封面，並把所有手填表照片放進來。
        建議單批 ≤ 20 張，照片越清晰、AI 抽取越準。
      </p>
      <div className="rule mt-6"></div>

      <section className="mt-8 space-y-7">
        <Field n="i" label="案卷標題" required>
          <input className="input text-lg" autoFocus value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>

        <div className="grid grid-cols-2 gap-8">
          <Field n="ii" label="志工隊">
            <input className="input" placeholder="例：中大義工隊" value={team} onChange={(e) => setTeam(e.target.value)} />
          </Field>
          <Field n="iii" label="探訪日期">
            <input type="date" className="input" value={visitDate} onChange={(e) => setVisitDate(e.target.value)} />
          </Field>
        </div>

        <Field n="iv" label="備註">
          <textarea
            className="input min-h-[80px]"
            placeholder="任務說明，例：第 3 期獨居長者關懷"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </Field>

        <Field n="v" label="收文" hint="JPG / PNG，可一次拖入多張">
          <label
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            className={`block border border-dashed cursor-pointer transition-all
              ${dragging
                ? "border-cinnabar-500 bg-cinnabar-50/40"
                : "border-ink-900/30 bg-paper-100/40 hover:bg-paper-100/80"}
              px-8 py-14 text-center`}
          >
            <input
              type="file"
              multiple
              accept="image/*"
              className="hidden"
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
            />
            {files.length === 0 ? (
              <div>
                <div className="font-serif text-2xl text-ink-700">⌇  將紙頁  ⌇</div>
                <div className="text-xs text-ink-400 mt-2 tracking-wider">
                  拖入此處 · 或 點擊選取
                </div>
              </div>
            ) : (
              <div className="text-left">
                <div className="font-serif text-lg text-ink-900 mb-2">
                  已收文 <span className="font-mono">{files.length}</span> 份
                </div>
                <ul className="text-xs text-ink-400 columns-2 gap-x-6 max-h-48 overflow-y-auto">
                  {files.map((f, i) => (
                    <li key={f.name + i} className="truncate py-0.5">
                      <span className="folio mr-2">{String(i + 1).padStart(2, "0")}</span>
                      {f.name}
                    </li>
                  ))}
                </ul>
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
            上傳後系統自動觸發 Qwen3.6-Plus 視覺抽取（並行 4 條）。
            <span className="text-cinnabar-500">  所有結果必經人工審查方可匯出 Excel。</span>
            <br />
            自動補全：
            {autoComplete ? (
              <span className="text-cinnabar-500 font-medium">已開啟</span>
            ) : (
              <span className="text-ink-700">未開啟</span>
            )}
            <Link to="/settings" className="ml-2 underline hover:text-cinnabar-500">設定 →</Link>
          </p>
          <div className="flex gap-3">
            <button
              className="btn-ghost"
              onClick={() => {
                if (files.length > 3 && !window.confirm(`清空 ${files.length} 張？`)) return;
                setFiles([]); setErr(null);
              }}
              disabled={busy}
            >
              清空
            </button>
            <button className="btn-stamp" onClick={submit} disabled={busy}>
              {busy ? "收文中…" : "立 · 案"}
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
