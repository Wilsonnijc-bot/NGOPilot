/// <reference types="vite/client" />

declare module "electron" {
  export interface IpcRendererEvent {
    sender?: unknown;
  }
}

declare module "@ngopilot/renderer";

declare module "@ngopilot/goose-sdk-schema" {
  import type { ZodTypeAny } from "zod";

  export const zRecipeDto: ZodTypeAny;
}

interface Window {
  electron: Record<string, any>;
  appConfig: {
    get: (key: string) => unknown;
    getAll: () => Record<string, unknown>;
  };
}
