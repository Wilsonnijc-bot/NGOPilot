/**
 * 後端 API 客戶端。所有路徑統一走 /api 前綴；
 * 開發時由 vite.config 反向代理到 :8000；生產由 nginx 代理。
 */

export interface VolunteerField {
  key: string;
  label: string;
  type: string;
  options?: string[];
}

export interface BatchOut {
  id: number;
  title: string;
  volunteer_team: string | null;
  visit_date: string | null;
  note: string | null;
  status: string;
  total_photos: number;
  confirmed_count: number;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
  exported_at: string | null;
  exported_file: string | null;
}

export interface RecordOut {
  id: number;
  batch_id: number;
  photo_url: string;
  original_filename: string;
  ai_extracted: Record<string, any> | null;
  ai_confidence: Record<string, number> | null;
  ai_bbox: Record<string, number[]> | null;
  ai_provider: string | null;
  ai_model: string | null;
  ai_latency_ms: number | null;
  ai_error: string | null;
  final_fields: Record<string, any> | null;
  is_reviewed: boolean;
  reviewer: string | null;
  reviewed_at: string | null;
  // ── v0.3.1 新增：資訊完整性 + 自動補全 ───────────────────────────────
  is_complete?: boolean;
  missing_fields?: string[];
  low_confidence_fields?: string[];
  /** key → 該欄位值內部「無法辨識」字元的 [start, end] 區段陣列 */
  partial_fields?: Record<string, [number, number][]>;
  auto_filled_keys?: string[];
  /** AI 推測的補全建議（永遠帶；前端可一鍵採用） */
  suggestions?: Record<string, any>;
  suggestion_confidence?: Record<string, number>;
  /** v0.3.4：DeepSeek 二次審查（預設套用，可一鍵撤回） */
  reviewed_keys?: string[];
  reviewed_reasons?: Record<string, string>;
  reviewed_confidence?: Record<string, number>;
  qwen_original?: Record<string, any>;
  /** v0.3.6：Qwen 連續回空 / 抽取完全失敗 → 提示人工輸入 */
  needs_human_input?: boolean;
}

