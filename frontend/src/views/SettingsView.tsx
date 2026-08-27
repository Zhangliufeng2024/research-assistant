import { useEffect, useState } from "react";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { api } from "@/lib/api";
import type { SettingsData } from "@/lib/types";
import { toast } from "@/stores/toastStore";

/** 服务商预设：选择后自动填 Base URL 与模型名（均可再改）。 */
const PRESETS = [
  { id: "custom", label: "自定义", base: "", model: "", provider: "" },
  { id: "deepseek", label: "DeepSeek 深度求索", base: "https://api.deepseek.com", model: "deepseek-chat", provider: "openai" },
  { id: "qwen", label: "通义千问（百炼）", base: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus", provider: "openai" },
  { id: "openai", label: "OpenAI 官方", base: "https://api.openai.com/v1", model: "gpt-4o", provider: "openai" },
  { id: "anthropic", label: "Anthropic 官方", base: "", model: "claude-sonnet-5", provider: "anthropic" },
] as const;

type StatusInfo = Record<string, any>;

/** A2 设置页扩展字段（GET /api/settings 新增返回；types.ts 保持不动避免并行冲突）。 */
type ExtendedSettings = SettingsData & {
  parallel_api_key_masked?: string;
  image_api_key_masked?: string;
  image_base_url?: string;
  image_model?: string;
  ra_max_cost_usd?: number | string | null;
  ra_max_tokens?: number | string | null;
  ra_max_turns?: number | string | null;
  llm_request_interval?: number | string | null;
  ra_llm_first_byte_timeout?: number | string | null;
  ra_approval_mode?: string;
  ra_permission_mode?: string;
};

/** PUT /api/settings 的完整载荷：数值键以字符串提交（后端做类型化校验）。 */
type SavePayload = {
  llm_api_key: string;
  llm_base_url: string;
  llm_model: string;
  llm_provider: string;
  parallel_api_key: string;
  image_api_key: string;
  image_base_url: string;
  image_model: string;
  ra_max_cost_usd: string;
  ra_max_tokens: string;
  ra_max_turns: string;
  llm_request_interval: string;
  ra_llm_first_byte_timeout: string;
  ra_approval_mode: string;
  ra_permission_mode: string;
};

const inputCls =
  "w-full rounded-xl border border-edge bg-canvas px-3 py-2 text-[13.5px] outline-none transition-colors placeholder:text-ink-3 focus:border-accent/60";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12.5px] font-medium text-ink-2">{label}</span>
      {children}
    </label>
  );
}

function Hint({ children }: { children: React.ReactNode }) {
  return <p className="text-[11.5px] leading-5 text-ink-3">{children}</p>;
}

function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  if (!value) return null;
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-edge/60 py-2 last:border-0">
      <span className="shrink-0 text-[12.5px] text-ink-2">{label}</span>
      <span className={`min-w-0 truncate text-right text-[12.5px] ${mono ? "font-mono" : ""}`}>
        {value}
      </span>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-edge bg-surface shadow-card">
      <h2 className="border-b border-edge px-5 py-3 text-[14px] font-semibold">{title}</h2>
      <div className="p-5">{children}</div>
    </section>
  );
}

/** 数值输入 + 单位提示（A2 预算与节奏分区用）；留空 = 使用系统默认。 */
function NumberField({
  label, unit, value, onChange, min, step,
}: {
  label: string;
  unit: string;
  value: string;
  onChange: (v: string) => void;
  min?: string;
  step?: string;
}) {
  return (
    <Field label={label}>
      <input
        type="number"
        value={value}
        min={min}
        step={step ?? "any"}
        onChange={(e) => onChange(e.target.value)}
        placeholder={`留空 = 用默认（${unit}）`}
        className={inputCls}
      />
    </Field>
  );
}

const onoff = (v: unknown) =>
  v === true || v === "true" || v === 1 ? "开启" : String(v ?? "关闭");

/** null/undefined → 空串（number 输入框的受控值约定） */
const fmt = (v: number | string | null | undefined) =>
  v === null || v === undefined ? "" : String(v);

