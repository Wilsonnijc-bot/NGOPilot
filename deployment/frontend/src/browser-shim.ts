import { apiFetch, ApiError, logout } from "./auth";

type Listener = (event: unknown, ...args: unknown[]) => void;

const SETTINGS_KEY = "ngopilot.browser.settings";
const RECENT_DIRS_KEY = "ngopilot.browser.recent-dirs";

const defaultSettings: Record<string, unknown> = {
  showMenuBarIcon: false,
  disableAutoDownload: true,
  showDockIcon: false,
  enableWakelock: false,
  enableNotifications: true,
  spellcheckEnabled: true,
  keyboardShortcuts: {},
  externalGoosed: { enabled: true, url: "", secret: "" },
  theme: "light",
  useSystemTheme: true,
  language: "zh-HK",
  responseStyle: "concise",
  showPricing: false,
  seenAnnouncementIds: [],
};

function readSettings(): Record<string, unknown> {
  try {
    const value = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    const settings = { ...defaultSettings, ...value };
    settings.language = settings.language === "en" ? "en" : "zh-HK";
    return settings;
  } catch {
    return { ...defaultSettings };
  }
}

function writeSettings(settings: Record<string, unknown>): void {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

const appConfig: Record<string, unknown> = {
  GOOSE_DEFAULT_PROVIDER: import.meta.env.VITE_GOOSE_DEFAULT_PROVIDER || "openrouter",
  GOOSE_DEFAULT_MODEL:
    import.meta.env.VITE_GOOSE_DEFAULT_MODEL || "deepseek/deepseek-v4-flash",
  GOOSE_PREDEFINED_MODELS: import.meta.env.VITE_GOOSE_PREDEFINED_MODELS || undefined,
  GOOSE_WORKING_DIR: import.meta.env.VITE_GOOSE_WORKING_DIR || "",
  GOOSE_PATH_ROOT: "",
  GOOSE_LOCALE: readSettings().language,
  GOOSE_DISABLE_NOSTR_SHARING: true,
  GOOSE_VERSION: "1.45.0",
  NGOPILOT_CLOUD: true,
};

function platform(): string {
  const value = navigator.userAgent.toLowerCase();
  if (value.includes("mac")) return "darwin";
  if (value.includes("win")) return "win32";
  return "linux";
}

async function openArtifact(path: string): Promise<void> {
  const response = await apiFetch(`/api/artifacts/url?path=${encodeURIComponent(path)}`);
  if (!response.ok) {
    throw new ApiError("The generated file is not available", response.status);
  }
  const payload = (await response.json()) as { url?: unknown };
  if (typeof payload.url !== "string" || !payload.url) {
    throw new Error("The artifact gateway returned an invalid download URL");
  }
  window.open(payload.url, "_blank", "noopener,noreferrer");
}

async function openExternal(url: string): Promise<void> {
  if (url.startsWith("/data/")) {
    await openArtifact(url);
    return;
  }
  const parsed = new URL(url, window.location.href);
  if (parsed.protocol === "file:") {
    await openArtifact(decodeURIComponent(parsed.pathname));
    return;
  }
  if (!["http:", "https:", "mailto:"].includes(parsed.protocol)) return;
  window.open(parsed.href, "_blank", "noopener,noreferrer");
}

function selectTextFile(): Promise<{ filePath: string; contents: string } | null> {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json,application/json,text/plain";
    input.addEventListener("change", async () => {
      const file = input.files?.[0];
      resolve(file ? { filePath: file.name, contents: await file.text() } : null);
    });
    input.addEventListener("cancel", () => resolve(null));
    input.click();
  });
}

function downloadText(filePath: string, content: string): void {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filePath.split(/[\\/]/).pop() || "ngopilot-export.txt";
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 0);
}

function uploadFile(file: File): string {
  const id = crypto.randomUUID();
  const placeholder = `ngopilot-upload://${id}/${encodeURIComponent(file.name)}`;
  const body = new FormData();
  body.set("file", file);
  body.set("upload_id", id);
  body.set("placeholder", placeholder);

  void apiFetch("/api/uploads", { method: "POST", body }).then(async (response) => {
    if (!response.ok) {
      const message = await response.text().catch(() => "");
      console.error(`[upload] ${placeholder}: ${response.status} ${message}`);
    }
  }).catch((error) => console.error(`[upload] ${placeholder}`, error));

  return placeholder;
}

