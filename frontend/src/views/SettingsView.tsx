import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SettingsData } from "@/lib/types";

/** 服务商预设：选择后自动填 Base URL 与模型名（均可再改）。 */
const PRESETS = [
  { id: "custom", label: "自定义", base: "", model: "", provider: "" },
  { id: "deepseek", label: "DeepSeek 深度求索", base: "https://api.deepseek.com", model: "deepseek-chat", provider: "openai" },
  { id: "qwen", label: "通义千问（百炼）", base: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus", provider: "openai" },
  { id: "openai", label: "OpenAI 官方", base: "https://api.openai.com/v1", model: "gpt-4o", provider: "openai" },
  { id: "anthropic", label: "Anthropic 官方", base: "", model: "claude-sonnet-4-6", provider: "anthropic" },
] as const;

type StatusInfo = Record<string, any>;

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

const onoff = (v: unknown) =>
  v === true || v === "true" || v === 1 ? "开启" : String(v ?? "关闭");

/** 设置页：模型接入（写工作目录 .env，即刻生效）+ 系统信息只读面板。 */
export function SettingsView() {
  const [cfg, setCfg] = useState<SettingsData | null>(null);
  const [sys, setSys] = useState<StatusInfo | null>(null);
  const [preset, setPreset] = useState("custom");
  const [base, setBase] = useState("");
  const [model, setModel] = useState("");
  const [key, setKey] = useState("");
  const [provider, setProvider] = useState("");
  const [status, setStatus] = useState<{ kind: "" | "ok" | "err" | "pending"; text: string }>({
    kind: "",
    text: "",
  });
  const [busy, setBusy] = useState<"" | "test" | "save">("");

  useEffect(() => {
    document.title = "研究助手 · 设置";
    Promise.allSettled([api.get<StatusInfo>("/api/status"), api.get<SettingsData>("/api/settings")])
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
        }
      });
  }, []);

  function pickPreset(id: string) {
    setPreset(id);
    const p = PRESETS.find((x) => x.id === id) || PRESETS[0];
    setBase(p.base);
    setModel(p.model);
    setProvider(p.provider);
  }

  const formValues = () => ({
    llm_base_url: base.trim(),
    llm_model: model.trim(),
    llm_provider: provider,
    llm_api_key: key.trim(), // 留空 = 沿用已配置 Key（后端合并，不回显明文）
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

  async function save() {
    setBusy("save");
    try {
      const r = await api.post<{ env_file: string; llm_api_key_masked: string }>(
        "/api/settings",
        formValues(),
      );
      setCfg({ ...(cfg || ({} as SettingsData)), configured: true });
      setKey("");
      setStatus({ kind: "ok", text: `✓ 已保存到 ${r.env_file}，即刻生效（${r.llm_api_key_masked}）` });
      // 刷新「模型与端点」等信息卡：其数据来自挂载时的一次性快照（R7 反馈 #2）
      api.get<StatusInfo>("/api/status").then(setSys).catch(() => {});
    } catch (e) {
      setStatus({ kind: "err", text: `✗ 保存失败：${(e as Error).message}` });
    } finally {
      setBusy("");
    }
  }

  const keyPlaceholder = cfg?.configured
    ? `已配置（${cfg.llm_api_key_masked || "***"}），留空则沿用现有`
    : "sk-…";

  return (
    <div className="mx-auto max-w-3xl space-y-5 px-6 py-6">
      <Card title="模型接入">
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
              placeholder="deepseek-chat"
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
            目录里的配置会在首次打开本页时自动迁移。图像 / 搜索等高级配置请直接
            编辑该文件。
          </p>
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
            <InfoRow label="审批模式 RA_APPROVAL_MODE" value={sys.approval_mode} mono />
            <InfoRow label="权限拦截 RA_PERMISSION_MODE" value={sys.permission_mode} mono />
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
    </div>
  );
}
