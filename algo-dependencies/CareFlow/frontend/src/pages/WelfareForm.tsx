import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import DropLabel from "../components/DropLabel";
import PipelineIntroModal from "../components/PipelineIntroModal";
import { PIPELINE_INTROS } from "../lib/pipelineIntroContent";

type TplSummary = {
  id: string;
  display_name: string;
  display_name_en?: string;
  source_pdf: string;
  pdf_pages: number;
  fill_strategy: "acroform" | "coord_anchor";
  field_count: number;
  status: "ready" | "pending_coord_mapping";
  notes?: string;
};

type Mapping = {
  key: string;
  label_zh?: string;
  value: string;
  source: "direct" | "default" | "llm" | "missing";
  confidence: number;
  type: string;
  elder_profile_path?: string;
  reason?: string;
};

type Preview = {
  template_id: string;
  display_name: string;
  fill_strategy: "acroform" | "coord_anchor";
  mappings: Mapping[];
  summary: { total: number; direct: number; default: number; llm: number; missing: number };
  used_llm: boolean;
};

const sourceBadge: Record<Mapping["source"], { label: string; cls: string }> = {
  direct: { label: "直接", cls: "bg-paper-200 text-ink-900" },
  default: { label: "預設", cls: "bg-paper-100 text-ink-700" },
  llm: { label: "AI 推測", cls: "bg-amber_ink-50 text-amber_ink-700" },
  missing: { label: "缺", cls: "bg-cinnabar-50 text-cinnabar-700" },
};

