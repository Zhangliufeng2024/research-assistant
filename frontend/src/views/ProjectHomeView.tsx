import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";

type Thread = { id: string; title: string; status: string; kind: string; updated_at: number };
type Task = { id: string; query: string; status: string; updated_at: number; metadata?: Record<string, unknown> };
type QualityItem = { id: string; severity: string; gate: string; message: string; object_type: string; object_id: string };
type Artifact = { id: string; artifact_path: string; status: string; updated_at: number };
type Decision = { id: string; title: string; rationale: string; updated_at: number };
type Notification = { id: string; kind: string; title: string; message: string; created_at: number };
type Approval = { id: string; task_id?: string | null; agent_id: string; role: string; tool_name: string; summary: string; created_at: number };
type Activity = { id: string; kind: string; title: string; message: string; ts: number; severity?: string; status?: string };
type Home = {
  project: { id: string; name: string; root: string; instructions: string };
  overview: { counts: Record<string, number>; uncovered_claims: number };
  quality: { ready_for_synthesis: boolean; failed_runs: number; orphan_evidence: number; stale_evidence?: number; claims: { total: number; supported: number; uncovered: number; conflicted?: number } };
  threads: Thread[]; tasks: Task[]; quality_items: QualityItem[]; artifacts: Artifact[]; decisions: Decision[];
  usage: { summary: { cost_usd: number; total_tokens: number; turns: number; runs: number; failed_runs: number; seconds: number } };
  notifications: Notification[];
  activity: Activity[];
};

const STATUS: Record<string, string> = { running: "执行中", queued: "排队", complete: "完成", failed: "失败", interrupted: "中断", idle: "空闲", archived: "归档" };

function Empty({ children }: { children: React.ReactNode }) { return <div className="rounded-xl border border-dashed border-edge p-5 text-center text-xs text-ink-3">{children}</div>; }

