import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Agent = {
  agent_id: string;
  role: string;
  role_title: string;
  title: string;
  status: string;
  error?: string;
  seconds?: number | null;
};

type AgentRoster = { agents: Agent[] };

const STATUS: Record<string, string> = {
  pending: "等待", running: "执行中", done: "完成", failed: "失败", skipped: "跳过", cancelled: "取消",
};

export function AgentPanel({ taskId, statusHint }: { taskId: string | null; statusHint: string }) {
  const [roster, setRoster] = useState<AgentRoster | null>(null);
  useEffect(() => {
    if (!taskId) { setRoster(null); return; }
    const refresh = () => api.get<AgentRoster>(`/api/tasks/${encodeURIComponent(taskId)}/agents`).then(setRoster).catch(() => setRoster(null));
    void refresh();
    const timer = window.setInterval(refresh, statusHint.includes("running") ? 2000 : 5000);
    return () => window.clearInterval(timer);
  }, [taskId, statusHint]);
  if (!taskId || !roster || roster.agents.length === 0) return null;
  return <section className="shrink-0 border-b border-edge bg-surface/60 px-5 py-2.5">
    <div className="mb-2 flex items-center justify-between"><div><h2 className="text-xs font-semibold">Agent 协作</h2><p className="text-[10px] text-ink-3">角色、状态、耗时和失败隔离</p></div><span className="text-[10px] text-ink-3">{roster.agents.filter(a => a.status === "done").length}/{roster.agents.length} 已完成</span></div>
    <div className="flex gap-2 overflow-x-auto pb-0.5">{roster.agents.map(agent => <div key={agent.agent_id} className="min-w-44 rounded-lg border border-edge bg-canvas px-2.5 py-2">
      <div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${agent.status === "running" ? "animate-pulse bg-warn" : agent.status === "done" ? "bg-ok" : agent.status === "failed" ? "bg-danger" : "bg-ink-3"}`} /><span className="truncate text-[11px] font-medium">{agent.role_title || agent.role || agent.agent_id}</span><span className="ml-auto text-[10px] text-ink-3">{STATUS[agent.status] || agent.status}</span></div>
      <div className="mt-1 truncate text-[10.5px] text-ink-2">{agent.title}</div>
      <div className="mt-1 text-[10px] text-ink-3">{agent.seconds == null ? "—" : `${agent.seconds.toFixed(1)}s`}{agent.error ? <span className="ml-2 text-danger" title={agent.error}>有错误</span> : null}</div>
    </div>)}</div>
  </section>;
}
