import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ThetaFieldDef, ThetaTemplateOut } from "../lib/api";

const FIELD_TYPES = ["text", "number", "date", "checkbox", "signature", "select"];

export default function ThetaAudit() {
  const { templateId } = useParams<{ templateId: string }>();
  const tid = Number(templateId);

  const [tmpl, setTmpl] = useState<ThetaTemplateOut | null>(null);
  const [fields, setFields] = useState<ThetaFieldDef[]>([]);
  const [activePage, setActivePage] = useState(0);
  const [selectedFieldIdx, setSelectedFieldIdx] = useState<number | null>(null);
  const [imgSize, setImgSize] = useState<{ w: number; h: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [showLlmGhost, setShowLlmGhost] = useState(true);  // rc6.8：雙框模式 toggle，預設開

  useEffect(() => {
    api.getThetaTemplate(tid).then((r) => {
      setTmpl(r.template);
      setFields(r.fields);
      // 自動跳到第一個有欄位的頁面（避免使用者預設停在空白頁誤以為「0 欄位」）
      if (r.fields.length > 0) {
        const firstWithFields = r.fields[0].page_number;
        setActivePage(firstWithFields);
      }
    }).catch((e) => setError(e?.message || "載入失敗"));
  }, [tid]);

  const pageFields = fields.filter((f) => f.page_number === activePage);

  const updateField = (idx: number, patch: Partial<ThetaFieldDef>) => {
    setFields((prev) => prev.map((f, i) => (i === idx ? { ...f, ...patch } : f)));
  };

  const deleteField = (idx: number) => {
    setFields((prev) => prev.filter((_, i) => i !== idx));
    setSelectedFieldIdx(null);
  };

  const addField = (bbox: number[], pageNum: number) => {
    const label = window.prompt("請輸入此欄位的標籤名稱：");
    if (!label) return;
    const rand =
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID().slice(0, 8)
        : Math.random().toString(36).slice(2, 10);
    const key = label
      .replace(/[^\w\s]/g, "")
      .replace(/\s+/g, "_")
      .toLowerCase()
      .replace(/[^a-z0-9_]/g, "_")
      .slice(0, 40) || `field_${rand}`;
    const newField: ThetaFieldDef = {
      page_number: pageNum,
      key,
      label,
      type: "text",
      bbox,
      confidence: 1.0,
    };
    setFields((prev) => {
      const next = [...prev, newField];
      setSelectedFieldIdx(next.length - 1);
      return next;
    });
  };

  const saveTemplate = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.updateThetaTemplate(tid, {
        name: tmpl?.name,
        fields: fields.map((f) => ({
          key: f.key,
          label: f.label,
          type: f.type,
          bbox: f.bbox,
          confidence: f.confidence,
          page_number: f.page_number,
        })),
      });
      setTmpl(r.template);
      setFields(r.fields);
      setSaved(true);
    } catch (e: any) {
      setError(e?.message || "儲存失敗");
    } finally {
      setBusy(false);
    }
  };

  const selectedField = selectedFieldIdx != null ? fields[selectedFieldIdx] : null;

  if (!tmpl) {
    return <div className="p-10 text-ink-400">讀取中…</div>;
  }

  return (
    <div className="flex flex-col h-screen">
      {/* ── 頂條 ────────────────────────────────────────── */}
      <header className="border-b border-ink-900/15 px-8 py-4 bg-paper-50/80 backdrop-blur flex items-center gap-5">
        <Link to="/" className="folio text-ink-400 hover:text-cinnabar-500">← 工作台</Link>
        <div className="flex-1 min-w-0">
          <div className="eyebrow">流水線 θ · 步驟 2 / 3 · 審查欄位</div>
          <div className="font-serif text-xl truncate text-ink-900 mt-0.5">{tmpl.name}</div>
        </div>
        <div className="text-xs text-ink-400">
          共 <span className="font-mono text-ink-900">{fields.length}</span> 欄位
          {fields.length > 0 && tmpl.page_count > 1 && (
            <span className="ml-2 text-ink-400/70">
              · 本頁 <span className="font-mono text-ink-900">{pageFields.length}</span>
            </span>
          )}
        </div>
        {saved && (
          <span className="stamp-green">已儲存</span>
        )}
        <button
          className="btn-stamp"
          disabled={busy}
          onClick={saveTemplate}
        >
          {busy ? "儲存中…" : "確認 · 儲存模板"}
        </button>
      </header>

      {error && (
        <div className="border-b border-cinnabar-500/50 bg-cinnabar-50/40 text-cinnabar-700 text-sm px-8 py-2">
          {error}
        </div>
      )}

      {/* ── 三欄主區 ────────────────────────────────────── */}
      <div className="flex-1 grid grid-cols-12 overflow-hidden">
        {/* 左：頁面縮圖 */}
        <aside className="col-span-2 border-r border-ink-900/10 overflow-y-auto bg-paper-100/40 py-3">
          {Array.from({ length: tmpl.page_count }, (_, i) => (
            <button
              key={i}
              className={`w-full text-left px-4 py-2.5 transition-colors flex items-center gap-3
                ${i === activePage ? "bg-paper-50 border-l-2 border-cinnabar-500" : "border-l-2 border-transparent hover:bg-paper-100/60"}`}
              onClick={() => { setActivePage(i); setSelectedFieldIdx(null); }}
            >
              <span className="folio pt-0.5">{String(i + 1).padStart(2, "0")}</span>
              <div className="flex-1 min-w-0">
                <div className="aspect-[3/4] bg-paper-200 overflow-hidden">
                  <img
                    src={api.thetaPageImageUrl(tid, i)}
                    className="w-full h-full object-cover"
                    alt={`Page ${i + 1}`}
                  />
                </div>
                <div className="text-[10px] mt-1 text-ink-400">
                  {fields.filter((f) => f.page_number === i).length} 欄位
                </div>
              </div>
            </button>
          ))}
        </aside>

        {/* 中：PDF 頁面 + 可拖曳 bbox */}
        <div className="col-span-6 overflow-auto p-8 bg-paper-50/40">
          {/* rc6.8：雙框模式 toggle —— 顯示 LLM 原 bbox（藍虛線） + refined bbox（紅實線）*/}
          {fields.some((f) => f.refined) && (
            <label className="flex items-center gap-2 mb-3 text-xs text-ink-900/70 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={showLlmGhost}
                onChange={(e) => setShowLlmGhost(e.target.checked)}
                className="accent-cinnabar-500"
              />
              <span>顯示 LLM 原始 bbox（藍虛線）vs 向量微調後（紅實線）</span>
              <span className="ml-auto text-ink-900/40">
                已微調 {fields.filter((f) => f.refined).length} / {fields.length}
              </span>
            </label>
          )}
          <BboxCanvas
            pageImageUrl={api.thetaPageImageUrl(tid, activePage)}
            fields={pageFields}
            globalFieldIndex={Math.max(0, fields.findIndex((f) => f.page_number === activePage))}
            selectedFieldIdx={selectedFieldIdx}
            imgSize={imgSize}
            onImgLoad={(w, h) => setImgSize({ w, h })}
            onSelectField={(globalIdx) => setSelectedFieldIdx(globalIdx)}
            onUpdateBbox={(globalIdx, bbox) => updateField(globalIdx, { bbox })}
            onAddField={(bbox) => addField(bbox, activePage)}
            showLlmGhost={showLlmGhost}
          />
        </div>

        {/* 右：欄位編輯器 */}
        <aside className="col-span-4 overflow-y-auto bg-paper-100/30 border-l border-ink-900/10">
          <div className="p-7">
            <div className="eyebrow">欄位編輯器</div>
            <div className="font-serif text-lg text-ink-900 mt-1">
              頁 {activePage + 1} · {pageFields.length} 欄位
            </div>
            <div className="rule-thin mt-4 mb-5"></div>

            {selectedField ? (
              <FieldEditor
                field={selectedField}
                idx={selectedFieldIdx!}
                onChange={(patch) => updateField(selectedFieldIdx!, patch)}
                onDelete={() => deleteField(selectedFieldIdx!)}
              />
            ) : (
              <div className="text-sm text-ink-400 leading-relaxed">
                <p>點擊左側畫面上的 <span className="text-cinnabar-500">方框</span> 以選取欄位進行編輯。</p>
                <p className="mt-2">或點擊畫面空白處新增欄位。</p>
              </div>
            )}

            <div className="rule-thin mt-6 mb-5"></div>

            {/* 快速列表：此頁所有欄位 */}
            <div className="text-[11px] tracking-widest uppercase text-ink-400 mb-3">此頁欄位列表</div>
            {pageFields.length === 0 && (
              <div className="text-xs text-ink-400 leading-relaxed border-l-2 border-ink-900/15 pl-3 mb-3">
                GPT 在此頁未識別任何欄位。
                {fields.length > 0 && (
                  <>
                    <br />其他頁面共有 <span className="text-cinnabar-600">{fields.length}</span> 個欄位，
                    可從左側縮圖切換。
                  </>
                )}
              </div>
            )}
            <div className="space-y-1">
              {pageFields.map((f, i) => {
                const globalIdx = fields.findIndex(
                  (gf) => gf.page_number === activePage && gf === f
                );
                return (
                  <button
                    key={`${f.key}@${f.page_number}-${i}`}
                    className={`w-full text-left px-3 py-2 text-sm transition-colors
                      ${globalIdx === selectedFieldIdx
                        ? "bg-cinnabar-500/10 border-l-2 border-cinnabar-500"
                        : "border-l-2 border-transparent hover:bg-paper-100/60"}`}
                    onClick={() => setSelectedFieldIdx(globalIdx)}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-ink-900 truncate">{f.label}</span>
                      <span className="text-[10px] text-ink-400">{f.type}</span>
                    </div>
                    <div className="text-[10px] text-ink-400 mt-0.5 font-mono">{f.key}</div>
                  </button>
                );
              })}
            </div>

            <button
              className="btn-ghost w-full mt-4 text-sm"
              onClick={() => addField([0.1, 0.1, 0.4, 0.05], activePage)}
            >
              + 手動新增欄位
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
}