export function ProjectHomeView() {
  const [home, setHome] = useState<Home | null>(null);
  const [error, setError] = useState("");
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [recentProjects, setRecentProjects] = useState<Array<{ name: string; root: string; pinned?: boolean }>>([]);
  const refresh = useCallback(() => api.get<Home>("/api/project/home").then(setHome).catch((e: Error) => setError(e.message)), []);
  const refreshApprovals = useCallback(() => api.get<Approval[]>("/api/approvals").then(setApprovals).catch(() => setApprovals([])), []);
  useEffect(() => {
    document.title = "研究助手 · 项目"; void refresh(); void refreshApprovals();
    try {
      const stored = JSON.parse(localStorage.getItem("ra.recentProjects") || "[]") as Array<{ name: string; root: string; pinned?: boolean }>;
      const current = home?.project;
      setRecentProjects(stored);
      if (current && !stored.some(item => item.root === current.root)) {
        const next = [{ name: current.name, root: current.root }, ...stored].slice(0, 12);
        localStorage.setItem("ra.recentProjects", JSON.stringify(next)); setRecentProjects(next);
      }
    } catch { setRecentProjects([]); }
  }, [refresh, refreshApprovals, home?.project]);
  async function resolveApproval(id: string, approved: boolean) { await api.post(`/api/approvals/${id}/resolve`, { approved }); setApprovals(items => items.filter(item => item.id !== id)); }

  if (!home) return <div className="flex h-full items-center justify-center text-sm text-ink-3">{error || "正在加载项目空间…"}</div>;
  const running = home.tasks.filter(t => ["queued", "running", "stopping"].includes(t.status));
  const risk = home.overview.uncovered_claims + home.quality.failed_runs + home.quality_items.length;

  return <div className="mx-auto max-w-7xl px-6 py-6">
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div><div className="text-[11px] font-medium uppercase tracking-[0.16em] text-accent">Research Project</div><h1 className="mt-1 text-2xl font-semibold tracking-tight">{home.project.name}</h1><p className="mt-1 max-w-2xl truncate text-[12.5px] text-ink-3" title={home.project.root}>{home.project.root}</p></div>
      <div className="flex flex-wrap items-center gap-2"><select aria-label="最近项目" value="" onChange={async event => { const root = event.target.value; if (!root) return; await api.post("/api/workspace/root", { path: root }); window.location.reload(); }} className="max-w-52 rounded-xl border border-edge bg-surface px-3 py-2 text-xs"><option value="">最近项目…</option>{recentProjects.map(item => <option key={item.root} value={item.root}>{item.pinned ? "★ " : ""}{item.name}</option>)}</select><button type="button" onClick={() => { const next = recentProjects.map(item => item.root === home.project.root ? { ...item, pinned: !item.pinned } : item); localStorage.setItem("ra.recentProjects", JSON.stringify(next)); setRecentProjects(next); }} className="rounded-xl border border-edge bg-surface px-3 py-2 text-xs hover:bg-surface-2">{recentProjects.find(item => item.root === home.project.root)?.pinned ? "取消固定" : "固定项目"}</button><Link to="/tasks" className="rounded-xl bg-accent px-4 py-2 text-[13px] font-medium text-white hover:bg-accent-hover">启动 Agent 任务</Link><Link to="/sources" className="rounded-xl border border-edge bg-surface px-4 py-2 text-[13px] font-medium hover:bg-surface-2">导入资料</Link><a href="/api/project/export" className="rounded-xl border border-edge bg-surface px-4 py-2 text-[13px] font-medium hover:bg-surface-2">导出研究包</a></div>
    </header>

    <section className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
      {[["运行中任务", running.length, running.length ? "text-warn" : "text-ok"], ["研究线程", home.threads.length, ""], ["主张", home.quality.claims.total, ""], ["已覆盖主张", home.quality.claims.supported, "text-ok"], ["待补证据", home.overview.uncovered_claims, home.overview.uncovered_claims ? "text-warn" : "text-ok"], ["质量风险", risk, risk ? "text-danger" : "text-ok"]].map(([label, value, cls]) => <div key={String(label)} className="rounded-2xl border border-edge bg-surface p-4 shadow-card"><div className="text-[11px] text-ink-3">{label}</div><div className={`mt-1 text-2xl font-semibold ${cls}`}>{value}</div></div>)}
    </section>

    <section className={`mt-4 rounded-2xl border p-4 ${home.quality.ready_for_synthesis ? "border-ok/35 bg-ok/5" : "border-warn/35 bg-warn/5"}`}>
      <div className="flex items-center gap-3"><div className={`flex h-9 w-9 items-center justify-center rounded-xl ${home.quality.ready_for_synthesis ? "bg-ok/15 text-ok" : "bg-warn/15 text-warn"}`}>{home.quality.ready_for_synthesis ? "✓" : "!"}</div><div><div className="text-sm font-semibold">{home.quality.ready_for_synthesis ? "证据条件允许进入综合写作" : "当前研究尚未满足综合写作门禁"}</div><p className="mt-0.5 text-xs text-ink-2">未覆盖主张 {home.quality.claims.uncovered} · 冲突主张 {home.quality.claims.conflicted ?? 0} · 过期证据 {home.quality.stale_evidence ?? 0} · 失败运行 {home.quality.failed_runs}</p></div><Link to="/research" className="ml-auto text-xs font-medium text-accent">查看证据链 →</Link></div>
    </section>

    <div className="mt-5 grid gap-5 xl:grid-cols-[1.35fr_1fr]">
      <div className="space-y-5">
        <section className="rounded-2xl border border-edge bg-surface shadow-card"><div className="flex items-center justify-between border-b border-edge px-5 py-3.5"><div><h2 className="text-sm font-semibold">Agent 任务</h2><p className="mt-0.5 text-[11px] text-ink-3">任务是项目中的主要执行单元</p></div><Link to="/tasks" className="text-xs text-accent">全部任务</Link></div><div className="p-3">{home.tasks.length === 0 ? <Empty>尚无任务，启动一次研究工作流。</Empty> : <div className="space-y-2">{home.tasks.map(task => <Link to="/tasks" key={task.id} className="flex items-center gap-3 rounded-xl border border-edge/70 p-3 hover:border-accent/35 hover:bg-surface-2"><span className={`h-2 w-2 rounded-full ${task.status === "running" ? "animate-pulse bg-warn" : task.status === "complete" ? "bg-ok" : task.status === "failed" ? "bg-danger" : "bg-ink-3"}`} /><div className="min-w-0 flex-1"><div className="truncate text-[13px] font-medium">{task.query}</div><div className="mt-0.5 text-[10.5px] text-ink-3">{task.id} · {formatRelative(task.updated_at)}</div></div><span className="rounded-lg bg-surface-2 px-2 py-1 text-[10.5px] text-ink-2">{STATUS[task.status] || task.status}</span></Link>)}</div>}</div></section>
        <section className="rounded-2xl border border-edge bg-surface shadow-card"><div className="flex items-center justify-between border-b border-edge px-5 py-3.5"><div><h2 className="text-sm font-semibold">研究线程</h2><p className="mt-0.5 text-[11px] text-ink-3">任务、分支和持续上下文</p></div><Link to="/threads" className="text-xs text-accent">全部线程</Link></div><div className="grid gap-2 p-3 md:grid-cols-2">{home.threads.length === 0 ? <Empty>任务启动后会自动建立线程。</Empty> : home.threads.map(thread => <Link to={`/threads/${thread.id}`} key={thread.id} className="rounded-xl border border-edge/70 p-3 hover:border-accent/35 hover:bg-surface-2"><div className="flex items-center gap-2"><span className="rounded-md bg-accent-tint px-1.5 py-0.5 text-[9px] font-medium text-accent">{thread.kind}</span><span className="ml-auto text-[10px] text-ink-3">{STATUS[thread.status] || thread.status}</span></div><div className="mt-2 line-clamp-2 text-[12.5px] font-medium">{thread.title || "未命名线程"}</div><div className="mt-1 text-[10px] text-ink-3">{formatRelative(thread.updated_at)}</div></Link>)}</div></section>
      </div>

      <div className="space-y-5">
        <section className="rounded-2xl border border-edge bg-surface shadow-card"><div className="flex items-center justify-between border-b border-edge px-5 py-3.5"><div><h2 className="text-sm font-semibold">资源消耗</h2><p className="mt-0.5 text-[11px] text-ink-3">用于解释等待和成本</p></div><Link to="/scheduler" className="text-xs text-accent">运行队列</Link></div><div className="grid grid-cols-2 gap-2 p-3 md:grid-cols-4">{[["成本", `$${home.usage.summary.cost_usd.toFixed(3)}`], ["Token", home.usage.summary.total_tokens.toLocaleString()], ["回合", home.usage.summary.turns], ["耗时", `${home.usage.summary.seconds.toFixed(1)}s`]].map(([label, value]) => <div key={String(label)} className="rounded-xl bg-surface-2 p-3"><div className="text-[10px] text-ink-3">{label}</div><div className="mt-1 text-sm font-semibold">{value}</div></div>)}</div></section>
        {home.notifications.length > 0 && <section className="rounded-2xl border border-accent/25 bg-accent-tint/20 shadow-card"><div className="border-b border-accent/15 px-5 py-3.5"><h2 className="text-sm font-semibold">未读通知</h2></div><div className="space-y-2 p-3">{home.notifications.map(item => <div key={item.id} className="rounded-xl border border-edge/70 bg-surface p-3"><div className="text-xs font-medium">{item.title}</div><div className="mt-1 text-[11px] text-ink-2">{item.message}</div></div>)}</div></section>}
        <section className="rounded-2xl border border-edge bg-surface shadow-card"><div className="flex items-center justify-between border-b border-edge px-5 py-3.5"><div><h2 className="text-sm font-semibold">项目活动</h2><p className="mt-0.5 text-[11px] text-ink-3">任务、Agent、质量和产物的统一时间线</p></div><Link to="/threads" className="text-xs text-accent">查看线程 →</Link></div><div className="space-y-2 p-3">{home.activity.length === 0 ? <Empty>项目活动会在这里汇总。</Empty> : home.activity.slice(0, 8).map(item => <div key={item.id} className="flex gap-2.5 rounded-xl border border-edge/70 p-2.5"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${item.kind === "quality" || item.severity === "error" ? "bg-danger" : item.kind === "agent" ? "bg-accent" : item.kind === "artifact" ? "bg-ok" : "bg-ink-3"}`} /><div className="min-w-0"><div className="truncate text-xs font-medium">{item.title}</div><div className="mt-0.5 line-clamp-2 text-[10.5px] text-ink-2">{item.message}</div><div className="mt-0.5 text-[9.5px] text-ink-3">{formatRelative(item.ts)}</div></div></div>)}</div></section>
        {approvals.length > 0 && <section className="rounded-2xl border border-warn/35 bg-warn/5 shadow-card"><div className="border-b border-warn/20 px-5 py-3.5"><h2 className="text-sm font-semibold">Agent 审批收件箱</h2><p className="mt-0.5 text-[11px] text-ink-3">后台任务等待人工确认</p></div><div className="space-y-2 p-3">{approvals.map(item => <div key={item.id} className="rounded-xl border border-edge/70 bg-surface p-3"><div className="flex items-center gap-2 text-xs font-medium"><span>{item.tool_name}</span><span className="ml-auto text-[10px] text-ink-3">{item.agent_id || "Agent"} · {item.role || "未指定角色"}</span></div><p className="mt-1 line-clamp-2 text-[11px] text-ink-2">{item.summary}</p><div className="mt-2 flex gap-2"><button onClick={() => void resolveApproval(item.id, true)} className="rounded-lg bg-accent px-3 py-1.5 text-[11px] text-white">批准</button><button onClick={() => void resolveApproval(item.id, false)} className="rounded-lg border border-edge px-3 py-1.5 text-[11px]">拒绝</button></div></div>)}</div></section>}
        <section className="rounded-2xl border border-edge bg-surface shadow-card"><div className="flex items-center justify-between border-b border-edge px-5 py-3.5"><h2 className="text-sm font-semibold">质量风险</h2><Link to="/research" className="text-xs text-accent">质量中心</Link></div><div className="p-3">{home.quality_items.length === 0 && !home.overview.uncovered_claims ? <Empty>当前没有未解决的质量风险。</Empty> : <div className="space-y-2">{home.overview.uncovered_claims > 0 && <div className="rounded-xl border border-warn/30 bg-warn/5 p-3"><div className="text-xs font-medium text-warn">{home.overview.uncovered_claims} 条主张缺少支持证据</div><p className="mt-1 text-[10.5px] text-ink-3">在证据矩阵中关联资料片段或分析产物。</p></div>}{home.quality_items.map(item => <div key={item.id} className="rounded-xl border border-edge/70 p-3"><div className="flex gap-2"><span className={`text-[10px] font-medium ${item.severity === "error" ? "text-danger" : item.severity === "warning" ? "text-warn" : "text-accent"}`}>{item.gate}</span><span className="ml-auto text-[9.5px] text-ink-3">{item.object_type}</span></div><p className="mt-1 text-xs text-ink-2">{item.message}</p></div>)}</div>}</div></section>
        <section className="rounded-2xl border border-edge bg-surface shadow-card"><div className="flex items-center justify-between border-b border-edge px-5 py-3.5"><h2 className="text-sm font-semibold">待审阅产物</h2><Link to="/artifacts" className="text-xs text-accent">审阅中心</Link></div><div className="p-3">{home.artifacts.length === 0 ? <Empty>Agent 产物可在任务页加入审阅。</Empty> : <div className="space-y-2">{home.artifacts.map(item => <Link to="/artifacts" key={item.id} className="block rounded-xl border border-edge/70 p-3 hover:bg-surface-2"><div className="truncate text-xs font-medium">{item.artifact_path}</div><div className="mt-1 text-[10px] text-ink-3">等待审阅 · {formatRelative(item.updated_at)}</div></Link>)}</div>}</div></section>
        <section className="rounded-2xl border border-edge bg-surface shadow-card"><div className="flex items-center justify-between border-b border-edge px-5 py-3.5"><h2 className="text-sm font-semibold">最近决策</h2><Link to="/research" className="text-xs text-accent">决策日志</Link></div><div className="p-3">{home.decisions.length === 0 ? <Empty>尚未沉淀研究决策。</Empty> : <div className="space-y-2">{home.decisions.map(item => <div key={item.id} className="rounded-xl border border-edge/70 p-3"><div className="text-xs font-medium">{item.title}</div><p className="mt-1 line-clamp-2 text-[10.5px] text-ink-3">{item.rationale || "未填写理由"}</p></div>)}</div>}</div></section>
      </div>
    </div>
  </div>;
}