export default function WelfareForm() {
  const [list, setList] = useState<TplSummary[] | null>(null);
  const [hasMock, setHasMock] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [useLlm, setUseLlm] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [filling, setFilling] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);

  // v0.4.0-rc2：原始文字 → ElderProfile 抽取
  const [extractOpen, setExtractOpen] = useState(false);
  const [rawText, setRawText] = useState("");
  const [sourceHint, setSourceHint] = useState("社工筆記");
  const [extracting, setExtracting] = useState(false);
  const [extractedProfile, setExtractedProfile] = useState<any>(null);
  const [extractMockMode, setExtractMockMode] = useState(false);
  const [extractErr, setExtractErr] = useState<string | null>(null);
  // v0.4.0-rc3：模式切換 + 照片抽取
  const [extractMode, setExtractMode] = useState<"text" | "image">("text");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);

  useEffect(() => {
    api.listWelfareTemplates()
      .then((r) => {
        setList(r.templates);
        setHasMock(r.has_mock_elder);
        const firstReady = r.templates.find((t) => t.status === "ready");
        if (firstReady) setSelectedId(firstReady.id);
      })
      .catch((e) => setErr(e?.message || "讀取模板失敗"));
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    setOverrides({});
    setResult(null);
    setErr(null);
    setPreviewing(true);
    let cancelled = false;
    api.previewWelfareMapping(selectedId, { use_llm: useLlm, elder_profile: extractedProfile || undefined })
      .then((p) => { if (!cancelled) setPreview(p); })
      .catch((e) => { if (!cancelled) setErr(e?.message || "preview 失敗"); })
      .finally(() => { if (!cancelled) setPreviewing(false); });
    return () => { cancelled = true; };
  }, [selectedId, useLlm, extractedProfile]);

  // N: revoke object URL on unmount / URL change to prevent memory leak
  useEffect(() => {
    return () => {
      if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
    };
  }, [imagePreviewUrl]);

  const selected = useMemo(
    () => list?.find((t) => t.id === selectedId) || null,
    [list, selectedId],
  );

  const effectiveValue = (m: Mapping) =>
    overrides[m.key] !== undefined ? overrides[m.key] : m.value;

  const doExtract = async () => {
    if (!rawText.trim()) return;
    setExtracting(true); setExtractErr(null); setExtractedProfile(null);
    try {
      const r = await api.extractWelfareProfile(rawText, sourceHint);
      setExtractedProfile(r.profile);
      setExtractMockMode(r.mock_mode);
    } catch (e: any) {
      setExtractErr(e?.message || "抽取失敗");
    } finally {
      setExtracting(false);
    }
  };

  const onPickImage = (f: File | null) => {
    setImageFile(f);
    if (imagePreviewUrl) URL.revokeObjectURL(imagePreviewUrl);
    setImagePreviewUrl(f ? URL.createObjectURL(f) : null);
  };

  const doExtractFromImage = async () => {
    if (!imageFile) return;
    setExtracting(true); setExtractErr(null); setExtractedProfile(null);
    try {
      const r = await api.extractWelfareProfileFromImage(imageFile, sourceHint);
      setExtractedProfile(r.profile);
      setExtractMockMode(r.mock_mode);
    } catch (e: any) {
      setExtractErr(e?.message || "照片抽取失敗");
    } finally {
      setExtracting(false);
    }
  };

  const doFill = async () => {
    if (!selectedId) return;
    setFilling(true); setErr(null); setResult(null);
    try {
      const r = await api.fillWelfareForm(selectedId, {
        elder_profile: extractedProfile || undefined,
        overrides: Object.fromEntries(
          Object.entries(overrides).filter(([, v]) => v !== undefined),
        ),
      });
      setResult(r);
    } catch (e: any) {
      setErr(e?.message || "生成失敗");
    } finally {
      setFilling(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto px-10 py-12">
      <PipelineIntroModal intro={PIPELINE_INTROS.gamma} />
      <div className="eyebrow">流水線 γ · 政府福利表</div>
      <h1 className="font-serif text-4xl mt-2">福 利 表 套 組</h1>
      <p className="text-ink-400 text-sm mt-3 max-w-2xl leading-relaxed">
        從預設套組或你透過 <span className="text-cinnabar-500">θ 流水線</span> 上傳的自訂模板中選擇要填寫的表，
        系統會自動把長者個人事實庫（mock 或抽取結果）對應到表格欄位。
        你可在右側手改任何欄位後，一鍵生成 PDF。
      </p>
      <div className="rule mt-6"></div>

      {!hasMock && (
        <div className="mt-6 border-l-2 border-amber_ink-500 pl-3 py-2 text-sm text-amber_ink-700">
          ⚠ 找不到 mock elder profile（data/mock_elder_profile.json）。
        </div>
      )}

      {/* v0.4.0-rc2：原始長者文字 → GPT 抽取 ElderProfile */}
      <div className="mt-6 border border-ink-900/15 bg-paper-50">
        <button
          type="button"
          onClick={() => setExtractOpen((v) => !v)}
          className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-paper-100"
        >
          <div>
            <div className="eyebrow">流水線 γ · 進階</div>
            <div className="font-serif text-lg text-ink-900 mt-0.5">
              從原始文字 AI 抽取長者資料
            </div>
            <div className="text-[11px] text-ink-500 mt-0.5">
              貼上社工筆記 / 病歷 / 個案介紹，AI 會抽成結構化 ElderProfile 再填入表格
            </div>
          </div>
          <div className="text-ink-500 text-sm">
            {extractedProfile && (
              <span className="mr-3 text-sage-700">
                ✓ 已套用：{extractedProfile?.name_zh?.full || extractedProfile?.name_en?.full_upper || "—"}
              </span>
            )}
            {extractOpen ? "▴" : "▾"}
          </div>
        </button>

        {extractOpen && (
          <div className="px-4 pb-4 pt-1 border-t border-ink-900/10">
            {/* v0.4.0-rc3：模式切換 */}
            <div className="mt-3 flex gap-1 border-b border-ink-900/10">
              {(["text", "image"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => setExtractMode(m)}
                  className={
                    "px-4 py-1.5 text-sm border-b-2 -mb-px transition " +
                    (extractMode === m
                      ? "border-ink-900 text-ink-900 font-medium"
                      : "border-transparent text-ink-500 hover:text-ink-800")
                  }
                >
                  {m === "text" ? "純文字" : "照片"}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-12 gap-4 mt-3">
              <div className="col-span-9">
                {extractMode === "text" ? (
                  <textarea
                    value={rawText}
                    onChange={(e) => setRawText(e.target.value)}
                    placeholder="例如：陳婆婆，繁體中文姓名陳淑芬，HKID Z654321(8)，1945 年 6 月 3 日生，女性，喪偶。手機 98765432，家裡電話 22334455。住在屯門兆康苑興康閣 18 樓 1808 室。"
                    rows={6}
                    className="w-full text-sm bg-white border border-ink-900/20 px-3 py-2 font-mono leading-relaxed focus:border-ink-900 outline-none"
                  />
                ) : (
                  <DropLabel
                    accept="image/*"
                    onFiles={(f) => onPickImage(f[0] || null)}
                    className="block border border-dashed border-ink-900/30 bg-white p-3 cursor-pointer transition-colors"
                    draggingClassName="!border-cinnabar-500 !bg-cinnabar-50/40"
                  >
                    <div className="text-sm text-ink-700">
                      {imageFile ? imageFile.name : "拖入照片 · 或 點擊選取"}
                    </div>
                    {imagePreviewUrl ? (
                      <div className="mt-3 flex items-start gap-3">
                        <img
                          src={imagePreviewUrl}
                          alt="預覽"
                          className="max-h-48 max-w-xs border border-ink-900/20"
                        />
                        <div className="text-[11px] text-ink-500">
                          檔案：{imageFile?.name}<br />
                          大小：{imageFile ? Math.round(imageFile.size / 1024) : 0} KB<br />
                          上傳後系統會壓縮並交由 Vision LLM 識讀（HKID、申請表照、社工手寫筆記皆可）。
                        </div>
                      </div>
                    ) : (
                      <div className="text-[11px] text-ink-500 mt-2">
                        支援 JPG / PNG / HEIC（會自動壓縮至 ≤800KB ≤1600px）。
                      </div>
                    )}
                  </DropLabel>
                )}
              </div>
              <div className="col-span-3 flex flex-col gap-2">
                <label className="text-[11px] text-ink-500">資料來源</label>
                <select
                  value={sourceHint}
                  onChange={(e) => setSourceHint(e.target.value)}
                  className="text-sm bg-white border border-ink-900/20 px-2 py-1.5"
                >
                  <option>社工筆記</option>
                  <option>病人卡</option>
                  <option>家屬訪談</option>
                  <option>個案介紹</option>
                  <option>身份證照</option>
                  <option>申請表照</option>
                  <option>其他</option>
                </select>
                <button
                  className="btn-stamp text-sm mt-1"
                  onClick={extractMode === "text" ? doExtract : doExtractFromImage}
                  disabled={
                    extracting ||
                    (extractMode === "text" ? !rawText.trim() : !imageFile)
                  }
                >
                  {extracting ? "AI 抽取中..." : "AI 抽取"}
                </button>
                {extractedProfile && (
                  <button
                    className="text-[11px] text-ink-500 underline mt-1"
                    onClick={() => {
                      setExtractedProfile(null);
                      setExtractMockMode(false);
                    }}
                  >
                    清除，恢復用 mock
                  </button>
                )}
              </div>
            </div>

            {extractErr && (
              <div className="mt-3 border-l-2 border-cinnabar-500 pl-3 py-2 text-xs text-cinnabar-700">
                {extractErr}
              </div>
            )}

            {extractedProfile && (
              <div className="mt-4 bg-white border border-sage-500/40 px-4 py-3">
                <div className="flex items-center justify-between">
                  <div className="font-serif text-base text-sage-700">
                    ✓ 已抽取 — 將套用至下方表格
                  </div>
                  <span className="text-[10px] px-2 py-0.5 rounded bg-paper-200 text-ink-700">
                    {extractMockMode ? "mock 模式" : "DeepSeek LLM"}
                  </span>
                </div>
                <div className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-ink-800">
                  <div>中文姓名：{extractedProfile?.name_zh?.full || "—"}</div>
                  <div>英文姓名：{extractedProfile?.name_en?.full_upper || "—"}</div>
                  <div>HKID：{extractedProfile?.hkid?.full || "—"}</div>
                  <div>出生日期：{extractedProfile?.date_of_birth?.iso || "—"}</div>
                  <div>性別：{extractedProfile?.sex || "—"}</div>
                  <div>婚姻：{extractedProfile?.marital_status || "—"}</div>
                  <div>住宅電話：{extractedProfile?.phone_home?.full || "—"}</div>
                  <div>流動電話：{extractedProfile?.phone_mobile?.full || "—"}</div>
                  <div className="col-span-2">
                    地址：{extractedProfile?.address_text || "—"}
                  </div>
                  {extractedProfile?._extraction && (
                    <div className="col-span-2 text-[10px] text-ink-500 mt-1">
                      信心 {Math.round((extractedProfile._extraction.confidence ?? 0) * 100)}% ·{" "}
                      {extractedProfile._extraction.notes || ""}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>


      <div className="mt-8 grid grid-cols-12 gap-8">
        <aside className="col-span-4">
          {(() => {
            const thetaTpls = (list || []).filter((t) => (t.id || "").startsWith("theta_"));
            const presetTpls = (list || []).filter((t) => !(t.id || "").startsWith("theta_"));
            const renderTpl = (t: TplSummary, isTheta: boolean) => {
              const isSel = t.id === selectedId;
              const ready = t.status === "ready";
              return (
                <li key={t.id}>
                  <button
                    disabled={!ready}
                    onClick={() => ready && setSelectedId(t.id)}
                    className={
                      "w-full text-left px-4 py-3 border transition relative " +
                      (isSel
                        ? "border-ink-900 bg-paper-100"
                        : ready
                        ? "border-ink-900/20 hover:bg-paper-100/60"
                        : "border-ink-900/10 bg-paper-50 opacity-50 cursor-not-allowed")
                    }
                  >
                    {isTheta && (
                      <span className="absolute top-2 right-2 text-[9px] font-mono tracking-widest text-cinnabar-500 border border-cinnabar-500/50 px-1 py-0.5">
                        θ
                      </span>
                    )}
                    <div className="font-serif text-base text-ink-900 pr-8">{t.display_name}</div>
                    {t.display_name_en && (
                      <div className="text-[11px] text-ink-400 mt-0.5">{t.display_name_en}</div>
                    )}
                    <div className="text-[11px] text-ink-500 mt-2 flex gap-2 flex-wrap">
                      <span className="px-1.5 py-0.5 bg-paper-200 rounded">
                        {t.fill_strategy === "acroform" ? "AcroForm" : "坐標模板"}
                      </span>
                      <span>{t.pdf_pages} 頁</span>
                      <span>{t.field_count} 欄</span>
                      {!ready && <span className="text-cinnabar-700">未開放</span>}
                    </div>
                  </button>
                </li>
              );
            };
            return (
              <>
                {thetaTpls.length > 0 && (
                  <>
                    <div className="eyebrow mb-3 flex items-center gap-2">
                      <span>自訂模板</span>
                      <span className="text-cinnabar-500">θ</span>
                      <span className="text-ink-400 font-mono text-[10px]">{thetaTpls.length}</span>
                    </div>
                    <p className="text-[10px] text-ink-400 mb-3 leading-relaxed">
                      由你透過 θ 流水線上傳並審查過的 PDF 模板。標籤已自動對映到長者事實庫；缺欄位可手填或開 DeepSeek 推測。
                    </p>
                    <ul className="space-y-2 mb-6">
                      {thetaTpls.map((t) => renderTpl(t, true))}
                    </ul>
                  </>
                )}
                <div className="eyebrow mb-3 flex items-center gap-2">
                  <span>預設套組</span>
                  <span className="text-ink-400 font-mono text-[10px]">{presetTpls.length}</span>
                </div>
                <ul className="space-y-2">
                  {presetTpls.map((t) => renderTpl(t, false))}
                </ul>
                {thetaTpls.length === 0 && (
                  <div className="mt-6 border border-dashed border-ink-900/15 px-4 py-3 text-[11px] text-ink-400 leading-relaxed">
                    想填寫不在預設清單上的政府或 NGO 表格？
                    <a href="/theta/upload" className="ml-1 text-cinnabar-500 hover:underline">
                      到 θ 流水線上傳自訂 PDF →
                    </a>
                  </div>
                )}
              </>
            );
          })()}
        </aside>

        <section className="col-span-8">
          {!selected && <div className="text-ink-400 text-sm">← 請從左側選擇套組</div>}
          {selected && (
            <>
              <div className="flex items-center justify-between">
                <div>
                  <div className="eyebrow">{selected.id}</div>
                  <h2 className="font-serif text-2xl mt-1">{selected.display_name}</h2>
                </div>
                <label className="text-xs text-ink-700 flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={useLlm}
                    onChange={(e) => setUseLlm(e.target.checked)}
                  />
                  缺欄位用 DeepSeek 推測
                </label>
              </div>

              {previewing && <div className="text-ink-400 text-sm mt-4">⌇ 載入欄位中 ⌇</div>}

              {preview && (
                <>
                  <div className="mt-4 text-xs text-ink-500 flex gap-3">
                    <span>共 {preview.summary.total} 欄</span>
                    <span>直接 {preview.summary.direct}</span>
                    <span>預設 {preview.summary.default}</span>
                    <span>AI {preview.summary.llm}</span>
                    <span>缺 {preview.summary.missing}</span>
                  </div>

                  <div className="mt-4 max-h-[60vh] overflow-y-auto border border-ink-900/10">
                    <table className="w-full text-sm">
                      <thead className="bg-paper-100 text-ink-700 text-xs">
                        <tr>
                          <th className="text-left px-3 py-2 w-1/3">欄位</th>
                          <th className="text-left px-3 py-2">值</th>
                          <th className="text-left px-3 py-2 w-20">來源</th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.mappings.map((m) => {
                          const badge = sourceBadge[m.source];
                          const edited = overrides[m.key] !== undefined;
                          return (
                            <tr key={m.key} className="border-t border-ink-900/5">
                              <td className="px-3 py-2 align-top">
                                <div className="font-medium text-ink-900">{m.label_zh || m.key}</div>
                                <div className="text-[10px] text-ink-400 font-mono">{m.key}</div>
                              </td>
                              <td className="px-3 py-2">
                                <input
                                  className={
                                    "w-full bg-transparent border-b border-ink-900/20 focus:border-ink-900 outline-none px-1 py-0.5 " +
                                    (edited ? "text-amber_ink-700 font-medium" : "")
                                  }
                                  value={effectiveValue(m)}
                                  onChange={(e) =>
                                    setOverrides((o) => ({ ...o, [m.key]: e.target.value }))
                                  }
                                />
                                {m.reason && (
                                  <div className="text-[10px] text-amber_ink-700 mt-1">💡 {m.reason}</div>
                                )}
                              </td>
                              <td className="px-3 py-2">
                                <span className={`text-[10px] px-2 py-0.5 rounded ${badge.cls}`}>
                                  {edited ? "手改" : badge.label}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  <div className="mt-6 flex items-center gap-4">
                    <button className="btn-stamp" onClick={doFill} disabled={filling}>
                      {filling ? "生成中..." : "生成 PDF"}
                    </button>
                    {Object.keys(overrides).length > 0 && (
                      <button
                        className="text-xs text-ink-500 underline"
                        onClick={() => {
                          const n = Object.keys(overrides).length;
                          if (n > 0 && !window.confirm(`清除 ${n} 處手改？此操作不可復原。`)) return;
                          setOverrides({});
                        }}
                      >
                        清除手改 ({Object.keys(overrides).length})
                      </button>
                    )}
                  </div>
                </>
              )}

              {err && (
                <div className="mt-4 border-l-2 border-cinnabar-500 pl-3 py-2 text-sm text-cinnabar-700">
                  {err}
                </div>
              )}

              {result?.ok && (
                <div className="mt-6 border-l-2 border-sage-500 pl-4 py-3">
                  <div className="font-serif text-lg text-sage-700">✓ PDF 已生成</div>
                  <div className="text-xs text-sage-700 mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
                    <div>策略：{result.stats.strategy}</div>
                    <div>耗時：{result.latency_ms}ms</div>
                    {result.stats.filled !== undefined && <div>填入：{result.stats.filled}</div>}
                    {result.stats.ticked !== undefined && <div>勾選：{result.stats.ticked}</div>}
                    {result.stats.empty_value?.length > 0 && (
                      <div className="col-span-2 text-amber_ink-700">
                        空欄：{result.stats.empty_value.join(", ")}
                      </div>
                    )}
                  </div>
                  <div className="mt-3 flex gap-3">
                    <a
                      href={result.download_url}
                      target="_blank"
                      rel="noreferrer"
                      className="btn-stamp"
                    >
                      下載 PDF
                    </a>
                    <span className="text-[11px] text-ink-500 self-center font-mono">
                      {result.output_file}
                    </span>
                  </div>
                  <iframe
                    src={result.download_url}
                    className="w-full h-[600px] mt-4 border border-ink-900/10 bg-white"
                    title="PDF preview"
                  />
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
