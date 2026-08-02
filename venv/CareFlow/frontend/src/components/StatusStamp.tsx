export function StatusStamp({ status }: { status: string }) {
  const m: Record<string, { label: string; cls: string }> = {
    uploaded: { label: "已上傳", cls: "stamp-ink" },
    extracting: { label: "抽取中", cls: "stamp-amber" },
    pending_review: { label: "待審", cls: "stamp-amber" },
    confirmed: { label: "已審", cls: "stamp-green" },
    exported: { label: "已匯出", cls: "stamp-green" },
    failed: { label: "失敗", cls: "stamp-red" },
  };
  const x = m[status] || { label: status, cls: "stamp-mute" };
  return <span className={x.cls}>{x.label}</span>;
}
