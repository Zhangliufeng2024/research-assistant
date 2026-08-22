/* 设置视图：模型接入（可编辑，R6）+ 系统信息只读面板。
 *
 * 模型接入卡：服务商预设 → 填 Base URL/模型/Key → 测试连接（不落盘）→ 保存
 * （写工作目录 .env 并即刻生效，见 web/settings.py）。API Key 只回显掩码。
 */
import { api } from "../api.js";
import { el } from "../format.js";
import { toast } from "../components/toast.js";

/* 服务商预设：选择后自动填 Base URL 与模型名（均可再改） */
const PRESETS = [
  { id: "custom", label: "自定义", base: "", model: "", provider: "" },
  { id: "deepseek", label: "DeepSeek 深度求索", base: "https://api.deepseek.com", model: "deepseek-chat", provider: "openai" },
  { id: "qwen", label: "通义千问（百炼）", base: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus", provider: "openai" },
  { id: "openai", label: "OpenAI 官方", base: "https://api.openai.com/v1", model: "gpt-4o", provider: "openai" },
  { id: "anthropic", label: "Anthropic 官方", base: "", model: "claude-sonnet-4-6", provider: "anthropic" },
];

export async function renderSettingsView(root) {
  const view = el("section", { class: "view view-settings" });
  const grid = el("div", { class: "set-grid" });
  view.append(grid);
  root.append(view);

  let s = null;
  let cfg = null;
  const loadAll = await Promise.allSettled([api.get("/api/status"), api.get("/api/settings")]);
  if (loadAll[0].status === "fulfilled") s = loadAll[0].value;
  if (loadAll[1].status === "fulfilled") cfg = loadAll[1].value;

  grid.innerHTML = "";

  /* ================= 模型接入（可编辑） ================= */
  const presetSel = el("select", { class: "set-input" },
    ...PRESETS.map((p) => el("option", { value: p.id }, p.label)));
  const baseInput = el("input", { class: "set-input", type: "text",
    placeholder: "https://api.deepseek.com（Anthropic 官方可留空）" });
  const modelInput = el("input", { class: "set-input", type: "text", placeholder: "deepseek-chat" });
  const keyInput = el("input", { class: "set-input", type: "password",
    placeholder: cfg?.configured ? `已配置（${cfg.llm_api_key_masked || "***"}），留空则沿用现有` : "sk-…" });
  const provSel = el("select", { class: "set-input" },
    el("option", { value: "" }, "自动识别"),
    el("option", { value: "openai" }, "openai（OpenAI 兼容）"),
    el("option", { value: "anthropic" }, "anthropic"));
  const statusLine = el("div", { class: "set-status" }, "");

  presetSel.addEventListener("change", () => {
    const p = PRESETS.find((x) => x.id === presetSel.value) || PRESETS[0];
    baseInput.value = p.base;
    modelInput.value = p.model;
    provSel.value = p.provider;
  });

  /* 预填：当前 .env 已有值 → 直接填进表单（Key 只填占位提示，不回填明文） */
  if (cfg) {
    const preset = PRESETS.find((p) => p.base && p.base === cfg.llm_base_url);
    presetSel.value = preset ? preset.id : "custom";
    baseInput.value = cfg.llm_base_url || "";
    modelInput.value = cfg.llm_model || "";
    provSel.value = cfg.llm_provider || "";
  }

  const formValues = () => ({
    llm_base_url: baseInput.value.trim(),
    llm_model: modelInput.value.trim(),
    llm_provider: provSel.value,
    llm_api_key: keyInput.value.trim(), // 留空 = 沿用已配置 Key（后端合并，安全不回显明文）
  });

  async function testConn() {
    statusLine.className = "set-status pending";
    statusLine.textContent = "连接测试中…";
    try {
      const r = await api.post("/api/settings/test", formValues());
      if (r.ok) {
        statusLine.className = "set-status ok";
        statusLine.textContent = `✓ 连接成功（${r.model}）${r.reply ? ` · 回复：${r.reply}` : ""}`;
      } else {
        statusLine.className = "set-status err";
        statusLine.textContent = `✗ ${r.error || "连接失败"}`;
      }
    } catch (e) {
      statusLine.className = "set-status err";
      statusLine.textContent = `✗ ${e.message}`;
    }
  }

  async function save() {
    try {
      const r = await api.post("/api/settings", formValues());
      toast(`已保存到 ${r.env_file}，即刻生效（${r.llm_api_key_masked}）`);
      cfg = { configured: true, llm_api_key_masked: r.llm_api_key_masked };
      keyInput.value = "";
      keyInput.placeholder = `已配置（${r.llm_api_key_masked}），留空则沿用现有`;
      statusLine.className = "set-status ok";
      statusLine.textContent = "✓ 已保存并生效";
    } catch (e) {
      toast(`保存失败：${e.message}`);
    }
  }

  const modelCard = el("div", { class: "panel" },
    el("div", { class: "panel-head" }, "模型接入"),
    el("div", { class: "panel-pad set-form" },
      el("label", { class: "set-field" }, el("span", {}, "服务商预设"), presetSel),
      el("label", { class: "set-field" }, el("span", {}, "Base URL"), baseInput),
      el("label", { class: "set-field" }, el("span", {}, "模型名称"), modelInput),
      el("label", { class: "set-field" }, el("span", {}, "API Key"), keyInput),
      el("label", { class: "set-field" }, el("span", {}, "Provider"), provSel),
      statusLine,
      el("div", { class: "set-actions" },
        el("button", { class: "btn btn-ghost", onclick: testConn }, "测试连接"),
        el("button", { class: "btn btn-amber", onclick: save }, "保存配置")),
      el("div", { class: "set-hint" },
        "配置写入当前工作目录的 .env 文件（与 CLI 共享）。图像/搜索等高级配置请直接编辑该文件。")));

  grid.append(modelCard);

  /* ================= 系统信息（只读，原 R5 面板） ================= */
  if (!s) {
    grid.append(el("div", { class: "panel panel-pad banner banner-err" }, "系统信息加载失败"));
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
