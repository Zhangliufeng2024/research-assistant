/* 任务视图：左（运行历史）· 中（组稿 ↔ 驾驶舱）· 右（预算/产物） */
import { S } from "../store.js";
import { api } from "../api.js";
import { wsConnect, wsSend, wsClose, wsConnected } from "../ws.js";
import { emptyTask, reduceTask, RUN_STATUS_LABEL, runBadgeClass } from "../protocol.js";
import { el, fmtDate, fmtCost, fmtNum } from "../format.js";
import { toast } from "../components/toast.js";
import { confirmDialog } from "../components/modal.js";
import { createActivityStream, approvalCard } from "../components/activity.js";
import { renderTimeline } from "../components/timeline.js";
import { renderBudget } from "../components/budget.js";

let cleanup = null;
let stream = null;          // 活动流句柄
let ui = {};                // 视图内 DOM 引用
let lastTimelineJson = "";
let approvalNode = null;

export function renderTaskView(root, onCleanup) {
  if (cleanup) cleanup();
  ui = {};
  lastTimelineJson = "";
  approvalNode = null;

  const view = el("section", { class: "view view-task" });

  /* ---- 左栏：新建 + 运行历史 ---- */
  ui.runList = el("div", { class: "run-list" }, el("div", { class: "empty" }, "加载中…"));
  ui.runCount = el("span", { class: "count" }, "");
  const sideCol = el("div", { class: "side-col" },
    el("button", { class: "newtask-btn", onclick: () => composeMode() }, "＋ 新建任务"),
    el("div", { class: "panel", style: "flex:1;min-height:0" },
      el("div", { class: "panel-head" }, "运行历史", ui.runCount),
      ui.runList));

  /* ---- 中央 ---- */
  ui.center = el("div", { class: "cockpit" });

  /* ---- 右栏：预算 / 产物 ---- */
  ui.budgetBody = el("div", {}, "");
  ui.artifactBody = el("div", { class: "panel-pad" },
    el("div", { class: "empty", style: "padding:20px" }, "尚无产物"));
  const metaCol = el("div", { class: "meta-col" },
    el("div", { class: "panel" },
      el("div", { class: "panel-head" }, "本次消耗"),
      ui.budgetBody),
    el("div", { class: "panel" },
      el("div", { class: "panel-head" }, "产物"),
      ui.artifactBody));

  view.append(sideCol, ui.center, metaCol);
  root.append(view);

  /* ================= 组稿模式 ================= */
  function composeMode(prefill = "") {
    ui.center.innerHTML = "";
    const ta = el("textarea", {
      class: "textarea", id: "query",
      placeholder: "例如：写一篇关于复合结构在土木工程中应用的综述论文（Ctrl+Enter 开始）",
      rows: "7",
    });
    ta.value = prefill || "";
    const multi = el("input", { type: "checkbox", id: "multi-agent" });
    multi.checked = true;
    const cost = el("input", { class: "input cost-input", type: "number", min: "0.1", step: "0.5", placeholder: "不限" });

    const launch = () => startGeneration(ta.value.trim(), multi.checked, cost.value);
    ta.addEventListener("keydown", (e) => { if (e.ctrlKey && e.key === "Enter") launch(); });

    ui.center.append(el("div", { class: "panel compose" },
      el("div", { class: "compose-head" }, "描述你的研究任务",
        el("small", {}, "agent 将自动完成 规划 → 研究 → 图表 → 组装 → 质量门 → 定稿 全流程")),
      ta,
      el("div", { class: "compose-opts" },
        el("label", { class: "checkbox" }, multi, " 多智能体流水线"),
        el("span", { class: "cost-wrap" }, "预算上限 USD", cost)),
      el("div", { class: "compose-actions" },
        el("button", { class: "btn btn-amber", onclick: launch }, "▶ 启动生成"))));
    ta.focus();
  }

  /* ================= 驾驶舱模式 ================= */
  function cockpitMode(task) {
    ui.center.innerHTML = "";
    stream = null;
    approvalNode = null;

    // 状态横幅
    ui.bannerBox = el("div", {});

    // 时间轴面板
    const tlPanel = el("div", { class: "panel timeline-panel" },
      el("div", { class: "panel-head" }, "PIPELINE",
        el("span", { class: "badge b-info", id: "phase-badge" }, "")));
    ui.timelineBox = el("div", {});
    tlPanel.append(ui.timelineBox);

    // 活动流面板
    const logBody = el("div", { class: "activity panel-body" });
    stream = createActivityStream(logBody);
    stream.reset();
    ui.logBody = logBody;
    ui.approvalSlot = el("div", {}); // 审批卡插入点（视觉上位于流末尾）
    const actPanel = el("div", { class: "panel activity-panel", style: "display:flex;flex-direction:column" },
      el("div", { class: "panel-head" }, "活动流",
        el("span", { class: "badge", id: "act-count" }, "")),
      logBody,
      ui.approvalSlot);

    // 底部操作条：steer 输入 + 停止
    ui.steerInput = el("input", {
      class: "input", placeholder: "运行中可注入转向指令（Ctrl+Enter 发送），如：改为英文写作",
    });
    ui.steerInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") sendSteer();
    });
    ui.stopBtn = el("button", { class: "btn btn-danger btn-sm", onclick: stopGeneration }, "■ 停止");
    const steerBar = el("div", {},
      el("div", { class: "steer-bar" }, ui.steerInput,
        el("button", { class: "btn btn-ghost btn-sm", onclick: sendSteer }, "注入")),
      el("div", { class: "steer-hint" }, "steer 指令会在 agent 下一步被并入对话"));

    actPanel.append(steerBar);
    ui.phaseBadge = tlPanel.querySelector("#phase-badge");
    ui.actCount = actPanel.querySelector("#act-count");

    ui.center.append(ui.bannerBox, tlPanel, actPanel);

    // 结果区（完成后填充）
    ui.resultBox = el("div", {});
    ui.center.append(ui.resultBox);
  }

  /* ================= 动作 ================= */
  function startGeneration(query, multiAgent, maxCost, resumeRun = null) {
    if (!query && !resumeRun) return;
    S.set({ task: { ...emptyTask(), query, resumeRun, phase: "running", startedAt: Date.now() }, running: true });
    cockpitMode(S.get("task"));

    wsConnect({
      onMessage: onWsMessage,
      onStatus: onWsStatus,
    });
    wsConnectedWait(() => {
      const payload = { action: "start", query, track_token_usage: true };
      if (resumeRun) { payload.resume_run = resumeRun; payload.multi_agent = true; }
      else payload.multi_agent = !!multiAgent;
      const c = parseFloat(maxCost);
      if (!Number.isNaN(c) && c > 0) payload.max_cost_usd = c;
      wsSend(payload);
    });
    loadRuns();
  }

  function wsConnectedWait(fn) {
    let tries = 0;
    const h = setInterval(() => {
      if (wsConnected()) { clearInterval(h); fn(); }
      else if (++tries > 50) { clearInterval(h); toast("连接超时，请确认服务正在运行", "err"); }
    }, 100);
  }

  function stopGeneration() {
    const t = S.get("task");
    if (!t || !t.taskId) return;
    api.post(`/api/tasks/${encodeURIComponent(t.taskId)}/stop`)
      .then(() => toast("已请求停止，等待 agent 收尾…", "warn"))
      .catch((e) => toast(`停止失败：${e.message}`, "err"));
  }

  function sendSteer() {
    const v = (ui.steerInput?.value || "").trim();
    if (!v) return;
    if (!wsSend({ action: "steer", message: v.slice(0, 2000) })) {
      toast("连接不可用，无法注入指令", "err");
      return;
    }
    ui.steerInput.value = "";
    const t = S.get("task");
    if (t) S.set({ task: { ...t, activity: t.activity.concat({ t: Date.now(), kind: "info", text: `你：${v}` }) } });
  }

  function respondApproval(appr, approved) {
    if (approvalNode?._stopTimer) approvalNode._stopTimer();
    approvalNode?.remove();
    approvalNode = null;
    if (!wsSend({ action: "approval", id: appr.id, approved })) {
      toast("连接已断开，审批未能送达（服务端将按超时拒绝）", "err");
      return;
    }
    const t = S.get("task");
    if (t) S.set({ task: { ...t, approval: null } });
    toast(`已${approved ? "允许" : "拒绝"}：${appr.tool}`, approved ? "ok" : "warn", 2500);
  }

  function onWsMessage(msg) {
    const cur = S.get("task") || emptyTask();
    S.set({ task: reduceTask(cur, msg) });
    if (msg.type === "done") setTimeout(wsClose, 300); // 服务端收尾后释放通道
    if (msg.type === "result" || msg.type === "done" || msg.type === "error") {
      S.set({ running: false });
      loadRuns();
    }
  }

  function onWsStatus(st) {
    const t = S.get("task");
    if ((st === "closed" || st === "error") && t && t.phase === "running") {
      S.set({ task: { ...t, phase: "error", error: "WebSocket 连接断开，生成已中止。pipeline 任务可从左侧运行历史一键续跑。", finishedAt: Date.now() }, running: false });
      loadRuns();
    }
    if (st === "connecting" && !t) composeMode();
  }

  /* ================= 渲染同步 ================= */
  function syncTask(state) {
    const t = state.task;
    if (!t || !ui.timelineBox) return;

    // 时间轴
    const tj = JSON.stringify(t.timeline);
    if (tj !== lastTimelineJson) {
      lastTimelineJson = tj;
      ui.timelineBox.innerHTML = "";
      ui.timelineBox.append(renderTimeline(t));
    }
    // 阶段徽标
    if (ui.phaseBadge) {
      const label = { idle: "待命", running: "生成中", done: "已完成", failed: "失败", error: "出错", cancelled: "已停止" }[t.phase] || t.phase;
      const cls = { running: "b-run", done: "b-ok", failed: "b-err", error: "b-err", cancelled: "b-warn", idle: "" }[t.phase] || "";
      ui.phaseBadge.className = `badge ${cls}`;
      ui.phaseBadge.textContent = label;
      ui.stopBtn && (ui.stopBtn.disabled = t.phase !== "running");
      ui.steerInput && (ui.steerInput.disabled = t.phase !== "running");
    }
    // 活动流
    if (stream) {
      stream.sync(t.activity);
      ui.actCount.textContent = `${t.activity.length}`;
    }
    // 审批卡
    syncApproval(t);
    // 预算
    if (t.budget) {
      const nb = renderBudget(t);
      ui.budgetBody.innerHTML = "";
      ui.budgetBody.append(nb);
    }
    // 结果 / 错误
    syncResult(t);
  }

  function syncApproval(t) {
    const slot = ui.approvalSlot;
    if (!slot) return;
    if (!t.approval) {
      if (approvalNode) { approvalNode._stopTimer?.(); approvalNode.remove(); approvalNode = null; }
      return;
    }
    if (approvalNode && approvalNode._apprId === t.approval.id) return;
    if (approvalNode) { approvalNode._stopTimer?.(); approvalNode.remove(); }
    approvalNode = approvalCard(t.approval, (ok) => respondApproval(t.approval, ok));
    approvalNode._apprId = t.approval.id;
    slot.append(approvalNode);
  }

  function syncResult(t) {
    if (!ui.resultBox) return;
    if (!["done", "failed", "error", "cancelled"].includes(t.phase)) { ui.resultBox.innerHTML = ""; return; }
    const box = el("div", { class: "panel panel-pad", style: "flex-shrink:0" });

    if (t.phase === "done" && t.result) {
      const m = t.result.metadata || {};
      box.append(el("div", { class: "compose-head", style: "margin-bottom:10px" },
        "✓ 文档生成完成 ",
        el("small", {}, [
          m.title ? `《${m.title}》` : "",
          m.word_count ? ` ${fmtNum(m.word_count)} 字` : "",
          t.result.figures_count ? ` · 图 ${t.result.figures_count}` : "",
          t.result.citations?.count ? ` · 引文 ${t.result.citations.count}` : "",
          t.result.token_usage ? ` · ${fmtNum(t.result.token_usage.total_tokens)} tok` : "",
        ].join(""))));
      const acts = el("div", { class: "compose-actions" });
      const pn = t.result.paper_name;
      if (pn) {
        acts.append(el("button", { class: "btn btn-ghost btn-sm", onclick: () => { location.hash = "#/papers"; } }, "打开文库查看"));
      }
      const files = t.result.files || {};
      if (pn && files.docx_final)
        acts.append(el("a", { class: "btn btn-ghost btn-sm", href: `/api/papers/${encodeURIComponent(pn)}/files/${encodeURIComponent(files.docx_final)}`, download: "" }, "下载 Word"));
      if (pn && files.pdf_final)
        acts.append(el("a", { class: "btn btn-ghost btn-sm", href: `/api/papers/${encodeURIComponent(pn)}/files/${encodeURIComponent(files.pdf_final)}`, download: "" }, "下载 PDF"));
      box.append(acts);
    } else if (t.error) {
      box.append(el("div", { class: "banner banner-err" },
        el("span", { style: "white-space:pre-wrap;word-break:break-word" }, t.error)));
      if (t.resumeRun || t.taskId) {
        box.append(el("div", { class: "compose-actions", style: "margin-top:8px" }));
      }
    }
    ui.resultBox.innerHTML = "";
    ui.resultBox.append(box);
  }

  /* ================= 运行历史 ================= */
  async function loadRuns() {
    try {
      const runs = await api.get("/api/runs");
      S.set({ runs });
    } catch { /* 静默：侧栏数据非关键 */ }
  }

  function syncRuns(runs) {
    ui.runCount.textContent = `(${runs.length})`;
    ui.runList.innerHTML = "";
    if (!runs.length) {
      ui.runList.append(el("div", { class: "empty" },
        el("span", { class: "empty-icon" }, "▢"), "还没有任务",
        el("div", { class: "empty-hint" }, "点击上方「新建任务」开始")));
      return;
    }
    for (const r of runs) {
      const item = el("div", { class: "run-item" });
      item.append(
        el("div", { class: "run-item-top" },
          el("span", { class: `dot ${r.status === "running" ? "run" : r.status === "complete" ? "ok" : r.status === "failed" ? "err" : "idle"}` }),
          el("span", { class: "run-item-name", title: r.name }, r.name)),
        el("div", { class: "run-item-query", title: r.query || "" }, r.query || r.paper?.topic || ""),
        el("div", { class: "run-item-meta" },
          el("span", { class: `badge ${runBadgeClass(r.status)}` }, RUN_STATUS_LABEL[r.status] || r.status),
          el("span", {}, fmtDate(r.created_at)),
          r.budget?.cost_usd ? el("span", {}, fmtCost(r.budget.cost_usd)) : null),
      );
      item.addEventListener("click", () => onRunClick(r));
      ui.runList.append(item);
    }
  }

  async function onRunClick(r) {
    if (r.status === "legacy") { location.hash = "#/papers"; return; }
    const okResume = await confirmDialog(
      `续跑「${r.name}」？\n已完成阶段将自动跳过（ArtifactStore 断点续跑）。`,
      { danger: false, okText: "续跑", cancelText: "取消" });
    if (!okResume) return;
    startGeneration(r.query || "", true, null, r.name);
  }

  /* ================= 订阅与轮询 ================= */
  let lastRunsRef = null;
  const unsub = S.subscribe((state) => {
    if (state.runs !== lastRunsRef) { lastRunsRef = state.runs; syncRuns(state.runs); }
    syncTask(state);
  });

  const poll = setInterval(() => {
    if (document.visibilityState === "visible") loadRuns();
  }, 8000);

  loadRuns();
  if (!S.get("task") || S.get("task").phase === "idle") composeMode("");
  else { cockpitMode(S.get("task")); syncTask(S.get("all")); }

  cleanup = () => {
    clearInterval(poll);
    unsub();
    approvalNode?._stopTimer?.();
    stream = null;
  };
  onCleanup(() => { if (cleanup) { cleanup(); cleanup = null; } });
}
