import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { formatRelative, sessionTitle } from "@/lib/format";
import {
  RUN_STATUS_LABEL,
  TL_STAGES,
} from "@/lib/protocolTask";
import type { ActivityEntry, TaskState } from "@/lib/types";
import { useTaskStore, type RunSummary } from "@/stores/taskStore";
import { ApprovalCard } from "@/components/chat/ApprovalCard";
import { BudgetBar } from "@/components/chat/BudgetBar";

/* ---------- 时间轴 ---------- */

function Timeline({ task }: { task: TaskState }) {
  return (
    <div className="flex items-center gap-0 overflow-x-auto pb-1">
      {TL_STAGES.map((s, i) => {
        const st = task.timeline[i];
        return (
          <div key={s.key} className="flex shrink-0 items-center">
            <div className="flex flex-col items-center gap-1.5 px-1">
              <span
                className={`flex h-6 w-6 items-center justify-center rounded-full border text-[10px] font-semibold transition-colors ${
                  st === "done"
                    ? "border-ok bg-ok/15 text-ok"
                    : st === "active"
                      ? "border-accent bg-accent/15 text-accent"
                      : "border-edge text-ink-3"
                }`}
              >
                {st === "done" ? "✓" : i + 1}
              </span>
              <span
                className={`whitespace-nowrap text-[11px] ${
                  st === "active" ? "font-semibold text-accent" : "text-ink-3"
                }`}
              >
                {s.label}
              </span>
            </div>
            {i < TL_STAGES.length - 1 && (
              <span
                className={`mx-0.5 mb-[18px] h-px w-7 ${
                  st === "done" ? "bg-ok/60" : "bg-edge"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ---------- 活动流 ---------- */

const KIND_COLOR: Record<string, string> = {
  ok: "text-ok",
  err: "text-danger",
  warn: "text-warn",
  info: "text-ink-2",
  stage: "text-accent font-medium",
  log: "text-ink-2",
  text: "text-ink",
};

function ActivityFeed({ activity }: { activity: ActivityEntry[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [activity.length]);

  return (
    <div ref={ref} className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-4 font-mono text-[12px] leading-5">
      {activity.map((a, i) => (
        <div key={`${a.t}-${i}`}>
          {a.kind === "text" ? (
            <details className="group rounded-lg border border-edge/60 px-2.5 py-1.5">
              <summary className="cursor-pointer list-none text-ink-2 select-none">
                ▸ 模型输出片段
              </summary>
              <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap text-[11.5px] text-ink">
                {a.content}
              </pre>
            </details>
          ) : (
            <span className={KIND_COLOR[a.kind] || "text-ink-2"}>
              {a.kind === "stage" ? "" : "· "}
              {a.text}
            </span>
          )}
        </div>
      ))}
      {activity.length === 0 && (
        <div className="py-8 text-center font-sans text-sm text-ink-3">
          尚无活动——启动一次任务后，这里会实时滚动流水线日志。
        </div>
      )}
    </div>
  );
}

/* ---------- 运行历史 ---------- */

const RUN_BADGE: Record<string, string> = {
  running: "bg-warn/10 text-warn",
  complete: "bg-ok/10 text-ok",
  failed: "bg-danger/10 text-danger",
  cancelled: "bg-surface-2 text-ink-3",
  legacy: "bg-surface-2 text-ink-3",
};

function RunItem({
  run,
  onResume,
}: {
  run: RunSummary;
  onResume: (name: string) => void;
}) {
  const resumable = run.status !== "running" && run.status !== "legacy";
  const title =
    run.paper?.title || sessionTitle(run.query || null, run.query || "");
  return (
    <div className="rounded-xl border border-edge bg-surface px-3.5 py-2.5 transition-colors hover:border-accent/30">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium">{title}</span>
        <span className={`shrink-0 rounded-md px-1.5 py-0.5 text-[10.5px] font-medium ${RUN_BADGE[run.status] || RUN_BADGE.legacy}`}>
          {RUN_STATUS_LABEL[run.status] || run.status}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-3">
        <span>{formatRelative(run.updated_at)}</span>
        {resumable && (
          <button
            type="button"
            onClick={() => onResume(run.name)}
            className="ml-auto rounded-md border border-edge px-2 py-0.5 text-[11px] transition-colors hover:border-accent/50 hover:text-accent"
          >
            续跑
          </button>
        )}
      </div>
    </div>
  );
}

/* ---------- 主视图 ---------- */

export function TasksView() {
  const {
    task,
    runs,
    runsLoading,
    start,
    resume,
    respondApproval,
    steer,
    stop,
    refreshRuns,
  } = useTaskStore();

  const [query, setQuery] = useState("");
  const [multiAgent, setMultiAgent] = useState(true);
  const [maxCost, setMaxCost] = useState("");
  const [steerText, setSteerText] = useState("");
  const [notice, setNotice] = useState("");
  const running = task.phase === "running";

  useEffect(() => {
    document.title = "研究助手 · 任务";
    refreshRuns().catch(() => {});
  }, [refreshRuns]);

  async function launch() {
    const r = await start({
      query,
      multiAgent,
      maxCostUsd: maxCost.trim() ? Number(maxCost) : null,
    });
    if (r === "empty") setNotice("请填写研究主题");
    else if (r === "offline") setNotice("无法建立与服务端的连接");
    else setQuery("");
  }

  return (
    <div className="flex h-full min-h-0">
      {/* 左列：新任务 + 历史 */}
      <div className="hidden w-64 shrink-0 flex-col gap-3 overflow-y-auto border-r border-edge p-3 lg:flex">
        <div className="rounded-xl border border-edge bg-surface p-3.5 shadow-card">
          <h2 className="mb-2.5 text-[13px] font-semibold">新任务</h2>
          <textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="研究主题 / 写作要求…"
            rows={4}
            disabled={running}
            className="w-full resize-none rounded-lg border border-edge bg-canvas px-2.5 py-2 text-[12.5px] outline-none transition-colors placeholder:text-ink-3 focus:border-accent/60 disabled:opacity-60"
          />
          <label className="mt-2 flex cursor-pointer items-center gap-2 text-[12px] text-ink-2 select-none">
            <input
              type="checkbox"
              checked={multiAgent}
              onChange={(e) => setMultiAgent(e.target.checked)}
              disabled={running}
              className="accent-[var(--ra-accent)]"
            />
            多代理流水线（规划→研究→写作→定稿）
          </label>
          <input
            value={maxCost}
            onChange={(e) => setMaxCost(e.target.value)}
            placeholder="费用上限 USD（可选，如 5）"
            inputMode="decimal"
            disabled={running}
            className="mt-2 w-full rounded-lg border border-edge bg-canvas px-2.5 py-1.5 font-mono text-[12px] outline-none placeholder:font-sans placeholder:text-ink-3 focus:border-accent/60"
          />
          <button
            type="button"
            onClick={() => void launch()}
            disabled={running || !query.trim()}
            className="mt-2.5 w-full rounded-lg bg-accent px-3 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
          >
            开始生成
          </button>
          {notice && <p className="mt-2 text-[11.5px] text-danger">{notice}</p>}
        </div>

        <div className="min-h-0 flex-1">
          <h2 className="mb-2 px-1 text-[13px] font-semibold">运行历史</h2>
          <div className="space-y-2">
            {runsLoading && runs.length === 0 && (
              <div className="px-1 text-[12px] text-ink-3">加载中…</div>
            )}
            {!runsLoading && runs.length === 0 && (
              <div className="px-1 text-[12px] text-ink-3">暂无运行记录</div>
            )}
            {runs.slice(0, 20).map((r) => (
              <RunItem
                key={r.name}
                run={r}
                onResume={(name) => {
                  void resume(name).then((res) => {
                    if (res === "offline") setNotice("无法建立与服务端的连接");
                  });
                }}
              />
            ))}
          </div>
        </div>
      </div>

      {/* 右侧：任务面板 */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* 时间轴工具条 */}
        <div className="flex shrink-0 items-center gap-4 border-b border-edge px-5 py-2.5">
          <Timeline task={task} />
          <div className="ml-auto flex shrink-0 items-center gap-2.5 pl-3">
            {task.budget && (
              <div className="hidden xl:block">
                <BudgetBar budget={task.budget} />
              </div>
            )}
            {running && (
              <button
                type="button"
                onClick={() => void stop()}
                className="rounded-lg border border-edge bg-surface px-2.5 py-1 text-[12px] font-medium text-danger transition-colors hover:bg-surface-2"
              >
                停止
              </button>
            )}
          </div>
        </div>

        {task.error && (
          <div className="shrink-0 bg-danger/10 px-5 py-2 text-[12.5px] text-danger">
            {task.error}
          </div>
        )}

        {/* 结果横幅 */}
        {task.phase === "done" && task.result?.status !== "failed" && (
          <div className="shrink-0 bg-ok/10 px-5 py-2 text-[12.5px] text-ok">
            ✓ 生成完成{(task.result?.metadata?.title || task.result?.paper_name) &&
              `：${task.result.metadata?.title || task.result.paper_name}`}
            ——成果见「文库」页。
          </div>
        )}

        <ActivityFeed activity={task.activity} />

        {/* 审批 + steer */}
        <AnimatePresence>
          {task.approval && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 12 }}
              className="mx-auto w-full max-w-xl px-4 pb-2"
            >
              <ApprovalCard approval={task.approval} onRespond={respondApproval} />
            </motion.div>
          )}
        </AnimatePresence>

        {running && (
          <div className="shrink-0 border-t border-edge px-4 py-2.5">
            <div className="mx-auto flex max-w-xl items-center gap-2">
              <input
                value={steerText}
                onChange={(e) => setSteerText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && steerText.trim()) {
                    steer(steerText);
                    setSteerText("");
                  }
                }}
                placeholder="引导指令（Enter 注入下一步）…"
                className="flex-1 rounded-xl border border-edge bg-surface px-3.5 py-2 text-[13px] outline-none transition-colors placeholder:text-ink-3 focus:border-accent/60"
              />
              <button
                type="button"
                onClick={() => {
                  if (steerText.trim()) {
                    steer(steerText);
                    setSteerText("");
                  }
                }}
                disabled={!steerText.trim()}
                className="rounded-xl bg-surface-2 px-3.5 py-2 text-[13px] font-medium transition-colors hover:bg-edge disabled:opacity-50"
              >
                注入
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
