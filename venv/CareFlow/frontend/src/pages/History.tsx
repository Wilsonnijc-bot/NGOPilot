import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, BatchOut, VisitSessionOut, ThetaTemplateOut } from "../lib/api";
import { StatusStamp } from "../components/StatusStamp";

type Pipeline = "alpha" | "beta" | "theta";

export default function History() {
  const [searchParams, setSearchParams] = useSearchParams();
  const pipeline = (searchParams.get("p") as Pipeline) || "alpha";
  const setPipeline = (p: Pipeline) => setSearchParams((sp) => { sp.set("p", p); return sp; }, { replace: true });
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [team, setTeam] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [batches, setBatches] = useState<BatchOut[]>([]);
  const [visits, setVisits] = useState<VisitSessionOut[]>([]);
  const [thetas, setThetas] = useState<ThetaTemplateOut[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [combined, setCombined] = useState<any>(null);
  const [diffStats, setDiffStats] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  const refresh = async () => {
    const r = await api.listBatches({
      q: q || undefined,
      status: status || undefined,
      volunteer_team: team || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      limit: 100,
    });
    setBatches(r.batches);
  };
  useEffect(() => {
    refresh();
    api.correctionsByField().then(setDiffStats).catch(() => null);
    api.listVisitSessions().then((r) => setVisits(r.sessions || [])).catch(() => setVisits([]));
    api.listThetaTemplates().then((r) => setThetas(r.templates || [])).catch(() => setThetas([]));
  }, []);

  // Debounced re-fetch when filter inputs change
  useEffect(() => {
    const t = setTimeout(() => { refresh(); }, 300);
    return () => clearTimeout(t);
  }, [q, status, team, dateFrom, dateTo]);

  const toggle = (id: number) => {
    const s = new Set(selected);
    s.has(id) ? s.delete(id) : s.add(id);
    setSelected(s);
  };

  const exportCombined = async () => {
    if (selected.size === 0) return;
    setExporting(true);
    setErr(null);
    try {
      const r = await api.exportCombined(
        Array.from(selected),
        `合併匯出 · ${new Date().toISOString().slice(0, 10)}`
      );
      setCombined(r);
    } catch (e: any) {
      setErr(e?.message || "匯出失敗");
    } finally {
      setExporting(false);
    }
  };

  const topCorrected = useMemo(() => {
    if (!diffStats?.by_field) return [];
    return Object.entries(diffStats.by_field as Record<string, any>)
      .sort((a, b) => (b[1].count || 0) - (a[1].count || 0))
      .slice(0, 5);
  }, [diffStats]);

  return (
    <div className="max-w-6xl mx-auto px-10 py-12">
      <div className="flex items-end justify-between">
        <div>
          <div className="eyebrow">卷宗 · 01</div>
          <h1 className="font-serif text-4xl mt-2">歷史 案 卷</h1>
          <p className="text-ink-400 text-sm mt-3 max-w-lg leading-relaxed">
            所有完成過的流水線案卷皆收錄於此，可按管線切換、依條件檢索、批量合併匯出。
          </p>
        </div>
        <Link to="/volunteer/upload" className="btn-stamp">＋ 新立案</Link>
      </div>

      <div className="rule mt-6"></div>

      {/* 管線切換 tabs */}
      <div className="mt-6 flex flex-wrap gap-1 border-b border-ink-900/15">
        {([
          { k: "alpha", label: "α 志工紙本", count: batches.length },
          { k: "beta", label: "β 语音转录", count: visits.length },
          { k: "theta", label: "θ 自訂 PDF 模板", count: thetas.length },
        ] as { k: Pipeline; label: string; count: number }[]).map((t) => (
          <button
            key={t.k}
            onClick={() => setPipeline(t.k)}
            className={
              "px-5 py-2 text-sm border-b-2 -mb-px transition " +
              (pipeline === t.k
                ? "border-cinnabar-500 text-ink-900 font-medium"
                : "border-transparent text-ink-400 hover:text-ink-700")
            }
          >
            {t.label}
            <span className="ml-2 font-mono text-[11px] text-ink-400">{t.count}</span>
          </button>
        ))}
      </div>

      {pipeline === "alpha" && (
        <AlphaSection
          q={q} setQ={setQ}
          status={status} setStatus={setStatus}
          team={team} setTeam={setTeam}
          dateFrom={dateFrom} setDateFrom={setDateFrom}
          dateTo={dateTo} setDateTo={setDateTo}
          batches={batches}
          selected={selected} toggle={toggle}
          exportCombined={exportCombined} exporting={exporting}
          combined={combined}
          refresh={refresh}
          topCorrected={topCorrected}
          err={err}
        />
      )}

      {pipeline === "beta" && <BetaSection visits={visits} />}
      {pipeline === "theta" && <ThetaSection thetas={thetas} />}
    </div>
  );
}

function AlphaSection({
  q, setQ, status, setStatus, team, setTeam, dateFrom, setDateFrom, dateTo, setDateTo,
  batches, selected, toggle, exportCombined, exporting, combined, refresh, topCorrected, err,
}: any) {
  return (
    <>
      {/* 篩選 */}
      <section className="mt-7 grid grid-cols-1 md:grid-cols-6 lg:grid-cols-12 gap-x-6 gap-y-4">
        <div className="col-span-4">
          <div className="eyebrow mb-1">關鍵詞</div>
          <input className="input" placeholder="標題 / 志工隊 / 備註" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <div className="col-span-2">
          <div className="eyebrow mb-1">狀態</div>
          <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">全部</option>
            <option value="uploaded">已上傳</option>
            <option value="extracting">抽取中</option>
            <option value="pending_review">待審</option>
            <option value="confirmed">已審</option>
            <option value="exported">已匯出</option>
          </select>
        </div>
        <div className="col-span-2">
          <div className="eyebrow mb-1">志工隊</div>
          <input className="input" value={team} onChange={(e) => setTeam(e.target.value)} />
        </div>
        <div className="col-span-2">
          <div className="eyebrow mb-1">起</div>
          <input type="date" className="input" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
        </div>
        <div className="col-span-2">
          <div className="eyebrow mb-1">迄</div>
          <input type="date" className="input" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
        </div>
        <div className="col-span-12 flex items-center gap-3 pt-1">
          <button className="btn-ghost" onClick={refresh}>重新整理</button>
          <button
            className="btn-ghost"
            onClick={() => { setQ(""); setStatus(""); setTeam(""); setDateFrom(""); setDateTo(""); }}
          >
            清除
          </button>
          <div className="flex-1" />
          <span className="text-xs text-ink-400">已選 <span className="font-mono text-ink-900">{selected.size}</span> 卷</span>
          <button className="btn-stamp" disabled={selected.size === 0 || exporting} onClick={exportCombined}>
            {exporting ? "匯出中" : "合 · 匯"}
          </button>
        </div>
      </section>

      {err && (
        <div className="mt-5 border-l-2 border-cinnabar-500 pl-3 text-cinnabar-700 text-sm">{err}</div>
      )}

      {combined && (
        <div className="mt-5 border-l-2 border-sage-500 pl-4 py-2 flex items-center justify-between">
          <div className="text-sm text-sage-700">
            已合併 <span className="font-mono">{combined.batch_ids.length}</span> 個案卷
            共 <span className="font-mono">{combined.row_count}</span> 列 → {combined.exported_file}
          </div>
          <a className="btn-stamp" href={combined.download_url}>下載 .xlsx</a>
        </div>
      )}

      {/* 表 */}
      <div className="overflow-x-auto -mx-2 px-2">
      <table className="table-archive mt-8">
        <thead>
          <tr>
            <th className="w-8"></th>
            <th className="w-10">№</th>
            <th>案卷</th>
            <th>志工隊</th>
            <th className="text-center">日期</th>
            <th className="text-center">張數</th>
            <th className="text-center">審查</th>
            <th className="text-center">狀態</th>
            <th className="text-right">立卷時間</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {batches.length === 0 && (
            <tr><td colSpan={10} className="text-center text-ink-400 py-16">尚無案卷</td></tr>
          )}
          {batches.map((b: any, i: number) => (
            <tr key={b.id}>
              <td><input type="checkbox" checked={selected.has(b.id)} onChange={() => toggle(b.id)} /></td>
              <td className="folio">{String(i + 1).padStart(2, "0")}</td>
              <td>
                <Link to={`/history/${b.id}`} className="font-serif text-ink-900 hover:text-cinnabar-500">
                  {b.title}
                </Link>
                {b.note && <div className="text-[11px] text-ink-400 mt-0.5 truncate max-w-md">{b.note}</div>}
              </td>
              <td className="text-ink-700">{b.volunteer_team || "—"}</td>
              <td className="text-center font-mono text-ink-700">{b.visit_date || "—"}</td>
              <td className="text-center font-mono">{b.total_photos}</td>
              <td className="text-center font-mono">{b.confirmed_count}<span className="text-ink-400">/{b.total_photos}</span></td>
              <td className="text-center"><StatusStamp status={b.status} /></td>
              <td className="text-right font-mono text-[11px] text-ink-400">
                {new Date(b.created_at).toLocaleString("zh-HK", { hour12: false })}
              </td>
              <td className="text-right">
                <Link to={`/history/${b.id}`} className="text-xs">查 →</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>

      {/* 修正 top 5 */}
      {topCorrected.length > 0 && (
        <section className="mt-12">
          <div className="eyebrow">修正報告 · 跨案卷</div>
          <h2 className="font-serif text-2xl mt-2">AI 最常出錯的五個欄位</h2>
          <div className="rule-thin mt-3"></div>
          <div className="overflow-x-auto -mx-2 px-2">
          <table className="table-archive mt-4">
            <thead>
              <tr>
                <th>欄位</th>
                <th className="text-center w-24">修正次數</th>
                <th className="text-center w-28">其中低信心</th>
                <th>樣本</th>
              </tr>
            </thead>
            <tbody>
              {topCorrected.map(([k, v]: any) => (
                <tr key={k}>
                  <td className="font-serif text-ink-900">{k}</td>
                  <td className="text-center font-mono">{v.count}</td>
                  <td className="text-center font-mono text-cinnabar-500">{v.low_conf_count}</td>
                  <td className="text-[11px] text-ink-400">
                    {v.samples?.slice(0, 2).map((s: any, i: number) => (
                      <div key={i}>
                        <span className="text-cinnabar-500">「{s.ai ?? "(空)"}」</span>
                        <span className="mx-1">→</span>
                        <span className="text-sage-700">「{s.final ?? "(空)"}」</span>
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </section>
      )}
    </>
  );
}

function BetaSection({ visits }: { visits: VisitSessionOut[] }) {
  return (
    <section className="mt-8">
      <div className="eyebrow mb-1">语音转录 → 結構化報告</div>
      <p className="text-xs text-ink-400 mb-4">所有 β 流水線跑過的語音 session。點擊進入審查 / 下載 .docx。</p>
      {visits.length === 0 ? (
        <div className="py-16 text-center text-ink-400 text-sm">
          尚無家訪案卷。<Link to="/home-visit" className="underline">立即開始</Link>
        </div>
      ) : (
        <div className="overflow-x-auto -mx-2 px-2">
        <table className="table-archive">
          <thead>
            <tr>
              <th className="w-10">№</th>
              <th>標題</th>
              <th className="text-center">狀態</th>
              <th className="text-center">模型</th>
              <th className="text-center">耗時</th>
              <th className="text-right">建立</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {visits.map((v, i) => (
              <tr key={v.id}>
                <td className="folio">{String(i + 1).padStart(2, "0")}</td>
                <td>
                  <Link to={`/home-visit/sessions/${v.id}`} className="font-serif text-ink-900 hover:text-cinnabar-500">
                    {v.title}
                  </Link>
                  {v.note && <div className="text-[11px] text-ink-400 mt-0.5 truncate max-w-md">{v.note}</div>}
                  {v.transcript_burned && (
                    <span className="ml-2 text-[10px] tracking-widest uppercase text-sage-700">逐字稿已銷毀</span>
                  )}
                </td>
                <td className="text-center">
                  <StatusStamp status={v.status} />
                </td>
                <td className="text-center font-mono text-[11px] text-ink-700">{v.ai_model || "—"}</td>
                <td className="text-center font-mono text-[11px] text-ink-700">
                  {v.ai_latency_ms ? `${(v.ai_latency_ms / 1000).toFixed(1)}s` : "—"}
                </td>
                <td className="text-right font-mono text-[11px] text-ink-400">
                  {new Date(v.created_at).toLocaleString("zh-HK", { hour12: false })}
                </td>
                <td className="text-right">
                  {v.download_url ? (
                    <a href={v.download_url} className="text-xs text-cinnabar-500 hover:underline">下載 →</a>
                  ) : (
                    <Link to={`/home-visit/sessions/${v.id}`} className="text-xs">查 →</Link>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </section>
  );
}

function ThetaSection({ thetas }: { thetas: ThetaTemplateOut[] }) {
  return (
    <section className="mt-8">
      <div className="eyebrow mb-1">自訂 PDF 表單模板</div>
      <p className="text-xs text-ink-400 mb-4">所有透過 θ 流水線上傳並審查過的 PDF 模板。可重複用於福利表填寫 (γ) 流程。</p>
      {thetas.length === 0 ? (
        <div className="py-16 text-center text-ink-400 text-sm">
          尚無自訂模板。<Link to="/theta/upload" className="underline">立即上傳</Link>
        </div>
      ) : (
        <div className="overflow-x-auto -mx-2 px-2">
        <table className="table-archive">
          <thead>
            <tr>
              <th className="w-10">№</th>
              <th>模板名稱</th>
              <th className="text-center">頁數</th>
              <th className="text-center">欄位</th>
              <th className="text-center">狀態</th>
              <th className="text-right">建立</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {thetas.map((t, i) => (
              <tr key={t.id}>
                <td className="folio">{String(i + 1).padStart(2, "0")}</td>
                <td>
                  <Link to={`/theta/audit/${t.id}`} className="font-serif text-ink-900 hover:text-cinnabar-500">
                    {t.name}
                  </Link>
                  {t.note && <div className="text-[11px] text-ink-400 mt-0.5 truncate max-w-md">{t.note}</div>}
                  {t.original_pdf_filename && (
                    <div className="text-[10px] text-ink-400 mt-0.5 font-mono">{t.original_pdf_filename}</div>
                  )}
                </td>
                <td className="text-center font-mono">{t.page_count}</td>
                <td className="text-center font-mono">{t.field_count ?? "—"}</td>
                <td className="text-center">
                  <span className={t.status === "ready" ? "stamp-green" : "stamp-amber"}>{t.status}</span>
                </td>
                <td className="text-right font-mono text-[11px] text-ink-400">
                  {new Date(t.created_at).toLocaleString("zh-HK", { hour12: false })}
                </td>
                <td className="text-right">
                  <Link to={`/theta/audit/${t.id}`} className="text-xs">審 →</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </section>
  );
}