/**
 * 设置页（A2 分区卡片）：模型接入、联网检索、图像生成、预算与节奏、
 * 审批与权限共用一次「保存配置」（写全局 .env，即刻生效）；
 * 其余为只读信息面板。
 */
export function SettingsView() {
  const [cfg, setCfg] = useState<ExtendedSettings | null>(null);
  const [sys, setSys] = useState<StatusInfo | null>(null);
  const [preset, setPreset] = useState("custom");
  const [base, setBase] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [provider, setProvider] = useState("");
  // —— 联网检索 ——
  const [parallelKey, setParallelKey] = useState("");
  // —— 图像生成 ——
  const [imageKey, setImageKey] = useState("");
  const [imageBase, setImageBase] = useState("");
  const [imageModel, setImageModel] = useState("");
  // —— 预算与节奏 ——
  const [maxCost, setMaxCost] = useState("");
  const [maxTokens, setMaxTokens] = useState("");
  const [maxTurns, setMaxTurns] = useState("");
  const [reqInterval, setReqInterval] = useState("");
  const [firstByteTimeout, setFirstByteTimeout] = useState("");
  // —— 审批与权限 ——
  const [approvalMode, setApprovalMode] = useState("off");
  const [permissionMode, setPermissionMode] = useState("deny_dangerous");
  const [status, setStatus] = useState<{ kind: "" | "ok" | "err" | "pending"; text: string }>({
    kind: "",
    text: "",
  });
  const [busy, setBusy] = useState<"" | "test" | "save">("");
  const [instructions, setInstructions] = useState("");
  const [instrStatus, setInstrStatus] = useState("");
  // 覆盖确认（R15）：已配置过模型时，保存会整体替换 .env 的接入配置——
  // 不可逆，先经 ConfirmDialog 二次确认；首次配置则直接保存。
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);

  useEffect(() => {
    document.title = "研究助手 · 设置";
    Promise.allSettled([api.get<StatusInfo>("/api/status"), api.get<ExtendedSettings>("/api/settings")])
      .then(([r1, r2]) => {
        if (r1.status === "fulfilled") setSys(r1.value);
        if (r2.status === "fulfilled") {
          const c = r2.value;
          setCfg(c);
          const hit = PRESETS.find((p) => p.base && p.base === c.llm_base_url);
          setPreset(hit ? hit.id : "custom");
          setBase(c.llm_base_url || "");
          setModel(c.llm_model || "");
          setProvider(c.llm_provider || "");
          setImageBase(c.image_base_url || "");
          setImageModel(c.image_model || "");
          setMaxCost(fmt(c.ra_max_cost_usd));
          setMaxTokens(fmt(c.ra_max_tokens));
          setMaxTurns(fmt(c.ra_max_turns));
          setReqInterval(fmt(c.llm_request_interval));
          setFirstByteTimeout(fmt(c.ra_llm_first_byte_timeout));
          setApprovalMode(c.ra_approval_mode || "off");
          setPermissionMode(c.ra_permission_mode || "deny_dangerous");
        }
      });
    api.get<{ instructions: string }>("/api/project/instructions")
      .then((r) => setInstructions(r.instructions || ""))
      .catch(() => {});
  }, []);

  async function saveInstructions() {
    setInstrStatus("保存中…");
    try {
      await api.put("/api/project/instructions", { instructions });
      setInstrStatus("✓ 已保存，下一次生成任务即刻生效");
      toast.success("项目指令已保存，下一次生成任务即刻生效");
    } catch (e) {
      setInstrStatus(`✗ 保存失败：${(e as Error).message}`);
      toast.error(`项目指令保存失败：${(e as Error).message}`);
    }
  }

  function pickPreset(id: string) {
    setPreset(id);
    const p = PRESETS.find((x) => x.id === id) || PRESETS[0];
    setBase(p.base);
    setModel(p.model);
    setProvider(p.provider);
  }

  /** 全部分区的表单值一次提交；密钥留空 = 后端沿用已配置值。 */
  const formValues = (): SavePayload => ({
    llm_base_url: base.trim(),
    llm_model: model.trim(),
    llm_provider: provider,
    llm_api_key: key.trim(),
    parallel_api_key: parallelKey.trim(), // 留空 = 沿用已配置 Key
    image_api_key: imageKey.trim(),
    image_base_url: imageBase.trim(),
    image_model: imageModel.trim(),
    ra_max_cost_usd: maxCost.trim(), // 空 = 清除该上限（后端范围校验）
    ra_max_tokens: maxTokens.trim(),
    ra_max_turns: maxTurns.trim(),
    llm_request_interval: reqInterval.trim(),
    ra_llm_first_byte_timeout: firstByteTimeout.trim(),
    ra_approval_mode: approvalMode,
    ra_permission_mode: permissionMode,
  });

  async function testConn() {
    setStatus({ kind: "pending", text: "连接测试中…" });
    setBusy("test");
    try {
      const r = await api.post<{ ok: boolean; model?: string; reply?: string; error?: string }>(
        "/api/settings/test",
        formValues(),
      );
      setStatus(
        r.ok
          ? { kind: "ok", text: `✓ 连接成功（${r.model}）${r.reply ? ` · 回复：${r.reply}` : ""}` }
          : { kind: "err", text: `✗ ${r.error || "连接失败"}` },
      );
    } catch (e) {
      setStatus({ kind: "err", text: `✗ ${(e as Error).message}` });
    } finally {
      setBusy("");
    }
  }

  /** 真正的保存执行体（R15 拆出：save() 只负责确认门禁）。 */
  async function performSave() {
    setBusy("save");
    try {
      const r = await api.post<{ env_file: string; llm_api_key_masked: string }>(
        "/api/settings",
        formValues(),
      );
      setCfg({ ...(cfg || ({} as ExtendedSettings)), configured: true });
      setKey("");
      setParallelKey("");
      setImageKey("");
      setStatus({ kind: "ok", text: `✓ 已保存到 ${r.env_file}，即刻生效（${r.llm_api_key_masked}）` });
      toast.success(`配置已保存到 ${r.env_file}，即刻生效`);
      // 回读刷新各密钥的掩码占位提示
      api.get<ExtendedSettings>("/api/settings").then(setCfg).catch(() => {});
      // 刷新「模型与端点」等信息卡：其数据来自挂载时的一次性快照（R7 反馈 #2）
      api.get<StatusInfo>("/api/status").then(setSys).catch(() => {});
    } catch (e) {
      setStatus({ kind: "err", text: `✗ 保存失败：${(e as Error).message}` });
      toast.error(`配置保存失败：${(e as Error).message}`);
    } finally {
      setBusy("");
    }
  }

  async function save() {
    if (cfg?.configured) {
      // 已有接入配置：整体替换不可逆，走确认
      setConfirmOverwrite(true);
      return;
    }
    await performSave();
  }

  const keyPlaceholder = cfg?.configured
    ? `已配置（${cfg.llm_api_key_masked || "***"}），留空则沿用现有`
    : "sk-…";
  const parallelPlaceholder = cfg?.parallel_api_key_masked
    ? `已配置（${cfg.parallel_api_key_masked}），留空则沿用现有`
    : "留空 = 不启用联网检索";
  const imageKeyPlaceholder = cfg?.image_api_key_masked
    ? `已配置（${cfg.image_api_key_masked}），留空则沿用现有`
    : "nvapi-… 或 sk-…";
  const saveHint = (
    <Hint>修改后点击「模型」分区中的「保存配置」，与本页所有分区一并写入全局 .env。</Hint>
  );

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-6 py-6">
      <Card title="模型">
        <div className="space-y-4">
          <Field label="服务商预设">
            <select value={preset} onChange={(e) => pickPreset(e.target.value)} className={inputCls}>
              {PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Base URL">
            <input
              value={base}
              onChange={(e) => setBase(e.target.value)}
              placeholder="https://api.deepseek.com（Anthropic 官方可留空）"
              className={inputCls}
            />
          </Field>
          <Field label="模型名称">
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="claude-sonnet-5"
              className={inputCls}
            />
          </Field>
          <Field label="API Key">
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder={keyPlaceholder}
              className={inputCls}
            />
          </Field>
          <Field label="Provider">
            <select value={provider} onChange={(e) => setProvider(e.target.value)} className={inputCls}>
              <option value="">自动识别</option>
              <option value="openai">openai（OpenAI 兼容）</option>
              <option value="anthropic">anthropic</option>
            </select>
          </Field>

          {status.text && (
            <div
              className={`rounded-xl px-3.5 py-2.5 text-[12.5px] ${
                status.kind === "ok"
                  ? "bg-ok/10 text-ok"
                  : status.kind === "err"
                    ? "bg-danger/10 text-danger"
                    : "bg-surface-2 text-ink-2"
              }`}
            >
              {status.text}
            </div>
          )}

          <div className="flex gap-2.5">
            <button
              type="button"
              onClick={() => void testConn()}
              disabled={busy !== ""}
              className="rounded-xl border border-edge bg-surface px-4 py-2 text-[13px] font-medium transition-colors hover:bg-surface-2 disabled:opacity-50"
            >
              {busy === "test" ? "测试中…" : "测试连接"}
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy !== ""}
              className="rounded-xl bg-accent px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
            >
              {busy === "save" ? "保存中…" : "保存配置"}
            </button>
          </div>

          <p className="text-[11.5px] leading-5 text-ink-3">
            配置保存在应用数据目录（%APPDATA%\ResearchAssistant\.env），所有工作
            目录共享一份，切换工作目录不会丢失；保存即刻生效。旧版本写在某个工作
            目录里的配置会在首次打开本页时自动迁移。下方联网检索、图像生成、预算
            与节奏、审批与权限各分区随本次保存一并写入。
          </p>
        </div>
      </Card>

      <Card title="联网检索">
        <div className="space-y-4">
          <Field label="PARALLEL_API_KEY">
            <input
              type="password"
              value={parallelKey}
              onChange={(e) => setParallelKey(e.target.value)}
              placeholder={parallelPlaceholder}
              className={inputCls}
            />
          </Field>
          <Hint>
            用于 parallel-web 联网检索与引文核验（文献搜索、网页抽取、深度调研都经它
            出网）。留空则该功能不可用——任务仍可运行，但无法联网查证资料。
          </Hint>
          {saveHint}
        </div>
      </Card>

      <Card title="图像生成">
        <div className="space-y-4">
          <Field label="IMAGE_API_KEY">
            <input
              type="password"
              value={imageKey}
              onChange={(e) => setImageKey(e.target.value)}
              placeholder={imageKeyPlaceholder}
              className={inputCls}
            />
          </Field>
          <Field label="IMAGE_BASE_URL">
            <input
              value={imageBase}
              onChange={(e) => setImageBase(e.target.value)}
              placeholder="https://apihub.agnes-ai.com/v1"
              className={inputCls}
            />
          </Field>
          <Field label="IMAGE_MODEL">
            <input
              value={imageModel}
              onChange={(e) => setImageModel(e.target.value)}
              placeholder="agnes-image-2.0-flash"
              className={inputCls}
            />
          </Field>
          <Hint>
            图表与配图出图通道，与写作模型完全解耦。模型默认 agnes-image-2.0-flash；
            Key 以 nvapi- 开头时自动路由到 NVIDIA NIM 端点。
          </Hint>
          {saveHint}
        </div>
      </Card>

      <Card title="预算与节奏">
        <div className="grid gap-4 sm:grid-cols-2">
          <NumberField
            label="成本预算上限（美元）· RA_MAX_COST_USD"
            unit="美元，须大于 0"
            value={maxCost}
            onChange={setMaxCost}
            min="0"
          />
          <NumberField
            label="Token 总量上限 · RA_MAX_TOKENS"
            unit="tokens，≥ 1"
            value={maxTokens}
            onChange={setMaxTokens}
            min="1"
            step="1"
          />
          <NumberField
            label="轮次上限 · RA_MAX_TURNS"
            unit="轮，≥ 1"
            value={maxTurns}
            onChange={setMaxTurns}
            min="1"
            step="1"
          />
          <NumberField
            label="请求间隔（秒）· LLM_REQUEST_INTERVAL"
            unit="秒，≥ 0"
            value={reqInterval}
            onChange={setReqInterval}
            min="0"
          />
          <NumberField
            label="首字节超时（秒）· RA_LLM_FIRST_BYTE_TIMEOUT"
            unit="秒，≥ 5"
            value={firstByteTimeout}
            onChange={setFirstByteTimeout}
            min="5"
          />
        </div>
        <div className="mt-4 space-y-4">
          <Hint>
            单次任务的硬性预算（超出即优雅停止并保留已产出内容）与两次写作模型调用
            之间的最小间隔（限速防 429）。留空表示不设上限 / 使用默认节奏。
          </Hint>
          {saveHint}
        </div>
      </Card>

      <Card title="审批与权限">
        <div className="space-y-4">
          <Field label="审批模式 · RA_APPROVAL_MODE">
            <select value={approvalMode} onChange={(e) => setApprovalMode(e.target.value)} className={inputCls}>
              <option value="off">off —— 工具调用直接执行，无需人工确认</option>
              <option value="interactive">interactive —— 工具调用前逐次人工确认</option>
            </select>
          </Field>
          <Field label="权限拦截 · RA_PERMISSION_MODE">
            <select value={permissionMode} onChange={(e) => setPermissionMode(e.target.value)} className={inputCls}>
              <option value="deny_dangerous">deny_dangerous —— 拦截灾难性命令（默认）</option>
              <option value="off">off —— 不做权限拦截</option>
            </select>
          </Field>
          <Hint>
            审批模式控制工具是否需要人工放行（交互式任务中会弹出审批卡片）；权限拦
            控针对不可逆的系统级破坏操作（格式化磁盘、递归删除等），不影响正常读写。
          </Hint>
          {saveHint}
        </div>
      </Card>

      <Card title="项目长期指令">
        <div className="space-y-3">
          <p className="text-[11.5px] leading-5 text-ink-3">
            面向整个研究项目的持久要求（领域约定、写作规范、引用风格、数据说明等）。
            会注入到流水线每个子代理的系统提示，随项目数据一起保存。
          </p>
          <textarea
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            rows={6}
            placeholder={"例：本文聚焦钙钛矿太阳能电池；引用采用 Nature 格式；图表标题使用中英双语…"}
            className={`${inputCls} resize-y font-mono text-[12.5px]`}
          />
          {instrStatus && <div className="text-[12px] text-ink-2">{instrStatus}</div>}
          <button
            type="button"
            onClick={() => void saveInstructions()}
            className="rounded-xl bg-accent px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover"
          >
            保存项目指令
          </button>
        </div>
      </Card>

      {sys && (
        <>
          <Card title="模型与端点">
            <InfoRow label="模型" value={sys.model} mono />
            <InfoRow label="Provider" value={sys.provider} />
            <InfoRow label="API Host" value={sys.base_url_host} mono />
            <InfoRow label="输出目录" value={sys.output_folder} mono />
          </Card>
          <Card title="机制开关">
            <InfoRow label="重复调用阈值 RA_REPEAT_TOOL_LIMIT" value={String(sys.repeat_limit ?? "")} mono />
            <InfoRow label="流水线状态机 RA_PIPELINE" value={onoff(sys.pipeline)} />
            <InfoRow label="自动续跑 RA_AUTO_CONTINUE" value={onoff(sys.auto_continue)} />
          </Card>
          <Card title="运行环境">
            <InfoRow label="版本" value={sys.version} mono />
            <InfoRow label="Python" value={sys.python} mono />
            <InfoRow label="活动任务" value={String(sys.active_tasks ?? "")} />
          </Card>
        </>
      )}

      <ConfirmDialog
        open={confirmOverwrite}
        title="覆盖现有配置？"
        description="当前已保存过配置。保存将整体替换现有的模型接入设置，并按本页表单更新联网检索、图像生成、预算与审批配置，旧值不会保留；进行中的任务不受影响，新任务即刻使用新配置。"
        confirmLabel="覆盖保存"
        danger
        busy={busy === "save"}
        onCancel={() => setConfirmOverwrite(false)}
        onConfirm={() => {
          setConfirmOverwrite(false);
          void performSave();
        }}
      />
    </div>
  );
}
