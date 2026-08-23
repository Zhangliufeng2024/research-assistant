import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// 版本号单一来源：package.json 构建期注入（侧栏页脚 v{APP_VERSION}），
// 杜绝再次出现硬编码漂移（v3.3.0 漂了三轮才被 E2E 截图发现）。
const pkg = JSON.parse(
  readFileSync(new URL("./package.json", import.meta.url), "utf-8"),
) as { version: string };

// 构建产物直出后端静态目录（R7 计划 D3）；开发期 /api 与 /ws 代理到本地 FastAPI。
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  build: {
    outDir: "../research_assistant/web/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
});
