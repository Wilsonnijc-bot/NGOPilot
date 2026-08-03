/// <reference types="vite/client" />

declare module "electron" {
  export interface IpcRendererEvent {
    sender?: unknown;
  }
}

declare module "@ngopilot/renderer";

interface Window {
  electron: Record<string, any>;
  appConfig: {
    get: (key: string) => unknown;
    getAll: () => Record<string, unknown>;
  };
}
