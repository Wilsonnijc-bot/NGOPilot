/**
 * 應用層設定 — 用 localStorage 持久化。
 * 目前唯一旗標：autoComplete（流水線 α 上傳時是否自動 AI 補全不完整欄位）。
 */

const KEY_AUTO_COMPLETE = "careflow.settings.autoComplete";

export const settingsStore = {
  getAutoComplete(): boolean {
    return localStorage.getItem(KEY_AUTO_COMPLETE) === "1";
  },
  setAutoComplete(v: boolean): void {
    localStorage.setItem(KEY_AUTO_COMPLETE, v ? "1" : "0");
    window.dispatchEvent(new CustomEvent("careflow:settings", { detail: { autoComplete: v } }));
  },
  subscribe(cb: () => void): () => void {
    const h = () => cb();
    window.addEventListener("careflow:settings", h);
    window.addEventListener("storage", h);
    return () => {
      window.removeEventListener("careflow:settings", h);
      window.removeEventListener("storage", h);
    };
  },
};
