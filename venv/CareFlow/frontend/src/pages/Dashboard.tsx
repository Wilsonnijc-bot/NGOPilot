import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, BatchOut } from "../lib/api";
import PipelineIntroModal from "../components/PipelineIntroModal";
import { PIPELINE_INTROS } from "../lib/pipelineIntroContent";
import { StatusStamp } from "../components/StatusStamp";

const fmtTime = () =>
  new Date().toLocaleTimeString("zh-HK", {
    hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit",
    timeZone: "Asia/Hong_Kong",
  }) + " HKT";

export default function Dashboard() {
  const [health, setHealth] = useState<any>(null);
  const [recent, setRecent] = useState<BatchOut[]>([]);
  const [template, setTemplate] = useState<any>(null);
  const [sessionTime, setSessionTime] = useState(() => fmtTime());

  useEffect(() => {
    api.health().then(setHealth).catch(() => null);
    api.listBatches({ limit: 5 }).then((r) => setRecent(r.batches)).catch(() => null);
    api.getTemplate().then(setTemplate).catch(() => null);
  }, []);

  useEffect(() => {
    const id = setInterval(() => setSessionTime(fmtTime()), 1000);
    return () => clearInterval(id);
  }, []);

  const today = new Date().toLocaleDateString("zh-HK", {
    year: "numeric", month: "long", day: "numeric", weekday: "long",
    timeZone: "Asia/Hong_Kong",
  });

  return (
    <div className="max-w-6xl mx-auto px-10 py-12">
      <PipelineIntroModal intro={PIPELINE_INTROS.desk} />
      {/* ── Header ─────────────────────────────────────────── */}
      <header className="grid grid-cols-12 gap-6 items-end">
        <div className="col-span-8">
          <div className="eyebrow">工作台 · Desk</div>
          <h1 className="font-serif text-5xl mt-2 leading-tight">
            今日案頭
            <span className="text-cinnabar-500"> .</span>
          </h1>
          <p className="mt-3 text-ink-400 text-sm max-w-lg leading-relaxed">
            一個社工，一張紙，一杯凍奶茶。我們處理表格，您處理人。
          </p>
        </div>
        <div className="col-span-4 text-right">
          <div className="folio">FOLIO · {today}</div>
          <div className="font-mono text-xs text-ink-400 mt-1">
            session · {sessionTime}
          </div>
        </div>
      </header>

      <div className="rule mt-6"></div>

      {/* ── 流水線四章 ─────────────────────────────────────── */}
      <section className="grid grid-cols-12 gap-6 mt-10">
        <PipelineCard
          num="α"
          title="志工紙本表"
          subtitle="→ NGO Excel"
          status="現行版本"
          to="/volunteer/upload"
          stampClass="stamp-red"
          description="拖入手填表，AI 抽取後社工人工審查、按 NGO 模板匯出。"
          primary
        />
        <PipelineCard
          num="θ"
          title="自訂 PDF 表"
          subtitle="→ 可重用模板"
          status="新版"
          to="/theta/upload"
          stampClass="stamp-red"
          description="上傳任意 PDF 空白表單，AI 識別欄位，審查後存為模板。"
          primary
        />
        <PipelineCard
          num="β"
          title="语音转录"
          subtitle="→ 結構化報告"
          status="現行版本"
          to="/home-visit"
          stampClass="stamp-red"
          description="錄音 → 自動轉文字 + 結構化抽取。"
          primary
        />
        <PipelineCard
          num="γ"
          title="政府福利表"
          subtitle="→ 已填寫 PDF"
          status="現行版本"
          to="/welfare-form"
          stampClass="stamp-red"
          description="檔案 OCR + RAG 校驗社署指引 + 半自動填寫。"
          primary
        />
      </section>

      {/* ── 系統 + 模板 + 最近案卷 雙欄 ──────────────────── */}
      <section className="grid grid-cols-12 gap-6 mt-12">
        <div className="col-span-7">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-serif text-xl">最近案卷</h2>
            <Link to="/history" className="text-xs text-ink-400 hover:text-cinnabar-500">
              全部歷史 →
            </Link>
          </div>
          <div className="rule-thin mb-3"></div>
          {recent.length === 0 ? (
            <div className="py-12 text-center text-ink-400 text-sm">
              尚無案卷。試試 <Link to="/volunteer/upload">上傳一批照片</Link>。
            </div>
          ) : (
            <ul className="divide-y divide-paper-300/60">
              {recent.map((b, i) => (
                <li key={b.id}>
                  <Link
                    to={`/history/${b.id}`}
                    className="grid grid-cols-12 gap-3 py-3 hover:bg-paper-100/50 -mx-2 px-2 transition-colors"
                  >
                    <div className="col-span-1 folio pt-1">
                      {String(i + 1).padStart(2, "0")}
                    </div>
                    <div className="col-span-7">
                      <div className="font-serif text-ink-900">{b.title}</div>
                      <div className="text-xs text-ink-400 mt-0.5">
                        {b.volunteer_team || "未指定志工隊"} · {b.total_photos} 張 ·
                        審 <span className="text-ink-700 font-mono">{b.confirmed_count}/{b.total_photos}</span>
                      </div>
                    </div>
                    <div className="col-span-4 text-right">
                      <StatusStamp status={b.status} />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="col-span-5 space-y-6">
          {/* 系統 （rc6.1 三通道） */}
          <div>
            <div className="eyebrow mb-2">系統現況 · 三通道</div>
            <div className="rule-thin mb-3"></div>
            {health ? (
              <div className="space-y-2 text-[12px]">
                <ChannelRow
                  label="文本"
                  provider={health.channels?.text?.provider || "—"}
                  model={health.channels?.text?.model || "—"}
                  mock={!!health.channels?.text?.mock}
                />
                <ChannelRow
                  label="視覺"
                  provider={health.channels?.vision?.provider || "—"}
                  model={health.channels?.vision?.deployment || health.channels?.vision?.model || "—"}
                  mock={!!health.channels?.vision?.mock}
                />
                <ChannelRow
                  label="語音"
                  provider={health.channels?.asr?.provider || "—"}
                  model={health.channels?.asr?.model || "—"}
                  mock={!!health.channels?.asr?.mock}
                />
                <div className="text-[10.5px] text-ink-400 pt-1">
                  任一路缺 key 則該路退回 mock · 其餘兩路不受影響
                </div>
              </div>
            ) : (
              <div className="text-ink-400 text-xs">讀取中…</div>
            )}
          </div>

          {/* 模板 */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="eyebrow">啟用中 · 輸出模板</div>
              <Link to="/templates" className="text-[11px] text-ink-400 hover:text-cinnabar-500">
                管理 →
              </Link>
            </div>
            <div className="rule-thin mb-3"></div>
            {template ? (
              <div className="text-sm">
                <div className="flex items-center gap-2">
                  <span className={template.kind === "user_excel" ? "stamp-red" : "stamp-ink"}>
                    {template.kind === "user_excel" ? "自訂" : "內建"}
                  </span>
                  <span className="text-ink-900 truncate">{template.original_name || template.file}</span>
                </div>
                <div className="text-xs text-ink-400 mt-1">
                  {template.headers?.length || 0} 個欄位 ·
                  匹配 {Object.keys(template.mapping || {}).length} 個
                </div>
              </div>
            ) : (
              <div className="text-ink-400 text-xs">讀取中…</div>
            )}
          </div>
        </div>
      </section>

      <footer className="mt-16 pt-6 border-t border-ink-900/10 flex items-center justify-between text-[11px] text-ink-400">
        <span className="folio">© 2026 · 護流 careflow.ngo</span>
        <span>所有 AI 輸出必經人工審查 · Made with patience, not magic.</span>
      </footer>
    </div>
  );
}

function ChannelRow({
  label, provider, model, mock,
}: { label: string; provider: string; model: string; mock: boolean }) {
  return (
    <div className="flex items-center justify-between border-b border-paper-300/60 pb-1.5">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-ink-400 text-[10px] tracking-widest uppercase w-9 shrink-0">{label}</span>
        <span className="font-mono text-ink-900 truncate">{provider}</span>
        <span className="text-ink-400 font-mono text-[11px] truncate">{model}</span>
      </div>
      {mock ? (
        <span className="stamp-amber text-[10px]">mock</span>
      ) : (
        <span className="stamp-green text-[10px]">live</span>
      )}
    </div>
  );
}

function PipelineCard({
  num, title, subtitle, status, to, stampClass, description, primary,
}: {
  num: string; title: string; subtitle: string; status: string; to: string;
  stampClass: string; description: string; primary?: boolean;
}) {
  return (
    <Link
      to={to}
      className="col-span-12 sm:col-span-6 lg:col-span-3 group block border border-ink-900/10 bg-paper-100/70 hover:border-cinnabar-500/60 transition-colors p-6 relative overflow-hidden"
    >
      <div className="flex items-start justify-between">
        <div className="folio text-xl text-ink-100 group-hover:text-cinnabar-100 transition-colors">
          {num}
        </div>
        <span className={stampClass}>{status}</span>
      </div>
      <div className="mt-8">
        <div className="font-serif text-2xl text-ink-900 leading-tight">{title}</div>
        <div className="font-serif text-base text-ink-400 mt-1">{subtitle}</div>
      </div>
      <p className="text-xs text-ink-400 leading-relaxed mt-4 min-h-[3em]">{description}</p>
      <div className="mt-5 text-xs flex items-center gap-1 text-ink-700 group-hover:text-cinnabar-500 transition-colors">
        {primary ? "立即開始" : "查看詳情"}
        <span className="transition-transform group-hover:translate-x-1">→</span>
      </div>
    </Link>
  );
}
