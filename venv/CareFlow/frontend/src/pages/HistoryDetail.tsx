import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../lib/api";
import { StatusStamp } from "../components/StatusStamp";

export default function HistoryDetail() {
  const { batchId } = useParams<{ batchId: string }>();
  const bid = Number(batchId);
  const [data, setData] = useState<any>(null);

  useEffect(() => { api.batchDetail(bid).then(setData).catch(() => null); }, [bid]);

  if (!data) return <div className="p-10 text-ink-400">讀取中…</div>;

  const batch = data.batch;
  const records: any[] = data.records;
  const diff = data.diff_stats;

  return (
    <div className="max-w-6xl mx-auto px-10 py-12">
      <div className="folio">
        <Link to="/history" className="hover:text-cinnabar-500">案卷</Link>
        <span className="mx-2">/</span>
        <span className="text-ink-700">№ {String(bid).padStart(4, "0")}</span>
      </div>

      <header className="mt-4 flex items-end justify-between">
        <div>
          <h1 className="font-serif text-4xl">{batch.title}</h1>
          <p className="text-ink-400 text-sm mt-2">
            {batch.volunteer_team || "未指定志工隊"} · 探訪 {batch.visit_date || "—"} ·
            共 <span className="font-mono text-ink-700">{batch.total_photos}</span> 張 ·
            審 <span className="font-mono text-ink-700">{batch.confirmed_count}/{batch.total_photos}</span>
          </p>
          {batch.note && <p className="text-sm text-ink-400 mt-1">備註：{batch.note}</p>}
        </div>
        <div className="flex flex-col items-end gap-2">
          <StatusStamp status={batch.status} />
          {batch.exported_file && (
            <a className="btn-stamp" href={`/api/files/${batch.exported_file}`}>下載 .xlsx</a>
          )}
          <Link to={`/volunteer/review/${bid}`} className="btn-ghost">續審</Link>
        </div>
      </header>

      <div className="rule mt-6"></div>

      {diff && diff.total_corrections > 0 && (
        <section className="mt-10">
          <div className="eyebrow">本卷 · 人工修正</div>
          <h2 className="font-serif text-2xl mt-2">
            共 <span className="text-cinnabar-500 font-mono">{diff.total_corrections}</span> 處
          </h2>
          <div className="rule-thin mt-3"></div>
          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-x-10 gap-y-6">
            {Object.entries(diff.by_field as Record<string, any>).map(([k, v]: any) => (
              <div key={k}>
                <div className="flex justify-between items-baseline border-b border-paper-300/60 pb-1">
                  <span className="font-serif text-ink-900">{k}</span>
                  <span className="folio">
                    {v.count} 次 · AI 信 <span className="font-mono">{(v.avg_conf * 100).toFixed(0)}%</span>
                  </span>
                </div>
                <ul className="mt-2 space-y-1 text-[11px]">
                  {v.samples?.map((s: any, i: number) => (
                    <li key={i}>
                      <span className="text-cinnabar-500">{s.ai ?? "(空)"}</span>
                      <span className="mx-1 text-ink-400">→</span>
                      <span className="text-sage-700">{s.final ?? "(空)"}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="mt-12">
        <div className="eyebrow">紀錄詳情 · {records.length}</div>
        <div className="rule-thin mt-3 mb-5"></div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {records.map((r, i) => (
            <article key={r.id} className="bg-paper-100/60 border border-paper-300/60">
              <a href={r.photo_url} target="_blank" rel="noreferrer" className="relative block">
                <img src={r.photo_url} className="w-full aspect-[3/4] object-cover" alt="" />
                {r.is_complete === false && (
                  <span className="absolute top-2 right-2 text-[10px] tracking-widest uppercase px-2 py-0.5 bg-amber_ink-500 text-paper-50 font-medium">
                    信息不完整
                  </span>
                )}
                {(r.auto_filled_keys?.length || 0) > 0 && (
                  <span className="absolute bottom-2 right-2 text-[10px] tracking-widest uppercase px-2 py-0.5 bg-cinnabar-500 text-paper-50 font-medium">
                    AI 補全
                  </span>
                )}
              </a>
              <div className="p-4">
                <div className="flex justify-between items-baseline">
                  <span className="folio">№ {String(i + 1).padStart(2, "0")}</span>
                  {r.is_reviewed ? <span className="stamp-green">已審</span> : <span className="stamp-amber">待審</span>}
                </div>
                <div className="font-serif text-ink-900 mt-2">
                  {r.final_fields?.elder_name || "—"}
                  <span className="text-ink-400 text-sm font-sans"> · {r.final_fields?.elder_age || "—"} 歲</span>
                </div>
                <dl className="mt-3 text-[11px] text-ink-400 space-y-0.5">
                  <div><span className="inline-block w-12">志工</span>{r.final_fields?.volunteer_name || "—"}</div>
                  <div><span className="inline-block w-12">情緒</span>{r.final_fields?.mood || "—"}</div>
                  <div><span className="inline-block w-12">跟進</span>{r.final_fields?.follow_up_needed || "—"}</div>
                </dl>
                {r.is_complete === false && ((r.missing_fields?.length || 0) > 0 || Object.keys(r.partial_fields || {}).length > 0) && (
                  <div className="mt-3 pt-2 border-t border-amber_ink-500/30 text-[10px] text-amber_ink-500 leading-snug space-y-0.5">
                    {(r.missing_fields?.length || 0) > 0 && (
                      <div>缺：{(r.missing_fields as string[]).join("、")}</div>
                    )}
                    {Object.keys(r.partial_fields || {}).length > 0 && (
                      <div>模糊：{Object.keys(r.partial_fields || {}).join("、")}</div>
                    )}
                  </div>
                )}
                {r.reviewer && (
                  <div className="mt-3 pt-2 border-t border-paper-300/60 folio">
                    {r.reviewer} · {r.reviewed_at ? new Date(r.reviewed_at).toLocaleString("zh-HK", { hour12: false }) : ""}
                  </div>
                )}
              </div>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
