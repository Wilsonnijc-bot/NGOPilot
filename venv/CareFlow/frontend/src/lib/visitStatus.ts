export const STATUS_LABELS: Record<string, { zh: string; cls: string }> = {
  uploaded: { zh: "已收件", cls: "stamp-ink" },
  extracting: { zh: "AI 抽取中", cls: "stamp-amber" },
  pending_review: { zh: "待覆核", cls: "stamp-amber" },
  rendering: { zh: "渲染中", cls: "stamp-ink" },
  confirmed: { zh: "已用印", cls: "stamp-green" },
  failed: { zh: "失敗", cls: "stamp-red" },
  burned: { zh: "已焚錄音稿", cls: "stamp-mute" },
  archived: { zh: "歸檔", cls: "stamp-mute" },
};

export const TERMINAL_STATUSES = new Set(["confirmed", "burned", "failed", "archived"]);
