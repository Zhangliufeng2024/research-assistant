/* 活动流：追加式日志，自动滚底（用户上翻时暂停），容量由 protocol.ACTIVITY_CAP 控制 */
import { el, esc, fmtTime } from "../format.js";

export function createActivityStream(container) {
  let stickBottom = true;
  let rendered = 0; // 已渲染条数

  container.addEventListener("scroll", () => {
    stickBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;
  });

  function entryNode(e) {
    const body = el("div", { class: "act-body" });
    if (e.kind === "text") {
      const preview = (e.text || "模型输出").slice(0, 100);
      body.append(el("details", { class: "act-text" },
        el("summary", {}, `${preview}${(e.text || "").length > 100 ? "…" : ""}`),
        el("div", { class: "act-text-body", textContent: e.content || e.text })));
    } else {
      body.textContent = e.text || "";
    }
    return el("div", { class: `act-entry k-${e.kind}` },
      el("span", { class: "act-time" }, fmtTime(e.t)),
      body);
  }

  return {
    /** 用最新 activity 数组同步 DOM（增量追加 + 裁剪） */
    sync(activity) {
      while (rendered < activity.length) {
        container.append(entryNode(activity[rendered]));
        rendered++;
      }
      if (rendered > activity.length) { // 数组被裁剪过：整体重绘
        container.innerHTML = "";
        activity.forEach((e) => container.append(entryNode(e)));
        rendered = activity.length;
      }
      // 审批卡等内联组件由视图层插入；这里只保证日志顺序
      if (stickBottom) container.scrollTop = container.scrollHeight;
    },
    reset() { container.innerHTML = ""; rendered = 0; stickBottom = true; },
  };
}

/* 内联审批卡（含倒计时）；respond(approved) 由视图层注入 */
export function approvalCard(appr, respond) {
  const card = el("div", { class: "approval", role: "alertdialog", "aria-modal": "false" });
  const timerEl = el("span", { class: "approval-timer" });
  card.append(
    el("div", { class: "approval-head" }, "⚠ 工具执行审批", timerEl),
    el("div", { class: "approval-summary", textContent: appr.summary || appr.tool }),
    el("div", { class: "approval-actions" },
      el("button", { class: "btn btn-amber btn-sm", onclick: () => respond(true) }, "允许执行"),
      el("button", { class: "btn btn-danger btn-sm", onclick: () => respond(false) }, "拒绝")),
    el("div", { class: "approval-hint" }, "超时未响应将自动拒绝"),
  );

  const tick = () => {
    const left = Math.max(0, Math.ceil((appr.deadline - Date.now()) / 1000));
    timerEl.textContent = `${left}s`;
    if (left <= 0) clearInterval(h);
  };
  const h = setInterval(tick, 500);
  tick();
  card._stopTimer = () => clearInterval(h);
  return card;
}
