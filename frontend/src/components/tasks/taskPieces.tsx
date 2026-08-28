/* 迭代2：任务中心共享部件——从 TasksView 抽出，供 进行中/看板/历史 三个
 * 分区页复用（侧栏 5 分区导航重组的支撑件）。
 * 全部为展示组件，数据获取只发生在 RunSearchPanel 内部（自带防抖检索）。
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { RUN_STATUS_LABEL } from "@/lib/protocolTask";
import type { TaskState } from "@/lib/types";
import type { DurableTask } from "@/stores/taskStore";

/* ---------- 来源会话回链（对话↔任务互链） ---------- */

/** 任务卡上的来源会话链接；无来源（旧任务）不渲染。 */
export function SourceSessionLink({ sessionId }: { sessionId?: string | null }) {
  if (!sessionId) return null;
  return (
    <Link
      to={`/chat/${encodeURIComponent(sessionId)}`}
      title="打开派生本任务的来源对话"
      className="inline-flex items-center gap-0.5 rounded-md bg-accent-tint px-1.5 py-0.5 text-[10.5px] font-medium text-accent-hover transition-colors hover:bg-accent-tint/70 dark:text-accent"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
        strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
        className="h-2.5 w-2.5" aria-hidden>
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z" />
      </svg>
      来源对话
    </Link>
  );
}

/* ---------- 任务检索（/api/runs/search） ---------- */

export interface RunSearchResult {
  total: number;
  items: Array<DurableTask & { output_dir?: string | null }>;
  limit: number;
  offset: number;
}

export const SEARCH_STATUSES = [
  { value: "", label: "全部状态" },
  { value: "queued", label: "排队中" },
  { value: "running", label: "运行中" },
  { value: "complete", label: "已完成" },
  { value: "failed", label: "失败" },
  { value: "cancelled", label: "已取消" },
  { value: "interrupted", label: "进程中断" },
];

