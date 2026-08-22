/* 入口：启动恢复 + 路由 + 全局连接状态 */
import { S } from "./store.js";
import { api } from "./api.js";
import { initRouter, registerRoutes } from "./router.js";
import { renderChatView } from "./views/chat.js";
import { renderTaskView } from "./views/task.js";
import { renderPapersView } from "./views/papers.js";
import { renderSettingsView } from "./views/settings.js";

registerRoutes({
  chat: renderChatView,   // D1：会话为主视图
  task: renderTaskView,
  papers: renderPapersView,
  settings: renderSettingsView,
});

/* 连接状态点 */
const dot = document.getElementById("conn-dot");
const modelLabel = document.getElementById("model-label");
S.subscribe((state) => {
  if (dot) {
    dot.className = `conn-dot ${state.conn === "open" ? (state.running ? "busy" : "on")
      : state.conn === "connecting" ? "busy"
      : state.conn === "error" || state.conn === "closed" ? "off" : ""}`;
  }
});

/* 启动 */
api.get("/api/status").then((s) => {
  S.set({ status: s });
  modelLabel.textContent = s.model || "unknown";
  document.title = `研究助手 · ${s.model || "RA Console"}`;
}).catch(() => {
  modelLabel.textContent = "服务离线";
});

initRouter();