/* ── BboxCanvas：可拖曳 bbox 的 PDF 頁面檢視器 ──────────────── */

function BboxCanvas({
  pageImageUrl,
  fields,
  globalFieldIndex,
  selectedFieldIdx,
  imgSize,
  onImgLoad,
  onSelectField,
  onUpdateBbox,
  onAddField,
  showLlmGhost,
}: {
  pageImageUrl: string;
  fields: ThetaFieldDef[];
  globalFieldIndex: number;
  selectedFieldIdx: number | null;
  imgSize: { w: number; h: number } | null;
  onImgLoad: (w: number, h: number) => void;
  onSelectField: (globalIdx: number) => void;
  onUpdateBbox: (globalIdx: number, bbox: number[]) => void;
  onAddField: (bbox: number[]) => void;
  showLlmGhost?: boolean;     // rc6.8：是否顯示 LLM 原始 bbox（虛線藍）
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<{
    fieldIdx: number;
    handle: string | null; // null = whole box drag, "se"/"nw"/etc = resize
    startMouse: { x: number; y: number };
    startBbox: number[];
  } | null>(null);

  const toPixel = (bbox: number[]) => {
    if (!imgSize) return { x: 0, y: 0, w: 0, h: 0 };
    return {
      x: bbox[0] * imgSize.w,
      y: bbox[1] * imgSize.h,
      w: bbox[2] * imgSize.w,
      h: bbox[3] * imgSize.h,
    };
  };

  const toNorm = (px: number, py: number) => {
    if (!imgSize) return [0, 0];
    return [px / imgSize.w, py / imgSize.h];
  };

  const handleMouseDown = (e: React.MouseEvent, globalIdx: number, handle: string | null) => {
    e.stopPropagation();
    e.preventDefault();
    const field = fields[globalIdx - globalFieldIndex];
    if (!field) return;
    onSelectField(globalIdx);
    setDragging({
      fieldIdx: globalIdx,
      handle,
      startMouse: { x: e.clientX, y: e.clientY },
      startBbox: [...field.bbox],
    });
  };

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: MouseEvent) => {
      if (!imgSize) return;
      const dx = (e.clientX - dragging.startMouse.x) / imgSize.w;
      const dy = (e.clientY - dragging.startMouse.y) / imgSize.h;
      const [sx, sy, sw, sh] = dragging.startBbox;
      let nx = sx, ny = sy, nw = sw, nh = sh;

      if (dragging.handle === null) {
        // drag whole box
        nx = Math.max(0, Math.min(1 - nw, sx + dx));
        ny = Math.max(0, Math.min(1 - nh, sy + dy));
      } else {
        // resize from handle
        const h = dragging.handle;
        if (h.includes("n")) { ny = Math.max(0, Math.min(sy + sh - 0.01, sy + dy)); nh = sy + sh - ny; }
        if (h.includes("s")) { nh = Math.max(0.01, Math.min(1 - sy, sh + dy)); }
        if (h.includes("w")) { nx = Math.max(0, Math.min(sx + sw - 0.01, sx + dx)); nw = sx + sw - nx; }
        if (h.includes("e")) { nw = Math.max(0.01, Math.min(1 - sx, sw + dx)); }
      }
      onUpdateBbox(dragging.fieldIdx, [
        Math.round(nx * 10000) / 10000,
        Math.round(ny * 10000) / 10000,
        Math.round(nw * 10000) / 10000,
        Math.round(nh * 10000) / 10000,
      ]);
    };
    const onUp = () => setDragging(null);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [dragging, imgSize]);

  const handleCanvasClick = (e: React.MouseEvent) => {
    if (!imgSize || !containerRef.current) return;
    // Only fire if clicking directly on the image area (not on a bbox)
    if (e.target !== e.currentTarget && (e.target as HTMLElement).tagName !== "IMG") return;
    const rect = containerRef.current.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    // Create a small default bbox centered on click
    const [nx, ny] = toNorm(px - 20, py - 10);
    onAddField([
      Math.max(0, Math.round(nx * 10000) / 10000),
      Math.max(0, Math.round(ny * 10000) / 10000),
      0.2,
      0.04,
    ]);
  };

  return (
    <div className="max-w-2xl mx-auto" ref={containerRef} onClick={handleCanvasClick}>
      <div className="relative inline-block bg-paper-100 p-2 shadow-sheet">
        <img
          src={pageImageUrl}
          alt=""
          className="block max-w-full max-h-[calc(100vh-220px)] object-contain"
          onLoad={(e) => {
            const t = e.currentTarget;
            onImgLoad(t.clientWidth, t.clientHeight);
          }}
        />
        {imgSize && fields.map((f, i) => {
          const globalIdx = globalFieldIndex + i;
          const isSelected = selectedFieldIdx === globalIdx;
          const { x, y, w, h } = toPixel(f.bbox);
          // rc6.8：若 vector-snap refined，且開啟雙框模式 → 畫 LLM 原 bbox（藍虛線）
          const showGhost = !!showLlmGhost && !!f.refined && Array.isArray(f.bbox_llm);
          const ghost = showGhost ? toPixel(f.bbox_llm as number[]) : null;
          return (
            <div key={i}>
              {/* Ghost LLM bbox（rc6.8 雙框模式）— 藍色虛線、不可互動 */}
              {ghost && (
                <div
                  className="absolute border border-dashed border-[rgb(140,60,50)]/80 pointer-events-none"
                  style={{ left: ghost.x, top: ghost.y, width: ghost.w, height: ghost.h }}
                  title="LLM 原始 bbox（微調前）"
                />
              )}
              {/* Bbox rectangle */}
              <div
                className={`group absolute border cursor-move transition-colors
                  ${isSelected ? "border-2 border-cinnabar-500 bg-cinnabar-500/10" : "border-[rgb(140,60,50)]/70 bg-[rgb(140,60,50)]/5 hover:border-cinnabar-400 hover:bg-cinnabar-500/10"}`}
                style={{
                  left: x, top: y, width: w, height: h,
                  boxShadow: isSelected ? "0 0 0 9999px rgba(252,250,243,0.45)" : undefined,
                }}
                onMouseDown={(e) => handleMouseDown(e, globalIdx, null)}
              >
                {/* Label above bbox — 預設只顯示首 8 字 + 透明背景；hover/selected 才放大 */}
                <div
                  className={`absolute bottom-full left-0 mb-px px-1 leading-tight whitespace-nowrap pointer-events-none transition-all
                    ${isSelected
                      ? "text-[10px] bg-cinnabar-500 text-paper-50 opacity-100 z-20"
                      : "text-[7px] bg-[rgb(140,60,50)]/85 text-paper-50 opacity-60 group-hover:opacity-100 group-hover:text-[10px] group-hover:z-20"}`}
                  style={{ maxWidth: Math.max(80, w + 40) }}
                >
                  {isSelected ? f.label : (f.label.length > 8 ? f.label.slice(0, 8) + "…" : f.label)}
                </div>
              </div>

              {/* Resize handles (only when selected) */}
              {isSelected && ["nw", "n", "ne", "e", "se", "s", "sw", "w"].map((hnd) => {
                const hx = hnd.includes("w") ? x - 3 : hnd.includes("e") ? x + w - 3 : x + w / 2 - 3;
                const hy = hnd.includes("n") ? y - 3 : hnd.includes("s") ? y + h - 3 : y + h / 2 - 3;
                const cursor = hnd === "nw" || hnd === "se" ? "nwse-resize"
                  : hnd === "ne" || hnd === "sw" ? "nesw-resize"
                  : hnd === "n" || hnd === "s" ? "ns-resize"
                  : "ew-resize";
                return (
                  <div
                    key={hnd}
                    className="absolute w-[7px] h-[7px] bg-paper-50 border border-cinnabar-500 z-10"
                    style={{ left: hx, top: hy, cursor }}
                    onMouseDown={(e) => handleMouseDown(e, globalIdx, hnd)}
                  />
                );
              })}
            </div>
          );
        })}
      </div>
      <p className="folio mt-3 text-center">
        拖曳方框調整位置 · 拉動邊角調整大小 · 點空白處新增欄位
      </p>
    </div>
  );
}