export function RunSearchPanel({
  onObserve,
  pageSize = 10,
  showHeader = true,
}: {
  onObserve: (taskId: string) => void;
  /** 每页条数（历史独立页用 20）。 */
  pageSize?: number;
  showHeader?: boolean;
}) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [result, setResult] = useState<RunSearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const limit = pageSize;

  useEffect(() => {
    // 输入防抖 300ms；条件变化回到第一页
    const t = setTimeout(() => {
      setBusy(true);
      const params = new URLSearchParams();
      if (q.trim()) params.set("q", q.trim());
      if (status) params.set("status", status);
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      api
        .get<RunSearchResult>(`/api/runs/search?${params.toString()}`)
        .then(setResult)
        .catch(() => setResult(null))
        .finally(() => setBusy(false));
    }, 300);
    return () => clearTimeout(t);
  }, [q, status, offset, limit]);

  useEffect(() => setOffset(0), [q, status]);

  const total = result?.total ?? 0;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));

  return (
    <div className="rounded-xl border border-edge bg-surface p-3 shadow-card">
      {showHeader && <h2 className="mb-2 text-[13px] font-semibold">任务检索</h2>}
      <input
        type="text"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="搜索任务标题…"
        aria-label="搜索任务"
        className="mb-1.5 w-full rounded-lg border border-edge bg-canvas px-2.5 py-1.5 text-[12px] outline-none transition-colors placeholder:text-ink-3 focus:border-accent/60"
      />
      <select
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        aria-label="按状态筛选"
        className="mb-2 w-full rounded-lg border border-edge bg-canvas px-2 py-1.5 text-[12px] text-ink-2 outline-none focus:border-accent/60"
      >
        {SEARCH_STATUSES.map((s) => (
          <option key={s.value} value={s.value}>{s.label}</option>
        ))}
      </select>
      <div className="space-y-1.5">
        {busy && !result && (
          <div className="px-1 py-2 text-[11.5px] text-ink-3">检索中…</div>
        )}
        {result && result.items.length === 0 && (
          <div className="px-1 py-2 text-[11.5px] text-ink-3">无匹配任务</div>
        )}
        {result?.items.map((t) => (
          <div key={t.id} className="rounded-lg border border-edge/70 px-2.5 py-1.5">
            <div className="truncate text-[12px] font-medium" title={t.query}>
              {t.query}
            </div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[10.5px] text-ink-3">
              <span className="rounded bg-surface-2 px-1 py-px">
                {RUN_STATUS_LABEL[t.status] || t.status}
              </span>
              <span>{formatRelative(t.updated_at)}</span>
              <SourceSessionLink sessionId={t.source_session_id} />
              {(t.status === "running" || t.status === "queued") && (
                <button
                  type="button"
                  onClick={() => onObserve(t.id)}
                  className="ml-auto rounded border border-edge px-1.5 py-px text-[10.5px] transition-colors hover:border-accent/50 hover:text-accent"
                >
                  观察
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
      {pages > 1 && (
        <div className="mt-2 flex items-center justify-between text-[11px] text-ink-3">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
            className="rounded border border-edge px-2 py-0.5 transition-colors enabled:hover:border-accent/50 enabled:hover:text-accent disabled:opacity-40"
          >
            上一页
          </button>
          <span>{page} / {pages}（共 {total} 条）</span>
          <button
            type="button"
            disabled={offset + limit >= total}
            onClick={() => setOffset(offset + limit)}
            className="rounded border border-edge px-2 py-0.5 transition-colors enabled:hover:border-accent/50 enabled:hover:text-accent disabled:opacity-40"
          >
            下一页
          </button>
        </div>
      )}
    </div>
  );
}

/* ---------- 状态带（任务状态机显式化） ---------- */

const STATUS_STRIP_NODES = [
  { key: "queued", label: "排队" },
  { key: "running", label: "运行" },
  { key: "awaiting_approval", label: "待批准" },
  { key: "terminal", label: "终态" },
] as const;

export function StatusStrip({ task }: { task: TaskState }) {
  const currentIdx =
    task.phase === "idle"
      ? -1
      : task.approval
        ? 2
        : task.phase === "running"
          ? 1
          : 3;
  const terminalTone =
    task.phase === "done"
      ? "border-ok bg-ok/15 text-ok"
      : task.phase === "error" || task.phase === "failed" || task.phase === "cancelled"
        ? "border-danger bg-danger/15 text-danger"
        : "border-edge text-ink-3";
  const terminalLabel =
    task.phase === "done"
      ? "完成"
      : task.phase === "cancelled"
        ? "已取消"
        : task.phase === "error" || task.phase === "failed"
          ? "失败"
          : "终态";
  return (
    <div className="flex items-center gap-1" aria-label="任务状态机">
      {STATUS_STRIP_NODES.map((node, i) => {
        const reached = currentIdx >= i;
        const isCurrent = currentIdx === i;
        const label = node.key === "terminal" ? terminalLabel : node.label;
        const tone =
          node.key === "terminal" && isCurrent
            ? terminalTone
            : isCurrent
              ? "border-accent bg-accent/15 text-accent"
              : reached
                ? "border-ok/60 bg-ok/10 text-ok"
                : "border-edge text-ink-3";
        return (
          <div key={node.key} className="flex items-center gap-1">
            {i > 0 && (
              <span className={`h-px w-3 ${reached ? "bg-ok/60" : "bg-edge"}`} />
            )}
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors ${tone} ${
                node.key === "awaiting_approval" && isCurrent ? "animate-pulse" : ""
              }`}
            >
              {label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ---------- 看板视图 ---------- */

const BOARD_COLUMNS: Array<{ key: string; label: string; statuses: string[]; tone: string }> = [
  { key: "active", label: "进行中", statuses: ["queued", "running", "stopping"], tone: "border-warn/50" },
  { key: "complete", label: "已完成", statuses: ["complete"], tone: "border-ok/50" },
  { key: "failed", label: "失败/中断", statuses: ["failed", "interrupted"], tone: "border-danger/50" },
  { key: "cancelled", label: "已取消", statuses: ["cancelled"], tone: "border-edge" },
];

export function KanbanBoard({
  tasks,
  onObserve,
  perColumn = 8,
}: {
  tasks: DurableTask[];
  onObserve?: (taskId: string) => void;
  perColumn?: number;
}) {
  return (
    <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
      {BOARD_COLUMNS.map((col) => {
        const items = tasks.filter((t) => col.statuses.includes(t.status));
        return (
          <div key={col.key} className={`rounded-xl border-t-2 ${col.tone} bg-surface-2/40 p-2`}>
            <div className="mb-1.5 flex items-center justify-between px-1 text-[11px] font-semibold">
              <span>{col.label}</span>
              <span className="text-ink-3">{items.length}</span>
            </div>
            <div className="space-y-1.5">
              {items.length === 0 && (
                <div className="px-1 py-3 text-center text-[10.5px] text-ink-3">空</div>
              )}
              {items.slice(0, perColumn).map((t) => (
                <div key={t.id} className="rounded-lg border border-edge/70 bg-surface px-2 py-1.5 shadow-sm">
                  <div className="truncate text-[11.5px] font-medium" title={t.query}>
                    {t.query}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1 text-[10px] text-ink-3">
                    <span>{formatRelative(t.updated_at)}</span>
                    <SourceSessionLink sessionId={t.source_session_id} />
                    {onObserve && (t.status === "running" || t.status === "queued") && (
                      <button
                        type="button"
                        onClick={() => onObserve(t.id)}
                        className="ml-auto rounded border border-edge px-1 py-px transition-colors hover:border-accent/50 hover:text-accent"
                      >
                        观察
                      </button>
                    )}
                  </div>
                </div>
              ))}
              {items.length > perColumn && (
                <div className="px-1 text-[10px] text-ink-3">
                  另 {items.length - perColumn} 条——用检索定位
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
