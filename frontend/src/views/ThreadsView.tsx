import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";

type Thread = { id: string; title: string; kind: string; status: string; context_summary: string; parent_thread_id?: string | null; updated_at: number; items?: AgentItem[] };
type AgentItem = { id: string; seq: number; type: string; title: string; status: string; role?: string | null; content: Record<string, unknown>; created_at: number };

export function ThreadsView() {
  const { threadId } = useParams();
  const [threads, setThreads] = useState<Thread[]>([]);
  const [selected, setSelected] = useState<Thread | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const all = await api.get<Thread[]>("/api/threads"); setThreads(all);
    const id = threadId || all[0]?.id;
    if (id) setSelected(await api.get<Thread>(`/api/threads/${encodeURIComponent(id)}`)); else setSelected(null);
  }, [threadId]);
  useEffect(() => { document.title = "研究助手 · 线程"; void load(); }, [load]);

  async function fork() {
    if (!selected) return; setBusy(true);
    try { const created = await api.post<Thread>(`/api/threads/${selected.id}/fork`, {}); window.location.hash = `#/threads/${created.id}`; } finally { setBusy(false); }
  }

  return <div className="flex h-full min-h-0">
    <aside className="w-72 shrink-0 overflow-y-auto border-r border-edge bg-canvas p-3"><div className="mb-3 flex items-center justify-between px-1"><div><h1 className="text-sm font-semibold">研究线程</h1><p className="text-[10.5px] text-ink-3">任务、分支与持续上下文</p></div><Link to="/tasks" className="text-xs text-accent">新任务</Link></div><div className="space-y-2">{threads.map(thread => <Link key={thread.id} to={`/threads/${thread.id}`} className={`block rounded-xl border p-3 ${selected?.id === thread.id ? "border-accent/50 bg-accent-tint/35" : "border-edge bg-surface hover:border-accent/30"}`}><div className="flex items-center gap-2"><span className="rounded bg-surface-2 px-1.5 py-0.5 text-[9px] text-ink-2">{thread.kind}</span><span className="ml-auto text-[9.5px] text-ink-3">{thread.status}</span></div><div className="mt-1.5 line-clamp-2 text-xs font-medium">{thread.title || "未命名线程"}</div><div className="mt-1 text-[9.5px] text-ink-3">{formatRelative(thread.updated_at)}</div></Link>)}{threads.length === 0 && <div className="rounded-xl border border-dashed border-edge p-5 text-center text-xs text-ink-3">暂无线程</div>}</div></aside>
    <main className="min-w-0 flex-1 overflow-y-auto">{selected ? <div className="mx-auto max-w-4xl p-6"><header className="mb-5 flex items-start gap-3"><div className="min-w-0 flex-1"><div className="text-[10px] uppercase tracking-widest text-accent">{selected.kind} thread</div><h2 className="mt-1 text-lg font-semibold">{selected.title || "未命名线程"}</h2>{selected.context_summary && <p className="mt-1 text-xs text-ink-2">{selected.context_summary}</p>}</div><button disabled={busy} onClick={() => void fork()} className="rounded-lg border border-edge px-3 py-1.5 text-xs hover:bg-surface-2 disabled:opacity-50">分支线程</button></header><div className="relative space-y-3 before:absolute before:bottom-0 before:left-[15px] before:top-0 before:w-px before:bg-edge">{(selected.items || []).map(item => <article key={item.id} className="relative ml-8 rounded-xl border border-edge bg-surface p-3.5 shadow-card"><span className={`absolute -left-[25px] top-4 h-3 w-3 rounded-full border-2 border-canvas ${item.type === "error" ? "bg-danger" : item.type === "progress" ? "bg-warn" : "bg-accent"}`} /><div className="flex items-center gap-2"><span className="text-[10px] font-medium text-accent">{item.type}</span>{item.role && <span className="text-[10px] text-ink-3">{item.role}</span>}<span className="ml-auto font-mono text-[9px] text-ink-3">#{item.seq}</span></div><div className="mt-1 text-xs font-medium">{item.title || "Agent 事件"}</div><pre className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-2.5 font-mono text-[10.5px] leading-4 text-ink-2">{JSON.stringify(item.content, null, 2)}</pre></article>)}{(!selected.items || selected.items.length === 0) && <div className="ml-8 rounded-xl border border-dashed border-edge p-8 text-center text-xs text-ink-3">这个线程尚无 Agent 项目。</div>}</div></div> : <div className="flex h-full items-center justify-center text-sm text-ink-3">选择或启动一个研究线程</div>}</main>
  </div>;
}
