import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { settingsStore } from "../lib/settings";

export default function Settings() {
  const [autoComplete, setAutoComplete] = useState(settingsStore.getAutoComplete());
  const [hvStatus, setHvStatus] = useState<any>(null);
  const [diag, setDiag] = useState<any>(null);
  const [diagBusy, setDiagBusy] = useState(false);
  const [savedField, setSavedField] = useState<string | null>(null);

  useEffect(() => {
    api.homeVisitStatus().then(setHvStatus).catch(() => null);
    return settingsStore.subscribe(() => setAutoComplete(settingsStore.getAutoComplete()));
  }, []);

  const toggleAuto = () => {
    const next = !autoComplete;
    setAutoComplete(next);
    settingsStore.setAutoComplete(next);
    setSavedField("autoComplete");
    setTimeout(() => setSavedField((s) => (s === "autoComplete" ? null : s)), 2000);
  };

  const runDiag = async () => {
    setDiagBusy(true);
    try {
      const r = await api.diagnoseLLM();
      setDiag(r);
    } catch (e: any) {
      setDiag({ error: String(e?.message || e) });
    } finally {
      setDiagBusy(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto px-10 py-12">
      <div className="folio">設 定 · PREFERENCES</div>
      <h1 className="font-serif text-4xl mt-3">案 頭 偏 好</h1>
      <p className="text-ink-400 text-sm mt-3 leading-relaxed">
        所有設定僅儲存於本機瀏覽器（localStorage），不上傳伺服器。
      </p>
      <div className="rule mt-6"></div>

      {/* ── AI 自動補全 ──────────────────────────────────── */}
      <section className="mt-10">
        <div className="eyebrow">流水線 α · 志工紙本</div>
        <h2 className="font-serif text-2xl mt-2">AI 自動補全</h2>
        <div className="rule-thin mt-3 mb-5"></div>

        <article className="border border-paper-300/60 bg-paper-50/60 p-6 flex items-start gap-5">
          <button
            onClick={toggleAuto}
            className={
              "relative shrink-0 w-14 h-7 rounded-full transition-colors duration-200 border " +
              (autoComplete
                ? "bg-cinnabar-500 border-cinnabar-500"
                : "bg-paper-200 border-ink-900/15")
            }
            aria-pressed={autoComplete}
            aria-label="切換自動補全"
          >
            <span
              className={
                "absolute top-0.5 left-0.5 w-6 h-6 rounded-full bg-paper-50 shadow transition-transform duration-200 " +
                (autoComplete ? "translate-x-7" : "translate-x-0")
              }
            ></span>
          </button>
          <div className="flex-1">
            <div className="flex items-baseline justify-between">
              <div className="font-serif text-lg text-ink-900">
                上傳時自動補全不完整欄位
              </div>
              <span
                className={
                  "text-[10px] tracking-widest uppercase px-2 py-0.5 border " +
                  (autoComplete
                    ? "border-cinnabar-500 text-cinnabar-500"
                    : "border-ink-900/20 text-ink-400")
                }
              >
                {autoComplete ? "開啟" : "關閉"}
              </span>
              {savedField === "autoComplete" && (
                <span className="ml-2 text-[11px] text-sage-700">✓ 已儲存於本機</span>
              )}
            </div>
            <p className="text-sm text-ink-700 mt-2 leading-relaxed">
              啟用後，AI 抽取完成的紀錄若有「必填欄位空白」或「低信心欄位」，會立即再次呼叫 LLM，
              根據可見資訊與其他欄位上下文做合理推測，並以
              <span className="stamp-amber mx-1.5">AI 推測</span>
              徽記在審查頁標出。社工仍須人工確認。
            </p>
            <p className="text-[11px] text-ink-400 mt-3">
              本設定僅作用於下一次上傳；已存在的批次可於審查頁手動逐筆按
              <span className="font-mono mx-1">🪄 補全此份</span>。
            </p>
          </div>
        </article>
      </section>

      {/* ── AI 供應商狀態 ────────────────────────────────── */}
      {hvStatus && (
        <section className="mt-12">
          <div className="eyebrow">AI 供應商</div>
          <h2 className="font-serif text-2xl mt-2">當 前 連 線</h2>
          <div className="rule-thin mt-3 mb-5"></div>
          <dl className="grid grid-cols-2 gap-x-10 gap-y-3 text-sm">
            <div className="flex justify-between border-b border-paper-300/60 pb-1.5">
              <dt className="text-ink-400">模式</dt>
              <dd className="font-mono text-ink-900">
                {hvStatus.mock_mode ? "Mock（無 API key）" : "真 實 API"}
              </dd>
            </div>
            <div className="flex justify-between border-b border-paper-300/60 pb-1.5">
              <dt className="text-ink-400">供應商</dt>
              <dd className="font-mono text-ink-900">{hvStatus.provider || "—"}</dd>
            </div>
            <div className="flex justify-between border-b border-paper-300/60 pb-1.5">
              <dt className="text-ink-400">文字模型</dt>
              <dd className="font-mono text-ink-900">{hvStatus.text_model || "—"}</dd>
            </div>
            <div className="flex justify-between border-b border-paper-300/60 pb-1.5">
              <dt className="text-ink-400">視覺模型</dt>
              <dd className="font-mono text-ink-900">{hvStatus.vision_model || "—"}</dd>
            </div>
            <div className="flex justify-between border-b border-paper-300/60 pb-1.5">
              <dt className="text-ink-400">ASR 模型</dt>
              <dd className="font-mono text-ink-900">{hvStatus.asr_model || "—"}</dd>
            </div>
          </dl>
          <p className="text-[11px] text-ink-400 mt-4 leading-relaxed">
            如需切換模型 / 供應商，請編輯 <span className="font-mono">backend/.env</span>，
            重啟 uvicorn 後本頁即會反映。
          </p>
        </section>
      )}

      {/* ── AI 連線自檢 ─────────────────────────────────── */}
      <section className="mt-12">
        <div className="eyebrow">診 斷 · DIAGNOSTICS</div>
        <h2 className="font-serif text-2xl mt-2">AI 連線自檢</h2>
        <div className="rule-thin mt-3 mb-5"></div>
        <article className="border border-paper-300/60 bg-paper-50/60 p-6">
          <div className="flex items-center justify-between">
            <div className="flex-1 pr-4">
              <p className="text-sm text-ink-700 leading-relaxed">
                一鍵測試 <span className="font-mono">DNS / TCP / Text / Vision</span> 四層連線。出現
                <span className="font-mono mx-1">Connection error.</span>
                時用這個面板定位是網路、Key、還是 API 端點問題。
              </p>
              <p className="text-[11px] text-ink-400 mt-2">
                Text 用 <span className="font-mono">"pong"</span> 探活；Vision 用 1×1 透明 PNG 探活。
              </p>
            </div>
            <button
              className="btn-stamp shrink-0"
              disabled={diagBusy}
              onClick={runDiag}
            >
              {diagBusy ? "測試中…" : "開始自檢"}
            </button>
          </div>

          {diag && !diag.error && (
            <div className="mt-5 grid gap-2 text-[12.5px]">
              <DiagRow label="模式" value={diag.is_mock_mode ? "全 Mock" : "三通道獨立"} ok={!diag.is_mock_mode} />
              <DiagRow label="路由" value={diag.provider || "—"} ok={true} />
              <ChannelDiag title="文字 · DeepSeek" item={diag.channels?.text || diag.text} />
              <ChannelDiag title="視覺 · Azure OpenAI" item={diag.channels?.vision || diag.vision} />
              <ChannelDiag title="語音 · Bailian fun-asr" item={diag.channels?.asr || diag.asr} />
              <div className="text-[10px] text-ink-400 mt-1">
                總耗時 {diag.total_ms}ms · {new Date(diag.ts * 1000).toLocaleTimeString("zh-HK", { hour12: false, timeZone: "Asia/Hong_Kong" })} HKT
              </div>
            </div>
          )}
          {diag?.error && (
            <div className="mt-5 text-sm text-cinnabar-500 font-mono">後端錯誤：{diag.error}</div>
          )}
        </article>
      </section>
    </div>
  );
}

function DiagRow({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className="flex items-center justify-between border-b border-paper-300/60 pb-1">
      <span className="text-ink-400 text-[11px] tracking-widest uppercase">{label}</span>
      <span className="font-mono flex items-center gap-2">
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${ok ? "bg-sage-500" : "bg-cinnabar-500"}`}></span>
        <span className="text-ink-900">{value}</span>
      </span>
    </div>
  );
}

function ChannelDiag({ title, item }: { title: string; item: any }) {
  if (!item) return null;
  const status = item.mock ? "MOCK" : item.ok ? "OK" : "FAIL";
  const tone = item.mock ? "text-amber_ink-700" : item.ok ? "text-sage-700" : "text-cinnabar-700";
  const dot = item.mock ? "bg-amber_ink-500" : item.ok ? "bg-sage-500" : "bg-cinnabar-500";
  const net = item.network || {};
  return (
    <div className="border border-paper-300/60 bg-paper-50/70 p-3">
      <div className="flex items-center justify-between">
        <span className="text-ink-400 text-[11px] tracking-widest uppercase">{title}</span>
        <span className="font-mono flex items-center gap-2 text-[11px]">
          <span className={`inline-block w-1.5 h-1.5 rounded-full ${dot}`}></span>
          <span className={tone}>{status}</span>
        </span>
      </div>
      <dl className="grid grid-cols-[5em_1fr] gap-y-0.5 mt-2 text-[11px] font-mono">
        <dt className="text-ink-400">provider</dt><dd className="text-ink-900">{item.provider || "—"}</dd>
        <dt className="text-ink-400">model</dt><dd className="text-ink-900 break-all">{item.deployment ? `${item.model} (deployment: ${item.deployment})` : item.model || "—"}</dd>
        <dt className="text-ink-400">base_url</dt><dd className="text-ink-900 break-all">{item.base_url || "—"}</dd>
        <dt className="text-ink-400">api key</dt><dd className={item.has_key ? "text-ink-900" : "text-amber_ink-500"}>{item.has_key ? "已設定" : "未設定"}</dd>
        <dt className="text-ink-400">network</dt>
        <dd className={net.ok ? "text-ink-900" : "text-cinnabar-500"}>
          {net.ok ? `${net.ip || net.host}:${net.port} · ${net.latency_ms}ms` : (net.error || "FAIL")}
        </dd>
        {("latency_ms" in item) && (<>
          <dt className="text-ink-400">api latency</dt>
          <dd className="text-ink-900">{item.latency_ms}ms</dd>
        </>)}
        {item.reply && (<>
          <dt className="text-ink-400">reply</dt>
          <dd className="text-ink-900 break-all">{item.reply}</dd>
        </>)}
        {item.error && (<>
          <dt className="text-ink-400">error</dt>
          <dd className="text-cinnabar-500 break-all">{item.error}</dd>
        </>)}
      </dl>
    </div>
  );
}
