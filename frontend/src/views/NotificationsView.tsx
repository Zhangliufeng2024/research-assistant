import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";

type Notification = { id: string; kind: string; title: string; message: string; object_type?: string | null; object_id?: string | null; read_at?: number | null; created_at: number };

/** R17 2.2：object_id → 落点路由（此前只展示不可跳转）。
 * 任务类对象落任务中心（检索面板可定位），会话类落 /chat/:id 深链。 */
function objectLink(objectType: string | null | undefined, objectId: string | null | undefined): string | null {
  if (!objectId) return null;
  const kind = (objectType || "").toLowerCase();
  if (kind.includes("session") || kind.includes("chat")) {
    return `/chat/${encodeURIComponent(objectId)}`;
  }
  if (kind.includes("task") || kind.includes("job") || kind.includes("run") || kind.includes("thread") || kind.includes("approval")) {
    return "/tasks";
  }
  return null;
}

export function NotificationsView() {
  const [items, setItems] = useState<Notification[]>([]);
  const refresh = useCallback(() => api.get<Notification[]>("/api/notifications?limit=200").then(setItems).catch(() => setItems([])), []);
  useEffect(() => { document.title = "研究助手 · 通知中心"; void refresh(); }, [refresh]);
  async function markRead(id: string) { await api.post(`/api/notifications/${id}/read`); setItems(current => current.map(item => item.id === id ? { ...item, read_at: Date.now() / 1000 } : item)); }
  return <div className="mx-auto max-w-4xl p-6"><header className="mb-6 flex items-start justify-between"><div><div className="text-[10px] uppercase tracking-widest text-accent">Activity Center</div><h1 className="mt-1 text-xl font-semibold">通知中心</h1><p className="mt-1 text-sm text-ink-2">任务完成、审批、质量风险和产物审阅都会在这里留下记录。</p></div><button type="button" onClick={() => void refresh()} className="rounded-lg border border-edge px-3 py-1.5 text-xs hover:bg-surface-2">刷新</button></header><div className="space-y-2">{items.length === 0 ? <div className="rounded-xl border border-dashed border-edge p-8 text-center text-xs text-ink-3">暂无通知。</div> : items.map(item => <div key={item.id} className={`rounded-xl border p-4 ${item.read_at ? "border-edge bg-surface" : "border-accent/30 bg-accent-tint/20"}`}><div className="flex items-start gap-3"><span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${item.read_at ? "bg-ink-3" : "bg-accent"}`} /><div className="min-w-0 flex-1"><div className="flex items-center gap-2"><h2 className="text-sm font-medium">{item.title}</h2><span className="text-[10px] text-ink-3">{formatRelative(item.created_at)}</span></div><p className="mt-1 text-xs text-ink-2">{item.message}</p><div className="mt-1 flex items-center gap-2 text-[10px] text-ink-3"><span>{item.kind}{item.object_id ? ` · ${item.object_type || "object"}:${item.object_id.slice(0, 10)}` : ""}</span>{objectLink(item.object_type, item.object_id) && <Link to={objectLink(item.object_type, item.object_id)!} className="rounded border border-edge px-1.5 py-px text-[10px] text-accent-hover transition-colors hover:border-accent/50 dark:text-accent">查看来源 →</Link>}</div></div>{!item.read_at && <button type="button" onClick={() => void markRead(item.id)} className="shrink-0 rounded-lg border border-edge px-2.5 py-1 text-[11px] hover:border-accent/50">标为已读</button>}</div></div>)}</div></div>;
}