async function request<T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number },
): Promise<T> {
  const { timeoutMs = 60000, ...rest } = init || {};
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(path, {
      headers: {
        "Content-Type": "application/json",
        ...(rest.headers || {}),
      },
      ...rest,
      signal: controller.signal,
    });
    if (!resp.ok) {
      const text = await resp.text().catch(() => "");
      const friendly =
        resp.status >= 500
          ? "伺服器內部錯誤"
          : resp.status === 404
          ? "資源不存在"
          : resp.status === 401
          ? "未授權"
          : `請求失敗 (${resp.status})`;
      const err: any = new Error(friendly);
      err.status = resp.status;
      err.body = text;
      console.debug("[api]", resp.status, path, text);
      throw err;
    }
    return resp.json();
  } catch (e: any) {
    if (e?.name === "AbortError") {
      throw new Error("timeout");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: () => request<any>("/api/health"),

  // schema
  getSchema: () => request<{ fields: VolunteerField[] }>("/api/volunteer/schema"),

  // batches
  createBatch: (data: { title: string; volunteer_team?: string; visit_date?: string; note?: string }) => {
    const form = new FormData();
    form.append("title", data.title);
    if (data.volunteer_team) form.append("volunteer_team", data.volunteer_team);
    if (data.visit_date) form.append("visit_date", data.visit_date);
    if (data.note) form.append("note", data.note);
    return fetch("/api/volunteer/batches", { method: "POST", body: form }).then((r) => {
      if (!r.ok) throw new Error("create batch failed");
      return r.json() as Promise<BatchOut>;
    });
  },

  uploadPhotos: async (batchId: number, files: File[], autoExtract = true, autoComplete = false) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("auto_extract", String(autoExtract));
    form.append("auto_complete", String(autoComplete));
    const r = await fetch(`/api/volunteer/batches/${batchId}/photos`, { method: "POST", body: form });
    if (!r.ok) throw new Error("upload failed");
    return r.json();
  },

  triggerExtraction: (batchId: number, autoComplete = false) =>
    fetch(`/api/volunteer/batches/${batchId}/extract?auto_complete=${autoComplete}`,
          { method: "POST" }).then((r) => r.json()),

  autoCompleteRecord: (recordId: number) =>
    request<RecordOut>(`/api/volunteer/records/${recordId}/auto-complete`, { method: "POST" }),

  /** v0.3.4：把某欄位從 DeepSeek 審查值還原為 Qwen 原值 */
  revertReviewedField: (recordId: number, fieldKey: string) =>
    request<RecordOut>(`/api/volunteer/records/${recordId}/revert/${fieldKey}`, { method: "POST" }),

  /** v0.3.9：刪除一張紀錄（這頁不是表 / 沒價值） */
  deleteRecord: (recordId: number) =>
    request<{ deleted: boolean; record_id: number; batch_id: number; photo_unlinked: boolean; remaining_in_batch: number }>(
      `/api/volunteer/records/${recordId}`, { method: "DELETE" }),

  /** v0.3.5：AI 連線自檢 —— 一鍵 ping 三個模型 + DNS / TCP 層 */
  diagnoseLLM: () => request<{
    ts: number;
    is_mock_mode: boolean;
    provider: string;
    base_url: string;
    has_api_key: boolean;
    network: { ok: boolean; host: string; port?: number; ip?: string; latency_ms?: number; error?: string };
    text: { ok: boolean; model: string; provider: string; latency_ms: number; reply?: string; error?: string };
    vision: { ok: boolean; model: string; provider: string; latency_ms: number; reply?: string; error?: string };
    total_ms: number;
  }>(`/api/llm/diagnose`),

  getBatch: (batchId: number) => request<BatchOut>(`/api/volunteer/batches/${batchId}`),

  listRecords: (batchId: number) =>
    request<{ records: RecordOut[] }>(`/api/volunteer/batches/${batchId}/records`),

  reviewRecord: (recordId: number, finalFields: Record<string, any>, reviewer?: string) =>
    request<RecordOut>(`/api/volunteer/records/${recordId}/review`, {
      method: "POST",
      body: JSON.stringify({ final_fields: finalFields, reviewer }),
    }),

  exportBatch: (batchId: number) =>
    request<{ batch_id: number; exported_file: string; download_url: string; row_count: number }>(
      `/api/volunteer/batches/${batchId}/export`,
      { method: "POST" }
    ),

  // history
  listBatches: (params: Record<string, string | number | undefined>) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== "" && q.set(k, String(v)));
    return request<{ total: number; batches: BatchOut[] }>(`/api/history/batches?${q.toString()}`);
  },

  batchDetail: (batchId: number) =>
    request<any>(`/api/history/batches/${batchId}/detail`),

  correctionsByField: () =>
    request<{ total: number; by_field: Record<string, any> }>(`/api/history/corrections/by-field`),

  exportCombined: (batchIds: number[], title = "合併匯出") =>
    request<any>(`/api/history/export-combined`, {
      method: "POST",
      body: JSON.stringify({ batch_ids: batchIds, title }),
    }),

  // templates
  getTemplate: () => request<any>("/api/templates"),
  uploadTemplate: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const r = await fetch("/api/templates/upload", { method: "POST", body: form });
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
    return r.json();
  },
  resetTemplate: () => request<any>("/api/templates/reset", { method: "POST" }),
  updateTemplateMapping: (mapping: Record<string, string>) =>
    request<any>("/api/templates/mapping", {
      method: "POST",
      body: JSON.stringify({ mapping }),
    }),

  // placeholders
  homeVisitStatus: () => request<any>("/api/home-visit/status"),
  welfareFormStatus: () => request<any>("/api/welfare-form/status"),

  /** v0.4.0-alpha：列出所有福利表預設套組 */
  listWelfareTemplates: () => request<{
    version: string;
    count: number;
    has_mock_elder: boolean;
    templates: Array<{
      id: string;
      display_name: string;
      display_name_en?: string;
      source_pdf: string;
      pdf_pages: number;
      fill_strategy: "acroform" | "coord_anchor";
      field_count: number;
      status: "ready" | "pending_coord_mapping";
      notes?: string;
    }>;
  }>("/api/welfare-form/templates"),

  /** v0.4.0-alpha：取單一 template 完整定義 + mock elder profile */
  getWelfareTemplate: (templateId: string) => request<{
    template: Record<string, any>;
    elder_profile: Record<string, any>;
  }>(`/api/welfare-form/templates/${templateId}`),

  /** v0.4.0-beta：preview 對映（每欄要填什麼 / 來源 direct/default/llm/missing） */
  previewWelfareMapping: (templateId: string, opts?: { elder_profile?: any; use_llm?: boolean }) =>
    request<{
      template_id: string;
      display_name: string;
      fill_strategy: "acroform" | "coord_anchor";
      mappings: Array<{
        key: string;
        label_zh?: string;
        value: string;
        source: "direct" | "default" | "llm" | "missing";
        confidence: number;
        type: string;
        elder_profile_path?: string;
        reason?: string;
      }>;
      summary: { total: number; direct: number; default: number; llm: number; missing: number };
      used_llm: boolean;
      elder_today: { iso: string; year: string; month: string; day: string };
    }>("/api/welfare-form/preview-mapping", {
      method: "POST",
      body: JSON.stringify({
        template_id: templateId,
        elder_profile: opts?.elder_profile,
        use_llm: opts?.use_llm ?? false,
      }),
    }),

  /** v0.4.0-rc2：從原始長者文字抽取結構化 ElderProfile */
  extractWelfareProfile: (text: string, sourceHint?: string) =>
    request<{
      profile: any;
      mock_mode: boolean;
    }>("/api/welfare-form/extract-profile", {
      method: "POST",
      body: JSON.stringify({ text, source_hint: sourceHint }),
    }),

  /** v0.4.0-rc3：從照片（身份證、申請表、社工筆記照等）抽取 ElderProfile */
  extractWelfareProfileFromImage: async (file: File, sourceHint?: string) => {
    const form = new FormData();
    form.append("image", file);
    if (sourceHint) form.append("source_hint", sourceHint);
    const resp = await fetch("/api/welfare-form/extract-profile-from-image", {
      method: "POST",
      body: form,
    });
    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${text}`);
    }
    return resp.json() as Promise<{
      profile: any;
      mock_mode: boolean;
      image_filename: string;
      image_bytes: number;
    }>;
  },

  /** v0.4.0-beta：實際生成 PDF */
  fillWelfareForm: (templateId: string, opts?: {
    elder_profile?: any;
    field_values?: Record<string, string>;
    overrides?: Record<string, string>;
  }) =>
    request<{
      ok: boolean;
      template_id: string;
      output_file: string;
      download_url: string;
      stats: Record<string, any>;
      latency_ms: number;
      filled_at: string;
    }>("/api/welfare-form/fill", {
      method: "POST",
      body: JSON.stringify({
        template_id: templateId,
        elder_profile: opts?.elder_profile,
        field_values: opts?.field_values,
        overrides: opts?.overrides,
      }),
    }),

  // ── 功能 θ：自訂 PDF 表單模板 ─────────────────────────────────────
  uploadThetaPdf: async (name: string, file: File, note?: string) => {
    const form = new FormData();
    form.append("name", name);
    form.append("file", file);
    if (note) form.append("note", note);
    const r = await fetch("/api/theta/upload", { method: "POST", body: form });
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
    return r.json() as Promise<ThetaUploadResult>;
  },
  listThetaTemplates: () =>
    request<{ templates: ThetaTemplateOut[] }>("/api/theta/templates"),
  getThetaTemplate: (id: number) =>
    request<{ template: ThetaTemplateOut; fields: ThetaFieldDef[]; page_count: number }>(
      `/api/theta/templates/${id}`
    ),
  updateThetaTemplate: (id: number, data: { name?: string; fields?: ThetaFieldDef[] }) =>
    request<{ template: ThetaTemplateOut; fields: ThetaFieldDef[] }>(
      `/api/theta/templates/${id}`,
      { method: "PUT", body: JSON.stringify(data) }
    ),
  deleteThetaTemplate: (id: number) =>
    request<{ deleted: boolean; template_id: number }>(
      `/api/theta/templates/${id}`,
      { method: "DELETE" }
    ),
  thetaPageImageUrl: (templateId: number, pageIndex: number) =>
    `/api/theta/templates/${templateId}/page/${pageIndex}/image`,

  // ── 流水線 β：语音转录 → 結構化報告 ───────────────────────────────
  createVisitSession: async (data: {
    title: string;
    note?: string;
    mode?: VisitSessionMode;
    audio: File;
    template: File;
  }) => {
    const form = new FormData();
    form.append("title", data.title);
    if (data.note) form.append("note", data.note);
    if (data.mode) form.append("mode", data.mode);
    form.append("audio", data.audio);
    form.append("template", data.template);
    const r = await fetch("/api/home-visit/sessions", { method: "POST", body: form });
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
    return r.json() as Promise<VisitSessionOut>;
  },
  listVisitSessions: () =>
    request<{ sessions: VisitSessionOut[] }>("/api/home-visit/sessions"),
  getVisitSession: (id: number) =>
    request<VisitSessionOut>(`/api/home-visit/sessions/${id}`),
  reviewVisitSession: (id: number, slotContentFinal: Record<string, any>, reviewer?: string) =>
    request<VisitSessionOut>(`/api/home-visit/sessions/${id}/review`, {
      method: "POST",
      body: JSON.stringify({ slot_content_final: slotContentFinal, reviewer }),
    }),
  burnTranscript: (id: number) =>
    request<{ burned: boolean }>(`/api/home-visit/sessions/${id}/burn`, { method: "POST" }),
  // 全離線 mock 示範（一鍵載入內建樣本 mp3 + docx）
  createVisitMockDemo: async () => {
    const r = await fetch("/api/home-visit/sessions/mock-demo", { method: "POST" });
    if (!r.ok) throw new Error(`HTTP ${r.status}: ${await r.text()}`);
    return r.json() as Promise<VisitSessionOut>;
  },
  getVisitMockDemoAvailable: () =>
    request<{ available: boolean; is_mock_mode: boolean; audio_filename: string | null; template_filename: string | null }>(
      "/api/home-visit/mock-demo/available"
    ),
};

// ── 功能 θ：自訂 PDF 表單模板 ───────────────────────────────────────
export interface ThetaFieldDef {
  id?: number;
  page_number: number;
  key: string;
  label: string;
  type: string;
  bbox: number[];
  bbox_llm?: number[] | null;  // rc6.8: 向量微調前的 LLM 原始 bbox（audit 雙框模式用）
  refined?: boolean;            // rc6.8: 是否經過 vector snap 微調
  confidence: number;
}

export interface ThetaTemplateOut {
  id: number;
  name: string;
  original_pdf_filename: string | null;
  page_count: number;
  status: string;
  note: string | null;
  field_count?: number;
  created_at: string;
  updated_at: string;
}

export interface ThetaUploadResult {
  template: ThetaTemplateOut;
  fields: ThetaFieldDef[];
  analysis_meta: {
    provider: string;
    model: string;
    latency_ms: number;
    total_pages: number;
    total_fields: number;
    is_mock: boolean;
    last_error?: string;
    page_errors?: Array<{ page: number; error: string }>;
  };
}

export type VisitSessionMode = "home_visit" | "internal_meeting";

export interface VisitSessionOut {
  id: number;
  title: string;
  note: string | null;
  status: string;
  audio_filename: string | null;
  template_filename: string | null;
  template_contract: {
    fixed_blocks?: Array<{ label?: string; content?: string }>;
    dynamic_slots?: Array<{ label: string; description?: string; expected_type?: string }>;
    rules?: any[];
    rendering_rules?: any[];
  } | null;
  slot_content: Record<string, string> | null;
  slot_content_final: Record<string, string> | null;
  generated_file: string | null;
  download_url: string | null;
  transcript_snippet: string | null;
  transcript_burned: boolean;
  ai_provider: string | null;
  ai_model: string | null;
  ai_latency_ms: number | null;
  ai_error: string | null;
  reviewer: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}