/* ── FieldEditor：右側欄位屬性編輯器 ────────────────────────── */

function FieldEditor({
  field, idx, onChange, onDelete,
}: {
  field: ThetaFieldDef;
  idx: number;
  onChange: (patch: Partial<ThetaFieldDef>) => void;
  onDelete: () => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="eyebrow">欄位 #{idx + 1}</span>
        <button
          className="text-[11px] tracking-widest uppercase text-ink-400 hover:text-cinnabar-600 border border-ink-900/15 hover:border-cinnabar-500 px-2 py-1 transition-colors"
          onClick={onDelete}
        >
          刪除此欄位
        </button>
      </div>

      <div>
        <label className="folio block mb-1">標籤名稱</label>
        <input
          className="input w-full"
          value={field.label}
          onChange={(e) => onChange({ label: e.target.value })}
        />
      </div>

      <div>
        <label className="folio block mb-1">識別碼 (key)</label>
        <input
          className="input w-full font-mono text-sm"
          value={field.key}
          onChange={(e) => onChange({ key: e.target.value })}
        />
      </div>

      <div>
        <label className="folio block mb-1">欄位類型</label>
        <select
          className="input w-full"
          value={field.type}
          onChange={(e) => onChange({ type: e.target.value })}
        >
          {FIELD_TYPES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="folio block mb-1">AI 信心值</label>
        <div className="flex items-center gap-2">
          <div className="flex-1 h-2 bg-paper-200">
            <div
              className="h-full transition-all"
              style={{
                width: `${Math.round(field.confidence * 100)}%`,
                backgroundColor:
                  field.confidence >= 0.9 ? "#6b8e5a" :
                  field.confidence >= 0.7 ? "#d4a843" : "#c4553a",
              }}
            />
          </div>
          <span className="folio text-xs">{Math.round(field.confidence * 100)}%</span>
        </div>
      </div>

      <div>
        <label className="folio block mb-1">位置 (bbox)</label>
        <div className="text-[11px] font-mono text-ink-400">
          x:{field.bbox[0]?.toFixed(3)} y:{field.bbox[1]?.toFixed(3)}
          {" "}w:{field.bbox[2]?.toFixed(3)} h:{field.bbox[3]?.toFixed(3)}
        </div>
      </div>
    </div>
  );
}
