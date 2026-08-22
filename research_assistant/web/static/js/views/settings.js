/* 设置视图：系统信息只读面板（模型/端点、机制开关、运行环境） */
import { api } from "../api.js";
import { el } from "../format.js";

export async function renderSettingsView(root) {
  const view = el("section", { class: "view view-settings" });
  const grid = el("div", { class: "set-grid" },
    el("div", { class: "panel panel-pad", style: "min-height:120px" },
      el("div", { class: "empty" }, el("span", { class: "spin" }), " 加载中…")));
  view.append(grid);
  root.append(view);

  let s;
  try {
    s = await api.get("/api/status");
  } catch (e) {
    grid.innerHTML = "";
    grid.append(el("div", { class: "panel panel-pad banner banner-err" }, `加载失败：${e.message}`));
    return;
  }

  const card = (title, rows) => {
    const p = el("div", { class: "panel" },
      el("div", { class: "panel-head" }, title));
    const body = el("div", { class: "panel-pad", style: "padding-top:6px" });
    for (const [k, v, cls] of rows) {
      if (v === undefined || v === null || v === "") continue;
      body.append(el("div", { class: "set-row" },
        el("span", { class: "set-key", html: k }),
        el("span", { class: `set-val ${cls || ""}`, textContent: String(v) })));
    }
    p.append(body);
    return p;
  };

  const onoff = (v) => (v === true || v === "true" || v === 1 ? ["on", "on"] : [v, ""]);

  grid.innerHTML = "";
  grid.append(
    card("模型与端点", [
      ["模型", s.model],
      ["Provider", s.provider],
      ["API Host", s.base_url_host, "off"],
      ["输出目录", s.output_folder],
    ]),
    card("机制开关", [
      ["审批模式 <code>RA_APPROVAL_MODE</code>", s.approval_mode, s.approval_mode === "interactive" ? "on" : "off"],
      ["权限拦截 <code>RA_PERMISSION_MODE</code>", s.permission_mode, s.permission_mode === "deny_dangerous" ? "on" : "off"],
      [`重复调用阈值 <code>RA_REPEAT_TOOL_LIMIT</code>`, s.repeat_limit],
      ["流水线状态机 <code>RA_PIPELINE</code>", ...onoff(s.pipeline)],
      ["自动续跑 <code>RA_AUTO_CONTINUE</code>", ...onoff(s.auto_continue)],
    ]),
    card("运行环境", [
      ["版本", s.version],
      ["Python", s.python],
      ["活动任务", s.active_tasks],
    ]),
  );
}
