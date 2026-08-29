import { readFileSync } from "node:fs";
// vitest/config 的 defineConfig 是 vite 的超集（多接受一个 test 字段）。
// 注意 vite.config.ts 不在 tsconfig.json 的 include 内（只含 src），
// 因此这里的 test 配置不参与 tsc -b，不影响 `npm run build`。
import { defineConfig } from "vitest/config";
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
    // R15 路由代码分割配套：重依赖拆 vendor chunk。react-vendor 是壳层
    // 必需；motion 被 Toaster/向导静态引用仍属首屏；markdown/katex 只被
    // lazy 视图引用，首屏不再加载（配合 React.lazy 的路由 chunk）。
    rollupOptions: {
      output: {
        manualChunks: {
          "react-vendor": ["react", "react-dom", "react-router-dom", "zustand"],
          motion: ["framer-motion"],
          markdown: [
            "react-markdown",
            "remark-gfm",
            "remark-math",
            "rehype-highlight",
            "rehype-katex",
            "highlight.js",
          ],
          katex: ["katex"],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  test: {
    // 覆盖率只统计 src 内自有代码：排除类型声明、测试自身与类型目录。
    // 阈值随阶段推进提高，A+ 口径为整体 ≥70%、纯函数层（lib/stores）≥90%。
    // 阶段 0 只报告不阻断（thresholds 暂不设）。
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "html"],
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/*.d.ts",
        "src/**/__tests__/**",
        "src/**/*.test.{ts,tsx}",
        "src/main.tsx",
        "src/types/**",
        "src/test/**",
      ],
    },
  },
});
