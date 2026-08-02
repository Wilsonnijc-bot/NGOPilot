import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Plugin } from "vite";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const demoVideoDir = path.resolve(__dirname, "../asset/videos");
const demoHtmlDir = path.resolve(__dirname, "../asset/html");

const videoMimeTypes: Record<string, string> = {
  ".mp4": "video/mp4",
  ".m4v": "video/mp4",
  ".mov": "video/quicktime",
  ".webm": "video/webm",
};

const htmlMimeTypes: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
};

type StaticAssetOptions = {
  mimeTypes: Record<string, string>;
  rangeRequests?: boolean;
};

function staticAssetMiddleware(rootDir: string, options: StaticAssetOptions) {
  return (req: any, res: any, next: any) => {
    if (req.method !== "GET" && req.method !== "HEAD") {
      next();
      return;
    }

    let requestPath = "/";
    try {
      requestPath = decodeURIComponent((req.url || "/").split("?")[0] || "/");
    } catch {
      res.statusCode = 400;
      res.end("Bad request");
      return;
    }

    const filePath = path.resolve(rootDir, `.${requestPath}`);
    const insideRoot = filePath === rootDir || filePath.startsWith(`${rootDir}${path.sep}`);
    if (!insideRoot) {
      res.statusCode = 403;
      res.end("Forbidden");
      return;
    }

    if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
      res.statusCode = 404;
      res.end("Not found");
      return;
    }

    const stat = fs.statSync(filePath);
    const ext = path.extname(filePath).toLowerCase();
    res.setHeader("Content-Type", options.mimeTypes[ext] || "application/octet-stream");
    res.setHeader("Content-Length", String(stat.size));
    res.setHeader("Cache-Control", "public, max-age=3600");

    if (options.rangeRequests) {
      res.setHeader("Accept-Ranges", "bytes");
      const range = req.headers.range;
      if (range) {
        const match = /^bytes=(\d*)-(\d*)$/.exec(range);
        if (!match) {
          res.statusCode = 416;
          res.end();
          return;
        }

        const start = match[1] ? Number(match[1]) : 0;
        const end = match[2] ? Number(match[2]) : stat.size - 1;
        if (start >= stat.size || end >= stat.size || start > end) {
          res.statusCode = 416;
          res.setHeader("Content-Range", `bytes */${stat.size}`);
          res.end();
          return;
        }

        res.statusCode = 206;
        res.setHeader("Content-Range", `bytes ${start}-${end}/${stat.size}`);
        res.setHeader("Content-Length", String(end - start + 1));
        if (req.method === "HEAD") {
          res.end();
          return;
        }
        fs.createReadStream(filePath, { start, end }).pipe(res);
        return;
      }
    }

    res.statusCode = 200;
    if (req.method === "HEAD") {
      res.end();
      return;
    }
    fs.createReadStream(filePath).pipe(res);
  };
}

function demoAssetServer(): Plugin {
  return {
    name: "careflow-demo-asset-server",
    configureServer(server) {
      server.middlewares.use(
        "/demo-videos",
        staticAssetMiddleware(demoVideoDir, { mimeTypes: videoMimeTypes, rangeRequests: true }),
      );
      server.middlewares.use(
        "/demo-html",
        staticAssetMiddleware(demoHtmlDir, { mimeTypes: htmlMimeTypes }),
      );
    },
  };
}

export default defineConfig({
  plugins: [react(), demoAssetServer()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
