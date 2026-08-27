import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

type Job = { id: string; workflow_id: string; status: string; attempts: number; max_attempts: number; run_after: number; last_error: string; created_at: number; estimated_seconds?: number | null; estimated_wait_seconds?: number; resource_key?: string; task_id?: string | null; payload?: { query?: string } };
type Trigger = { id: string; workflow_id: string; interval_seconds: number; enabled: boolean; next_run: number; last_run?: number | null };
type Workflow = { id: string; title?: string; description?: string };

const STATUS: Record<string, string> = { queued: "排队中", running: "执行中", complete: "已完成", failed: "失败" };

export function SchedulerView() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [triggers, setTriggers] = useState<Trigger[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [workflow, setWorkflow] = useState("paper");
  const [query, setQuery] = useState("");
  const [interval, setIntervalValue] = useState("3600");
  const [priority, setPriority] = useState("0");
  const [busy, setBusy] = useState(false);
  const refresh = useCallback(async () => {
    const [j, t, w] = await Promise.all([api.get<Job[]>("/api/scheduler/jobs"), api.get<Trigger[]>("/api/scheduler/triggers"), api.get<Workflow[]>("/api/scheduler/workflows")]);
    setJobs(j); setTriggers(t); setWorkflows(w);
  }, []);
  useEffect(() => {
    document.title = "研究助手 · 运行队列";
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [refresh]);
  const payload = query.trim() ? { query: query.trim() } : {};
  async function enqueue() { setBusy(true); try { await api.post("/api/scheduler/jobs", { workflow_id: workflow, payload, priority: Number(priority) }); await refresh(); } finally { setBusy(false); } }
  async function schedule() { setBusy(true); try { await api.post("/api/scheduler/triggers", { workflow_id: workflow, interval_seconds: Number(interval), payload }); await refresh(); } finally { setBusy(false); } }
  return <div className="mx-auto max-w-5xl p-6"><header className="mb-6 flex items-start justify-between"><div><div className="text-[10px] uppercase tracking-widest text-accent">Task Scheduler</div><h1 className="mt-1 text-xl font-semibold">运行队列</h1><p className="mt-1 text-sm text-ink-2">统一观察即时、后台和定时科研工作流。</p></div><button onClick={() => void refresh()} className="rounded-lg border border-edge px-3 py-1.5 text-xs hover:bg-surface-2">刷新</button></header>
    <section className="mb-5 rounded-2xl border border-edge bg-surface p-4 shadow-card"><div className="grid gap-3 md:grid-cols-[1.2fr_1.8fr_100px_100px_auto_auto]"><select aria-label="工作流" value={workflow} onChange={e => setWorkflow(e.target.value)} className="rounded-lg border border-edge bg-canvas px-3 py-2 text-sm">{workflows.map(item => <option key={item.id} value={item.id}>{item.title || item.id}</option>)}</select><input aria-label="研究任务" value={query} onChange={e => setQuery(e.target.value)} className="rounded-lg border border-edge bg-canvas px-3 py-2 text-sm" placeholder="研究问题（可选，定时任务会复用）" /><input aria-label="优先级" value={priority} onChange={e => setPriority(e.target.value)} type="number" min="-100" max="100" className="rounded-lg border border-edge bg-canvas px-3 py-2 text-sm" placeholder="优先级" /><input aria-label="间隔秒数" value={interval} onChange={e => setIntervalValue(e.target.value)} type="number" min="10" className="rounded-lg border border-edge bg-canvas px-3 py-2 text-sm" placeholder="秒" /><button disabled={busy} onClick={() => void enqueue()} className="rounded-lg bg-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-50">立即排队</button><button disabled={busy} onClick={() => void schedule()} className="rounded-lg border border-edge px-3 py-2 text-xs disabled:opacity-50">添加定时</button></div></section>
    <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]"><section className="rounded-2xl border border-edge bg-surface shadow-card"><div className="border-b border-edge px-5 py-3.5"><h2 className="text-sm font-semibold">队列任务</h2></div><div className="space-y-2 p-3">{jobs.length === 0 ? <p className="p-5 text-center text-xs text-ink-3">暂无队列任务。</p> : jobs.map(job => <div key={job.id} className="rounded-xl border border-edge/70 p-3"><div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${job.status === "running" ? "animate-pulse bg-warn" : job.status === "complete" ? "bg-ok" : job.status === "failed" ? "bg-danger" : "bg-ink-3"}`} /><span className="text-xs font-medium">{job.workflow_id}</span><span className="ml-auto text-[10px] text-ink-3">{STATUS[job.status] || job.status}</span></div>{job.payload?.query && <div className="mt-1 line-clamp-2 text-[11px] text-ink-2">{job.payload.query}</div>}<div className="mt-1 text-[10px] text-ink-3">尝试 {job.attempts}/{job.max_attempts} · {job.task_id ? `task ${job.task_id}` : "尚未创建 task"}</div>{job.last_error && <div className="mt-1 text-[10px] text-danger">{job.last_error}</div>}</div>)}</div></section><section className="rounded-2xl border border-edge bg-surface shadow-card"><div className="border-b border-edge px-5 py-3.5"><h2 className="text-sm font-semibold">定时触发器</h2></div><div className="space-y-2 p-3">{triggers.length === 0 ? <p className="p-5 text-center text-xs text-ink-3">暂无定时触发器。</p> : triggers.map(trigger => <div key={trigger.id} className="rounded-xl border border-edge/70 p-3"><div className="text-xs font-medium">{trigger.workflow_id}</div><div className="mt-1 text-[10px] text-ink-3">每 {trigger.interval_seconds} 秒 · 下次 {new Date(trigger.next_run * 1000).toLocaleString()}</div></div>)}</div></section></div>
  </div>;
}