export function installBrowserShim(): void {
  const listeners = new Map<string, Set<Listener>>();
  const on = (channel: string, listener: Listener) => {
    const channelListeners = listeners.get(channel) ?? new Set<Listener>();
    channelListeners.add(listener);
    listeners.set(channel, channelListeners);
  };
  const off = (channel: string, listener: Listener) => listeners.get(channel)?.delete(listener);
  const emit = (channel: string, ...args: unknown[]) => {
    listeners.get(channel)?.forEach((listener) => listener(undefined, ...args));
  };

  window.appConfig = {
    get: (key: string) => appConfig[key],
    getAll: () => ({ ...appConfig }),
  };

  window.electron = {
    platform: platform(),
    arch: "web",
    reactReady: () => undefined,
    getConfig: () => ({ ...appConfig }),
    hideWindow: () => undefined,
    directoryChooser: async () => ({ canceled: true, filePaths: [] }),
    createChatWindow: (options: Record<string, unknown> = {}) => {
      const sessionId = typeof options.resumeSessionId === "string" ? options.resumeSessionId : null;
      window.location.hash = sessionId
        ? `/pair?resumeSessionId=${encodeURIComponent(sessionId)}`
        : "/";
    },
    logInfo: (message: string) => console.info(message),
    showNotification: ({ title, body }: { title: string; body: string }) => {
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification(title, { body });
      }
    },
    showMessageBox: async (options: { message: string; detail?: string; buttons?: string[] }) => {
      const accepted = options.buttons?.length
        ? window.confirm([options.message, options.detail].filter(Boolean).join("\n\n"))
        : true;
      return { response: accepted ? 0 : 1 };
    },
    showSaveDialog: async () => ({ canceled: true }),
    openInChrome: (url: string) => void openExternal(url),
    reloadApp: () => window.location.reload(),
    checkForOllama: async () => false,
    selectFileOrDirectory: async () => null,
    selectImportSessionFile: selectTextFile,
    getBinaryPath: async () => "",
    readFile: async (filePath: string) => ({
      file: "",
      filePath,
      error: "Local filesystem access is unavailable in the browser",
      found: false,
    }),
    writeFile: async (filePath: string, content: string) => {
      downloadText(filePath, content);
      return true;
    },
    ensureDirectory: async () => false,
    listFiles: async () => [],
    getAllowedExtensions: async () => [],
    getPathForFile: uploadFile,
    setMenuBarIcon: async () => false,
    getMenuBarIconState: async () => false,
    setDockIcon: async () => false,
    getDockIconState: async () => false,
    getSetting: async (key: string) => readSettings()[key],
    setSetting: async (key: string, value: unknown) => {
      writeSettings({ ...readSettings(), [key]: value });
    },
    getSecretKey: async () => null,
    getAcpUrl: async () => {
      const response = await apiFetch("/api/ws-tickets", { method: "POST" });
      if (!response.ok) {
        if (response.status === 401) setTimeout(() => window.location.reload(), 0);
        throw new ApiError("Unable to open the agent connection", response.status);
      }
      const payload = (await response.json()) as { url?: unknown };
      if (typeof payload.url !== "string" || !payload.url) {
        throw new Error("The agent gateway returned an invalid WebSocket ticket");
      }
      return payload.url;
    },
    setWakelock: async () => false,
    getWakelockState: async () => false,
    setSpellcheck: async () => false,
    getSpellcheckState: async () => true,
    openNotificationsSettings: async () => false,
    isAnyWindowFocused: async () => document.hasFocus(),
    getIsFullScreen: async () => Boolean(document.fullscreenElement),
    onMouseBackButtonClicked: () => undefined,
    offMouseBackButtonClicked: () => undefined,
    on,
    off,
    emit,
    broadcastThemeChange: (themeData: unknown) => emit("theme-changed", themeData),
    openExternal,
    getVersion: () => String(appConfig.GOOSE_VERSION),
    checkForUpdates: async () => ({ updateInfo: null, error: null }),
    downloadUpdate: async () => ({ success: false, error: "Updates are managed by the web service" }),
    installUpdate: () => undefined,
    restartApp: () => window.location.reload(),
    onUpdaterEvent: () => undefined,
    getUpdateState: async () => null,
    isUsingGitHubFallback: async () => false,
    getAutoDownloadDisabled: async () => true,
    closeWindow: () => undefined,
    hasAcceptedRecipeBefore: async () => false,
    recordRecipeHash: async () => true,
    openDirectoryInExplorer: async () => false,
    launchApp: async () => undefined,
    refreshApp: async () => undefined,
    closeApp: logout,
    addRecentDir: async (dir: string) => {
      const recent = JSON.parse(localStorage.getItem(RECENT_DIRS_KEY) || "[]") as string[];
      localStorage.setItem(RECENT_DIRS_KEY, JSON.stringify([dir, ...recent.filter((item) => item !== dir)].slice(0, 10)));
      return true;
    },
    listRecentDirs: async () => JSON.parse(localStorage.getItem(RECENT_DIRS_KEY) || "[]"),
    listGitWorktreeDirs: async () => [],
  };

}
