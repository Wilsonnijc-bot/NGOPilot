import { useEffect, useState } from "react";
import { api } from "../lib/api";
import DropLabel from "../components/DropLabel";

export default function Templates() {
  const [tpl, setTpl] = useState<any>(null);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [mappingSaved, setMappingSaved] = useState(false);

  const refresh = () => api.getTemplate().then(setTpl);
  useEffect(() => { refresh(); }, []);

  const upload = async () => {
    if (!file) return;
    setBusy(true); setErr(null); setMsg(null);
    try {
      await api.uploadTemplate(file);
      setMsg(`已啟用：${file.name}`);
      setFile(null);
      await refresh();
    } catch (e: any) {
      setErr(e?.message || "上傳失敗");
    } finally { setBusy(false); }
  };

  const reset = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      await api.resetTemplate();
      setMsg("已回退至內建模板");
      await refresh();
    } catch (e: any) {
      setErr(e?.message || "失敗");
    } finally { setBusy(false); }
  };

  const updateMapping = async (newMapping: Record<string, string>) => {
    setBusy(true);
    setErr(null);
    try {
      await api.updateTemplateMapping(newMapping);
      await refresh();
      setMappingSaved(true);
      setTimeout(() => setMappingSaved(false), 2000);
    } catch (e: any) {
      setErr(e?.message || "儲存失敗");
    } finally { setBusy(false); }
  };

  return (
    <div className="max-w-5xl mx-auto px-10 py-12">
      <div className="eyebrow">卷宗 · 02</div>
      <h1 className="font-serif text-4xl mt-2">輸出 模 板</h1>
      <p className="text-ink-400 text-sm mt-3 max-w-xl leading-relaxed">
        匯出 Excel 時以此模板為樣式。上傳貴機構的範本（.xlsx 第 1 列為標題），
        系統將自動把 AI 抽取出的欄位對應到對應的欄位。
      </p>
      <div className="rule mt-6"></div>

      {/* 上傳區 */}
      <section className="mt-8 grid grid-cols-12 gap-8">
        <div className="col-span-7">
          <div className="eyebrow mb-2">上傳新模板</div>
          <DropLabel
            accept=".xlsx,.xls"
            onFiles={(f) => setFile(f[0] || null)}
            className="block border border-dashed border-ink-900/30 bg-paper-100/40 hover:bg-paper-100/80 transition-colors px-6 py-10 text-center cursor-pointer"
            draggingClassName="!border-cinnabar-500 !bg-cinnabar-50/40"
          >
            {!file ? (
              <div>
                <div className="font-serif text-xl text-ink-900">⌇  拖入紙頁  ⌇</div>
                <div className="text-xs text-ink-400 mt-2 tracking-wider">.xlsx · 或 點擊選取</div>
              </div>
            ) : (
              <div className="font-serif text-lg text-ink-900">
                {file.name}
                <div className="text-[11px] text-ink-400 mt-1 font-sans">{(file.size / 1024).toFixed(0)} KB</div>
              </div>
            )}
          </DropLabel>
          <div className="mt-4 flex gap-3">
            <button className="btn-stamp" onClick={upload} disabled={!file || busy}>啟用此模板</button>
            <button className="btn-ghost" onClick={reset} disabled={busy}>回退內建</button>
          </div>
          {msg && <div className="mt-3 border-l-2 border-sage-500 pl-3 text-sage-700 text-sm">{msg}</div>}
          {err && <div className="mt-3 border-l-2 border-cinnabar-500 pl-3 text-cinnabar-700 text-sm">{err}</div>}
        </div>

        <div className="col-span-5">
          <div className="eyebrow mb-2">啟用中</div>
          <div className="rule-thin mb-3"></div>
          {tpl ? (
            <dl className="text-sm space-y-1.5">
              <div className="flex gap-2">
                <dt className="w-20 text-ink-400">類型</dt>
                <dd>
                  <span className={tpl.kind === "user_excel" ? "stamp-red" : "stamp-ink"}>
                    {tpl.kind === "user_excel" ? "自訂 Excel" : tpl.kind === "user_image" ? "上傳照片" : "內建"}
                  </span>
                </dd>
              </div>
              <div className="flex gap-2"><dt className="w-20 text-ink-400">名稱</dt><dd className="font-mono text-ink-900">{tpl.original_name || tpl.file}</dd></div>
              <div className="flex gap-2"><dt className="w-20 text-ink-400">標題列</dt><dd className="font-mono">{tpl.headers?.length || 0} 個欄位</dd></div>
              <div className="flex gap-2"><dt className="w-20 text-ink-400">已匹配</dt><dd className="font-mono">{Object.keys(tpl.mapping || {}).length} 個</dd></div>
              {tpl.uploaded_at && <div className="flex gap-2"><dt className="w-20 text-ink-400">上傳</dt><dd className="font-mono text-[11px]">{tpl.uploaded_at}</dd></div>}
              {tpl.note && <div className="text-[11px] text-ink-400 mt-2 leading-relaxed">{tpl.note}</div>}
            </dl>
          ) : (
            <div className="text-ink-400 text-sm">讀取中…</div>
          )}
        </div>
      </section>

      {/* 映射表 */}
      {tpl?.headers && tpl.headers.length > 0 && (
        <section className="mt-12">
          <div className="eyebrow">欄位對應</div>
          <h2 className="font-serif text-2xl mt-2">
            模板欄 → 系統欄位
            {busy && <span className="ml-3 text-sm text-ink-400 align-middle">· 儲存中…</span>}
            {mappingSaved && !busy && <span className="ml-3 text-sm text-sage-700 align-middle">✓ 已儲存</span>}
          </h2>
          <p className="text-[11px] text-ink-400 mt-1">下拉修改後即時生效。留空表示該欄不寫入。</p>
          <div className="rule-thin mt-3"></div>
          <table className="table-archive mt-4">
            <thead>
              <tr>
                <th className="w-12">№</th>
                <th>模板標題（Excel 第 1 列）</th>
                <th className="w-72">對應到</th>
              </tr>
            </thead>
            <tbody>
              {tpl.headers.map((h: string, i: number) => (
                <tr key={`${h}-${i}`}>
                  <td className="folio">{String(i + 1).padStart(2, "0")}</td>
                  <td className="font-serif text-ink-900">{h || <span className="text-ink-400">(空)</span>}</td>
                  <td>
                    <select
                      className="input"
                      value={tpl.mapping?.[String(i + 1)] || ""}
                      onChange={(e) => {
                        const map = { ...(tpl.mapping || {}) };
                        if (e.target.value) map[String(i + 1)] = e.target.value;
                        else delete map[String(i + 1)];
                        updateMapping(map);
                      }}
                    >
                      <option value="">— 不對應 —</option>
                      {tpl.schema_keys?.map((k: string) => (
                        <option key={k} value={k}>{tpl.schema_labels?.[k] || k}（{k}）</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
