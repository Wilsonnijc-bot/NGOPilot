import path from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const repositoryRoot = path.resolve(frontendRoot, "../..");

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
        find: "@aaif/goose-sdk",
        replacement: path.resolve(frontendRoot, "src/goose-sdk-compat.ts"),
      },
      {
        find: "electron",
        replacement: path.resolve(frontendRoot, "src/electron-stub.ts"),
      },
    ],
    dedupe: ["react", "react-dom", "@aaif/goose-sdk", "@agentclientprotocol/sdk"],
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
