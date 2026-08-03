import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import packageManifest from "./package.json" with { type: "json" };

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const repositoryRoot = path.resolve(frontendRoot, "../..");
const browserDependencies = Object.keys(packageManifest.dependencies);

export default defineConfig({
  root: frontendRoot,
  base: "/",
  plugins: [react(), tailwindcss()],
  define: {
    "process.env.GOOSE_TUNNEL": "false",
  },
  resolve: {
    alias: [
      {
        find: "@ngopilot/renderer",
        replacement: path.resolve(repositoryRoot, "harness bone/ui/desktop/src/renderer.tsx"),
      },
      {
        find: "@ngopilot/goose-sdk-schema",
        replacement: path.resolve(repositoryRoot, "harness bone/ui/sdk/src/generated/zod.gen.ts"),
      },
      {
        find: "@aaif/goose-sdk",
        replacement: path.resolve(frontendRoot, "src/goose-sdk-compat.ts"),
      },
      {
        find: "electron",
        replacement: path.resolve(frontendRoot, "src/electron-stub.ts"),
      },
    ],
    dedupe: browserDependencies,
  },
  optimizeDeps: {
    exclude: ["@aaif/goose-sdk"],
  },
  server: {
    host: "127.0.0.1",
    port: 4173,
    strictPort: true,
    fs: {
      allow: [repositoryRoot],
    },
  },
  build: {
    target: "esnext",
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
  },
});
