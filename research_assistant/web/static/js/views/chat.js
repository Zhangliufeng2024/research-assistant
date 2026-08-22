/* 会话视图：左（历史会话）· 中（聊天流 + 输入条）· 右（预算 + 工作区文件树）。
 *
 * R2 会话模式前端。WS 协议见 docs/plans/2026-08-22-desktop-workspace.md §3-C2；
 * 消息归约在 protocol_chat.js（纯函数，node:test 覆盖），本文件只管渲染与动作。
 */
import { api } from "../api.js";
import { wsConnect, wsSend, wsClose, wsConnected } from "../ws.js";
import {
  emptyChat, applyUserMessage, applyApprovalResponse, reduceChat,
  chatBadgeClass, CHAT_PHASE_LABEL,
} from "../protocol_chat.js";
import { el, fmtDate, fmtCost, fmtNum } from "../format.js";
import { toast } from "../components/toast.js";
import { approvalCard } from "../components/activity.js";
import { showImage, showPdf, panelModal } from "../components/modal.js";
import { renderMarkdown } from "../md.js";
import { createFileTree } from "../components/filetree.js";

let cleanup = null;

export function renderChatView(root, onCleanup) {
  if (cleanup) cleanup();
  let chat = emptyChat();
  let sessions = [];
  let approvalNode = null;
  let raf = 0;
  const ui = {};

  /* ================= 布局 ================= */
  ui.sessList = el("div", { class: "session-list" },
    el("div", { class: "empty", style: "padding:12px" }, "加载中…"));
  ui.sessCount = el("span", { class: "count" }, "");
  const sideCol = el("div", { class: "side-col" },
    el("button", { class: "newtask-btn", onclick: newSession }, "＋ 新会话"),
    el("div", { class: "panel", style: "flex:1;min-height:0;display:flex;flex-direction:column" },
      el("div", { class: "panel-head" }, "历史会话", ui.sessCount),
      ui.sessList));

  ui.phaseBadge = el("span", { class: "badge" }, "待命");
  ui.connHint = el("span", { class: "chat-conn" }, "");
  ui.stream = el("div", { class: "chat-stream" },
    el("div", { class: "empty", style: "margin:auto" },
      el("span", { class: "empty-icon" }, "◇"), "开始与助手对话",
      el("div", { class: "empty-hint" }, "它可以读写工作区文件、跑数据分析、查文献、生成长文档")));
  ui.approvalSlot = el("div", {});
  ui.input = el("textarea", {
    class: "input chat-input", rows: "2",
    placeholder: "向助手发消息…（Ctrl+Enter 发送；agent 运行中发送将作为转向指令注入）",
    disabled: "",
  });
  ui.sendBtn = el("button", { class: "btn btn-amber btn-sm", onclick: send, disabled: "" }, "发送");
  ui.input.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); send(); }
  });

  const chatPanel = el("div", { class: "chat-panel" },
    el("div", { class: "chat-head" },
      el("span", { class: "chat-title" }, "SESSION"),
      ui.phaseBadge,
      ui.connHint,
      el("span", { style: "flex:1" }),
      el("button", { class: "btn btn-ghost btn-sm", onclick: () => { location.hash = "#/task"; } }, "长文档任务 →")),
    ui.stream,
    ui.approvalSlot,
    el("div", { class: "chat-foot" },
      el("div", { class: "chat-inputbar" }, ui.input, ui.sendBtn),
      el("div", { class: "chat-hint" }, "工具调用与文件产物会以卡片形式出现在对话流中")));

  ui.budgetBody = el("div", { class: "panel-pad" },
    el("div", { class: "empty", style: "padding:12px" }, "等待用量…"));
  ui.treeBox = el("div", { style: "flex:1;min-height:0;overflow:hidden;display:flex" });
  const metaCol = el("div", { class: "meta-col" },
    el("div", { class: "panel" },
      el("div", { class: "panel-head" }, "本次消耗"),
      ui.budgetBody),
    el("div", { class: "panel", style: "flex:1;min-height:0;display:flex;flex-direction:column" },
      el("div", { class: "panel-head" }, "工作区",
        el("button", { class: "fact", onclick: () => ui.tree && ui.tree.refresh() }, "刷新")),
      ui.treeBox));

  const view = el("section", { class: "view view-chat" });
  view.append(sideCol, chatPanel, metaCol);
  root.append(view);

  const tree = createFileTree(ui.treeBox, { onOpen: openFilePreview });
  ui.tree = tree;

  /* ================= 文件预览 ================= */
  function openFilePreview(nd) {
    if (!nd || !nd.path) return;
    const url = `/api/workspace/file?path=${encodeURIComponent(nd.path)}`;
    const name = nd.name || nd.path.split("/").pop();
    if (/\.(png|jpe?g|gif|svg|webp)$/i.test(name)) return showImage(url, name);
    if (/\.pdf$/i.test(name)) return showPdf(url, name);
    api.get(url).then((res) => {
      if (res.kind !== "text") { window.open(url, "_blank"); return; }
      panelModal(name, (content) => {
        content.append(el("pre", {
          class: "md-content",
          style: "margin:0;padding:12px 16px;max-height:70vh;overflow-y:auto;white-space:pre-wrap;word-break:break-word;font-family:var(--mono);font-size:12px;line-height:1.7",
        }, res.content + (res.truncated ? "\n\n…（内容过长已截断）" : "")));
      });
    }).catch((e) => toast(`预览失败：${e.message}`, "err"));
  }

  /* ================= 会话列表 ================= */
  async function loadSessions() {
    try {
      const res = await api.get("/api/chat/sessions");
      sessions = Array.isArray(res) ? res : res.sessions || [];
      ui.sessCount.textContent = `(${sessions.length})`;
      renderSessions();
    } catch {
      ui.sessList.innerHTML = "";
      ui.sessList.append(el("div", { class: "empty", style: "padding:12px" }, "会话 API 未就绪"));
    }
  }

  function renderSessions() {
    ui.sessList.innerHTML = "";
    if (!sessions.length) {
      ui.sessList.append(el("div", { class: "empty", style: "padding:14px" }, "暂无历史会话"));
      return;
    }
    for (const s of sessions) {
      const item = el("div", { class: `ss-item ${s.id === chat.sessionId ? "active" : ""}` });
      item.append(
        el("div", { class: "ss-name", title: s.last_message || s.id }, s.title || s.last_message || s.id),
        el("div", { class: "ss-meta" },
          el("span", {}, fmtDate(s.updated_at || s.created_at)),
          typeof s.turns === "number" ? el("span", {}, `${s.turns} 轮`) : null));
      item.addEventListener("click", () => resumeSession(s.id));
      ui.sessList.append(item);
    }
  }

  /* ================= 连接与动作 ================= */
  function connect(queryStr = "") {
    wsConnect({ channel: "chat", query: queryStr, onMessage: onMsg, onStatus: onStatus });
  }

  function newSession() {
    wsClose("chat");
    chat = emptyChat();
    renderSessions();
    syncAll();
    connect("");
  }

  async function resumeSession(id) {
    if (id === chat.sessionId && wsConnected("chat")) return;
    wsClose("chat");
    chat = { ...emptyChat(), sessionId: id };
    try {
      const h = await api.get(`/api/chat/sessions/${encodeURIComponent(id)}`);
      hydrate(h.messages || []);
    } catch { /* 无历史也照常进入 */ }
    renderSessions();
    syncAll();
    connect(`session=${encodeURIComponent(id)}`);
  }

  /* 历史 messages → 聊天流（工具卡不持久化，仅恢复文本往来） */
  function hydrate(msgs) {
    chat = {
      ...chat,
      items: msgs.map((m) => m.role === "user"
        ? { kind: "user", text: m.content || "", t: 0 }
        : { kind: "text", text: m.content || "", t: 0 }),
    };
  }

  function enableInput() {
    ui.input.disabled = false;
    ui.sendBtn.disabled = false;
    ui.input.placeholder = "向助手发消息…（Ctrl+Enter 发送；agent 运行中发送将作为转向指令注入）";
  }

  function send() {
    const v = ui.input.value.trim();
    if (!v) return;
    if (!wsConnected("chat")) { toast("连接不可用，请稍候或新建会话", "err"); return; }
    const running = chat.phase === "running";
    ui.input.value = "";
    chat = applyUserMessage(chat, v);
    scheduleSync();
    if (running) wsSend({ action: "steer", message: v.slice(0, 2000) }, "chat");
    else wsSend({ action: "user", text: v.slice(0, 8000) }, "chat");
  }

  function respondApproval(appr, ok) {
    approvalNode?._stopTimer?.();
    approvalNode?.remove();
    approvalNode = null;
    if (!wsSend({ action: "approval", id: appr.id, approved: ok }, "chat")) {
      toast("审批未能送达（服务端将按超时拒绝）", "err");
      return;
    }
    chat = applyApprovalResponse(chat);
    scheduleSync();
    toast(`已${ok ? "允许" : "拒绝"}：${appr.tool}`, ok ? "ok" : "warn", 2500);
  }

  /* ================= WS 回调 ================= */
  function onMsg(msg) {
    const next = reduceChat(chat, msg);
    const changed = next !== chat;
    chat = next;
    if (msg.type === "connected") { enableInput(); loadSessions(); }
    if (msg.type === "result" || msg.type === "error") loadSessions();
    if (changed) scheduleSync();
  }

  function onStatus(st) {
    ui.connHint.textContent =
      st === "open" ? "· 已连接" : st === "connecting" ? "· 连接中…" : "· 离线";
    if (st === "open") enableInput();
    if ((st === "closed" || st === "error") && chat.phase === "running") {
      chat = { ...chat, phase: "error", error: "连接断开，本轮对话已中止。可从左侧历史重新进入该会话。", finishedAt: Date.now() };
    }
    scheduleSync();
  }

  /* ================= 渲染 ================= */
  function scheduleSync() {
    if (raf) return;
    raf = requestAnimationFrame(() => { raf = 0; syncAll(); });
  }

  function nearBottom(elm) {
    return elm.scrollHeight - elm.scrollTop - elm.clientHeight < 80;
  }

  function syncAll() {
    ui.phaseBadge.className = `badge ${chatBadgeClass(chat.phase)}`;
    ui.phaseBadge.textContent = CHAT_PHASE_LABEL[chat.phase] || chat.phase;
    ui.sendBtn.disabled = !wsConnected("chat");

    const stick = nearBottom(ui.stream);
    ui.stream.innerHTML = "";
    for (const it of chat.items) ui.stream.append(itemNode(it));
    if (stick) ui.stream.scrollTop = ui.stream.scrollHeight;

    syncApproval();

    const nb = renderBudgetMini(chat.budget);
    ui.budgetBody.replaceWith(nb);
    ui.budgetBody = nb;
  }

  function itemNode(it) {
    if (it.kind === "user") {
      return el("div", { class: "msg-row user" },
        el("div", { class: "bubble user" }, it.text,
          it.steer ? el("div", { class: "steer-tag" }, "↻ 已作为转向指令注入") : null));
    }
    if (it.kind === "text") {
      return el("div", { class: "msg-row" },
        el("div", { class: "bubble ai md-content", html: renderMarkdown(it.text || "") }));
    }
    const card = chat.cards[it.ref];
    return card ? toolCardNode(card) : el("div", {});
  }

  function toolCardNode(card) {
    const dotCls = { running: "run", done: "ok", error: "err" }[card.status] || "";
    const bcls = { running: "b-run", done: "b-ok", error: "b-err" }[card.status] || "";
    const label = { running: "运行中", done: "完成", error: "出错" }[card.status] || card.status;
    const head = el("div", { class: "tc-head" },
      el("span", { class: `dot ${dotCls}` }),
      el("span", { class: "tc-tool" }, card.tool || "tool"),
      el("span", { class: `badge ${bcls}` }, label));
    const box = el("div", { class: "toolcard" }, head);
    let argStr = "";
    try { argStr = JSON.stringify(card.args ?? {}, null, 1); } catch { argStr = ""; }
    if (argStr && argStr !== "{}") box.append(el("div", { class: "tc-args" }, argStr.slice(0, 600)));
    if (card.preview) box.append(el("div", { class: "tc-preview" }, String(card.preview).slice(0, 800)));
    if (Array.isArray(card.files) && card.files.length) {
      const files = el("div", { class: "tc-files" });
      for (const f of card.files.slice(0, 8)) {
        const base = (f.path || "").split("/").pop();
        const isImg = /\.(png|jpe?g|gif|webp|svg)$/i.test(base);
        const chip = el("span", { class: "tc-file", title: f.path },
          isImg ? "▣ " : "▪ ", base);
        chip.addEventListener("click", () =>
          openFilePreview({ path: f.path, name: base, type: "file" }));
        files.append(chip);
      }
      box.append(files);
    }
    return el("div", { class: "msg-row" }, box);
  }

  function syncApproval() {
    const slot = ui.approvalSlot;
    if (!chat.approval) {
      if (approvalNode) { approvalNode._stopTimer?.(); approvalNode.remove(); approvalNode = null; }
      return;
    }
    if (approvalNode && approvalNode._apprId === chat.approval.id) return;
    if (approvalNode) { approvalNode._stopTimer?.(); approvalNode.remove(); }
    approvalNode = approvalCard(chat.approval, (ok) => respondApproval(chat.approval, ok));
    approvalNode._apprId = chat.approval.id;
    slot.append(approvalNode);
  }

  function renderBudgetMini(b) {
    if (!b) return el("div", { class: "panel-pad" },
      el("div", { class: "empty", style: "padding:12px" }, "等待首轮用量…"));
    const wrap = el("div", { class: "panel-pad" });
    const cost = typeof b.cost_usd === "number" ? b.cost_usd : 0;
    // BudgetGuard.snapshot() 把上限嵌在 limits 子对象下（docs/protocol.md §10）
    const limitRaw = b.max_cost_usd ?? b.limits?.max_cost_usd;
    const limit = typeof limitRaw === "number" && limitRaw > 0 ? limitRaw : null;
    const pct = limit ? Math.min(100, (cost / limit) * 100) : 0;
    wrap.append(el("div", { class: "b-row" }, el("span", {}, "费用"),
      el("b", { style: pct >= 80 ? "color:var(--err)" : "" },
        `${fmtCost(cost)}${limit ? ` / $${limit.toFixed(2)}` : ""}`)));
    if (limit) {
      wrap.append(el("div", { class: "cost-track" },
        el("div", { class: `cost-fill ${pct >= 80 ? "hot" : ""}`, style: `width:${pct}%` })));
    }
    // 模型无价格表时成本上限不可执行（BudgetGuard.snapshot 如实上报）——明示，别让 $0.00 装作免费
    if (limit && b.cost_cap_enforceable === false) {
      wrap.append(el("div", { class: "b-note" },
        "⚠ 该模型无价格表：费用上限暂不生效（token/轮次/时长上限仍生效）"));
    }
    if (typeof b.total_tokens === "number") {
      wrap.append(el("div", { class: "b-row" }, el("span", {}, "Tokens"),
        el("b", {}, fmtNum(b.total_tokens))));
    }
    wrap.append(el("div", { class: "b-row" }, el("span", {}, "轮次"),
      el("b", {}, String(chat.turns || b.turns || 0))));
    return wrap;
  }

  /* ================= 启动 ================= */
  loadSessions();
  connect("");

  cleanup = () => {
    if (raf) cancelAnimationFrame(raf);
    approvalNode?._stopTimer?.();
    wsClose("chat");
  };
  onCleanup(() => { if (cleanup) { cleanup(); cleanup = null; } });
}
