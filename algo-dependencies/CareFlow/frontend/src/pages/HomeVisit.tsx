import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, VisitSessionOut } from "../lib/api";
import DropLabel from "../components/DropLabel";
import PipelineIntroModal from "../components/PipelineIntroModal";
import { PIPELINE_INTROS } from "../lib/pipelineIntroContent";
import { STATUS_LABELS, TERMINAL_STATUSES } from "../lib/visitStatus";

type VisitMode = "home_visit" | "internal_meeting";

export default function HomeVisit() {
  const nav = useNavigate();
  const [sessions, setSessions] = useState<VisitSessionOut[]>([]);
  const [mode, setMode] = useState<VisitMode>("home_visit");
  const [title, setTitle] = useState("");
  const [note, setNote] = useState("");
  const [audio, setAudio] = useState<File | null>(null);
  const [template, setTemplate] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [demoLoading, setDemoLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [pollError, setPollError] = useState(false);
  const timer = useRef<number | null>(null);

  const reload = async () => {
    try {
      const r = await api.listVisitSessions();
      setSessions(r.sessions);
      setPollError(false);
    } catch (e) {
      setPollError(true);
    }
  };

  useEffect(() => {
    reload();
  }, []);

  const hasActive = useMemo(
    () => sessions.some((s) => !TERMINAL_STATUSES.has(s.status)),
    [sessions]
  );

  useEffect(() => {
    const start = () => {
      if (timer.current != null) return;
      if (!hasActive) return;
      if (document.visibilityState !== "visible") return;
      timer.current = window.setInterval(reload, 4000);
    };
    const stop = () => {
      if (timer.current != null) {
        window.clearInterval(timer.current);
        timer.current = null;
      }
    };

    start();

    const onVis = () => {
      if (document.visibilityState === "visible") start();
      else stop();
    };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [hasActive]);

  const submit = async () => {
    setErr(null);
    if (!title.trim()) {
      setErr("請填寫個案標題");
      return;
    }
    if (!audio || !template) {
      setErr("請同時選擇錄音檔與報告模板（.docx / .doc）");
      return;
    }
    setSubmitting(true);
    try {
      const created = await api.createVisitSession({ title, note, mode, audio, template });
      setTitle("");
      setNote("");
      setAudio(null);
      setTemplate(null);
      await reload();
      nav(`/home-visit/sessions/${created.id}`);
    } catch (e: any) {
      setErr(e?.message || "建立失敗");
    } finally {
      setSubmitting(false);
    }
  };

  const launchMockDemo = async () => {
    setErr(null);
    setDemoLoading(true);
    try {
      const created = await api.createVisitMockDemo();
      await reload();
      nav(`/home-visit/sessions/${created.id}`);
    } catch (e: any) {
      setErr(e?.message || "Mock 示範啟動失敗");
    } finally {
      setDemoLoading(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto px-10 py-12">
      <PipelineIntroModal intro={PIPELINE_INTROS.beta} />
      {pollError && (
        <div className="mb-3 text-xs text-cinnabar-700 bg-cinnabar-50 border border-cinnabar-500/40 px-3 py-1 inline-block">
          🔌 連線中斷
        </div>
      )}
      <div className="folio">流水線 β</div>
      <h1 className="font-serif text-5xl mt-3 leading-none">语音转录 → 結構化報告</h1>
      <div className="font-serif text-base text-ink-400 mt-2">
        上傳錄音與機構報告模板，AI 將完成轉錄與草擬，所有欄位由同事人手覆核後方可用印渲染。
      </div>
      <div className="rule mt-6"></div>

      {/* 上傳卡 */}
      <section className="mt-10 grid grid-cols-1 lg:grid-cols-12 gap-10">
        <div className="lg:col-span-7">
          <div className="eyebrow mb-4">新案 · 立案</div>
          <div className="space-y-5">
            <div>
              <label className="folio block mb-2">0 · 模式</label>
              <div className="inline-flex border border-ink-900/20">
                {([
                  ["home_visit", "家访语音"],
                  ["internal_meeting", "会议纪要"],
                ] as const).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setMode(value)}
                    className={
                      "px-4 py-2 text-sm transition-colors border-r border-ink-900/20 last:border-r-0 " +
                      (mode === value
                        ? "bg-ink-900 text-paper-50"
                        : "text-ink-700 hover:text-cinnabar-500 hover:bg-paper-100")
                    }
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label className="folio block mb-1">i · 個案標題</label>
              <input
                className="input w-full"
                autoFocus
                placeholder={mode === "home_visit" ? "例：陳婆婆 2026-05 月度家訪" : "例：服務隊 2026-05 月度會議"}
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
            <div>
              <label className="folio block mb-1">ii · 備註（可選）</label>
              <input
                className="input w-full"
                placeholder={mode === "home_visit" ? "例：兒子陪同／著重情緒評估" : "例：跟進下月活動安排"}
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              <div>
                <label className="folio block mb-1">iii · 錄音</label>
                <DropLabel
                  accept=".mp3,.wav,.m4a,.aac,.flac,.ogg,audio/*"
                  onFiles={(f) => setAudio(f[0] || null)}
                  className="block border border-dashed border-ink-900/30 px-4 py-5 cursor-pointer hover:border-cinnabar-500 transition-colors"
                  draggingClassName="border-cinnabar-500 bg-cinnabar-50/40"
                >
                  {audio ? (
                    <div className="text-sm text-ink-700">{audio.name}</div>
                  ) : (
                    <>
                      <div className="font-serif text-2xl text-ink-700">⌇  拖入錄音  ⌇</div>
                      <div className="text-xs text-ink-400 mt-2 tracking-wider">.mp3 / .wav / .m4a · 或 點擊選取</div>
                    </>
                  )}
                  <div className="folio mt-1">支援廣東話 · fun-asr</div>
                </DropLabel>
              </div>
              <div>
                <label className="folio block mb-1">iv · 報告模板</label>
                <DropLabel
                  accept=".docx,.doc"
                  onFiles={(f) => setTemplate(f[0] || null)}
                  className="block border border-dashed border-ink-900/30 px-4 py-5 cursor-pointer hover:border-cinnabar-500 transition-colors"
                  draggingClassName="border-cinnabar-500 bg-cinnabar-50/40"
                >
                  {template ? (
                    <div className="text-sm text-ink-700">{template.name}</div>
                  ) : (
                    <>
                      <div className="font-serif text-2xl text-ink-700">⌇  拖入表格模板  ⌇</div>
                      <div className="text-xs text-ink-400 mt-2 tracking-wider">.docx / .doc · 或 點擊選取</div>
                    </>
                  )}
                  <div className="folio mt-1">機構自家版式 · 完整保留</div>
                </DropLabel>
              </div>
            </div>
            {err && <div className="text-sm text-cinnabar-500">{err}</div>}
            <div className="flex items-center gap-4 flex-wrap">
              <button
                className="btn-stamp"
                onClick={submit}
                disabled={submitting || demoLoading}
              >
                {submitting ? "建立中…" : "送 件 立 案"}
              </button>
              <button
                type="button"
                onClick={launchMockDemo}
                disabled={submitting || demoLoading}
                className="px-4 py-2 border border-ink-900/40 text-sm hover:border-cinnabar-500 hover:text-cinnabar-500 transition-colors disabled:opacity-50"
                title="一鍵載入內建 mock mp3 + docx，全程離線生成示範報告"
              >
                {demoLoading ? "Mock 示範生成中…" : "✦ 一鍵 Mock 示範"}
              </button>
              <span className="folio">
                建檔後將自動啟動轉錄與初稿生成 · 預設模式為家访语音
              </span>
            </div>
          </div>
        </div>

        {/* 隱私守則卡 */}
        <aside className="lg:col-span-5">
          <div className="eyebrow mb-4">隱私 · 信則</div>
          <div className="border-l-2 border-cinnabar-500 pl-4 space-y-3 text-sm leading-relaxed text-ink-700">
            <p>
              <span className="folio mr-2">壹</span>
              錄音稿經 Fernet 加密後落地於後端 vault，<span className="text-cinnabar-500">資料庫不留明文</span>。
            </p>
            <p>
              <span className="folio mr-2">貳</span>
              社工只見 AI 草擬的<strong>結構化欄位</strong>與 200 字內的逐字稿摘要，全文需主管同意方能查閱。
            </p>
            <p>
              <span className="folio mr-2">參</span>
              覆核完成後請按「<strong>閱後即焚</strong>」鈕，逐字稿即以隨機位元覆寫並刪除。
            </p>
            <p>
              <span className="folio mr-2">肆</span>
              所有 AI 輸出皆<span className="stamp-red ml-1">必經人手覆核</span>方可用印渲染 DOCX。
            </p>
          </div>
        </aside>
      </section>

      {/* 案宗列表 */}
      <section className="mt-14">
        <div className="flex items-center justify-between mb-4">
          <div className="eyebrow">案宗 · 流轉</div>
          <div className="folio">共 {sessions.length} 件</div>
        </div>
        {sessions.length === 0 ? (
          <div className="border-t border-b border-ink-900/10 py-12 text-center text-sm text-ink-400">
            尚未立案。請於上方建檔以啟動流水線 β。
          </div>
        ) : (
          <table className="table-archive">
            <thead>
              <tr>
                <th className="w-12">#</th>
                <th>個案標題</th>
                <th className="w-32">狀態</th>
                <th className="w-40">錄音 · 模板</th>
                <th className="w-32">覆核人</th>
                <th className="w-44">最後更新</th>
                <th className="w-24"></th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((s) => {
                const lbl = STATUS_LABELS[s.status] || { zh: s.status, cls: "stamp-ink" };
                return (
                  <tr key={s.id}>
                    <td className="folio">{String(s.id).padStart(3, "0")}</td>
                    <td>
                      <Link
                        to={`/home-visit/sessions/${s.id}`}
                        className="text-ink-900 hover:text-cinnabar-500 underline-offset-4 hover:underline"
                      >
                        {s.title}
                      </Link>
                      {s.note && <div className="text-[11px] text-ink-400 mt-0.5">{s.note}</div>}
                    </td>
                    <td>
                      <span className={lbl.cls}>{lbl.zh}</span>
                      {s.transcript_burned && (
                        <span className="stamp-mute ml-1">焚</span>
                      )}
                    </td>
                    <td className="text-[11px] text-ink-400">
                      <div className="truncate max-w-[12rem]">{s.audio_filename || "—"}</div>
                      <div className="truncate max-w-[12rem]">{s.template_filename || "—"}</div>
                    </td>
                    <td className="text-sm">{s.reviewer || "—"}</td>
                    <td className="folio">{new Date(s.updated_at).toLocaleString("zh-HK")}</td>
                    <td>
                      <Link
                        to={`/home-visit/sessions/${s.id}`}
                        className="folio text-cinnabar-500 hover:underline"
                      >
                        覆核 →
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
