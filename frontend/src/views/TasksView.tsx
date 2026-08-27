import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import { formatRelative, sessionTitle } from "@/lib/format";
import { loadDockCollapsed, saveDockCollapsed } from "@/lib/artifacts";
import { api } from "@/lib/api";
import {
  RUN_STATUS_LABEL,
  TL_STAGES,
} from "@/lib/protocolTask";
import { gateReason, type TaskGateCtx } from "@/lib/taskGate";
import type { ActivityEntry, TaskState } from "@/lib/types";
import { useTaskStore, type RunSummary } from "@/stores/taskStore";
import { toast } from "@/stores/toastStore";
import { ApprovalCard } from "@/components/chat/ApprovalCard";
import { ArtifactsPanel } from "@/components/chat/ArtifactsPanel";
import { BudgetBar } from "@/components/chat/BudgetBar";
import { AgentPanel } from "@/components/agent/AgentPanel";

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

interface WorkflowStep { id: string; title: string; depends_on: string[]; status: string }
interface WorkflowMetrics { total_seconds: number; event_count: number; critical_path_seconds: number }

function WorkflowPlan({ taskId, statusHint }: { taskId: string | null; statusHint: string }) {
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [metrics, setMetrics] = useState<WorkflowMetrics | null>(null);
  useEffect(() => {
    if (!taskId) { setSteps([]); setMetrics(null); return; }
    const id = encodeURIComponent(taskId);
    Promise.all([api.get<{ steps: WorkflowStep[] }>(`/api/tasks/${id}/plan`), api.get<WorkflowMetrics>(`/api/tasks/${id}/metrics`)] )
      .then(([plan, timing]) => { setSteps(plan.steps); setMetrics(timing); }).catch(() => { setSteps([]); setMetrics(null); });
  }, [taskId, statusHint]);
  if (!steps.length) return null;
  return <div className="shrink-0 border-b border-edge bg-canvas px-5 py-2.5">
    {metrics && <div className="mb-2 text-[10.5px] text-ink-3">总耗时 {metrics.total_seconds.toFixed(1)}s · 关键路径 {metrics.critical_path_seconds.toFixed(1)}s · {metrics.event_count} 个事件</div>}
    <div className="flex gap-2 overflow-x-auto">
    {steps.map((step) => <div key={step.id} className="min-w-28 rounded-lg border border-edge bg-surface px-2.5 py-1.5">
      <div className={`text-[10.5px] font-medium ${step.status === "done" ? "text-ok" : step.status === "running" ? "text-accent" : step.status === "failed" ? "text-danger" : "text-ink-3"}`}>{step.status === "running" ? "执行中" : step.status === "done" ? "已完成" : step.status === "failed" ? "失败" : "等待"}</div>
      <div className="mt-0.5 whitespace-nowrap text-[11.5px] font-medium">{step.title}</div>
      {step.depends_on.length > 0 && <div className="mt-0.5 text-[10px] text-ink-3">依赖：{step.depends_on.join("、")}</div>}
    </div>)}
    </div>
  </div>;
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
  // R13-H：截断生效后 length 恒为 ACTIVITY_CAP，依赖 length 不再触发滚动——
  // 改挂末条 entry 的引用（每条新日志都是新对象）
  const lastEntry = activity[activity.length - 1];
  useEffect(() => {
    const el = ref.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lastEntry]);

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
  selected,
  onSelect,
  onResume,
  resumeBlocked,
}: {
  run: RunSummary;
  selected: boolean;
  onSelect: (name: string) => void;
  onResume: (name: string) => void;
  /** R13-F：非 null 时续跑禁用，值为禁用原因（title 提示） */
  resumeBlocked?: string | null;
}) {
  const resumable = run.status !== "running" && run.status !== "legacy";
  const title =
    run.paper?.title || sessionTitle(run.query || null, run.query || "");
  return (
    <div
      onClick={() => onSelect(run.name)}
      className={`cursor-pointer rounded-xl border bg-surface px-3.5 py-2.5 transition-colors ${
        selected
          ? "border-accent/50 bg-accent-tint/40"
          : "border-edge hover:border-accent/30"
      }`}
      aria-pressed={selected}
    >
      <div className="flex items-center gap-2">
        <span className={`min-w-0 flex-1 truncate text-[12.5px] font-medium ${selected ? "text-accent-hover dark:text-accent" : ""}`}>{title}</span>
        <span className={`shrink-0 rounded-md px-1.5 py-0.5 text-[10.5px] font-medium ${RUN_BADGE[run.status] || RUN_BADGE.legacy}`}>
          {RUN_STATUS_LABEL[run.status] || run.status}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-3">
        <span>{formatRelative(run.updated_at)}</span>
        {resumable && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onResume(run.name);
            }}
            disabled={!!resumeBlocked}
            title={resumeBlocked || "从断点续跑"}
            className="ml-auto rounded-md border border-edge px-2 py-0.5 text-[11px] transition-colors hover:border-accent/50 hover:text-accent disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:border-edge disabled:hover:text-inherit"
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
    conn,
    task,
    runs,
    runsLoading,
    start,
    resume,
    respondApproval,
    steer,
    stop,
    refreshRuns,
    durableTasks,
    refreshDurableTasks,
    workflows,
    workflowsLoading,
    refreshWorkflows,
    observe,
    restart,
  } = useTaskStore();

  const [query, setQuery] = useState("");
  const [multiAgent, setMultiAgent] = useState(true);
  const [workflowId, setWorkflowId] = useState("paper");
  const [maxCost, setMaxCost] = useState("");
  const [steerText, setSteerText] = useState("");
  const [notice, setNotice] = useState("");
  const running = task.phase === "running";

  // 停止任务（R15）：取消类操作先确认，结果走全局 toast
  const [confirmStop, setConfirmStop] = useState(false);
  const [stopBusy, setStopBusy] = useState(false);
  async function performStop() {
    setStopBusy(true);
    try {
      await stop();
      toast.success("已发送停止指令，任务将在安全点退出");
      setNotice("");
    } catch (e) {
      toast.error(`停止失败：${(e as Error).message}`);
    } finally {
      setStopBusy(false);
      setConfirmStop(false);
    }
  }

  // ---- 运行选中 + 产出 dock（R12 P3/C6）：行点击=选中，dock 展示该次运行目录 --
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  useEffect(() => {
    // 默认选最近一次；选中项从历史中消失（清空/刷新）时回退
    setSelectedRun((cur) =>
      cur && runs.some((r) => r.name === cur) ? cur : (runs[0]?.name ?? null),
    );
  }, [runs]);

  const [dockCollapsed, setDockCollapsed] = useState<boolean>(loadDockCollapsed);
  const toggleDock = useCallback(() => {
    setDockCollapsed((prev) => {
      const next = !prev;
      saveDockCollapsed(next);
      return next;
    });
  }, []);

  // 回合结束（离开 running）→ 刷新信号 + 拉取历史（新运行入列、状态徽标更新）
  const [dockRefreshKey, setDockRefreshKey] = useState(0);
  const prevPhaseRef = useRef(task.phase);
  useEffect(() => {
    if (prevPhaseRef.current === "running" && task.phase !== "running") {
      setDockRefreshKey((k) => k + 1);
      refreshRuns().catch(() => {});
    }
    prevPhaseRef.current = task.phase;
  }, [task.phase, refreshRuns]);

  const dockRoot = selectedRun ? `writing_outputs/${selectedRun}` : null;

  useEffect(() => {
    document.title = "研究助手 · 任务";
    refreshRuns().catch(() => {});
    refreshDurableTasks().catch(() => {});
    refreshWorkflows().catch(() => {});
  }, [refreshRuns, refreshDurableTasks, refreshWorkflows]);

  useEffect(() => {
    if (workflows.length > 0 && !workflows.some((item) => item.id === workflowId)) {
      setWorkflowId(workflows[0].id);
    }
  }, [workflows, workflowId]);

  // 后台任务：有 running 任务且当前未连接时，给出「继续观察」入口。
  const bgRunning = durableTasks.filter((t) => t.status === "queued" || t.status === "running");
  const recoverable = durableTasks.filter((t) => ["interrupted", "failed", "cancelled"].includes(t.status));
  // R13-F：单槽互斥——观察/运行占用 task 通道期间，其余行的
  // 观察/续跑/重跑必须真正 disabled（此前只有样式弱化，点击仍会掐断连接）。
  const gateCtx: TaskGateCtx = {
    boundTaskId: task.taskId,
    localRunning: running,
    channelBusy: conn === "connecting" || conn === "open",
  };

  function observeTask(taskId: string) {
    void observe(taskId).then((res) => {
      if (res === "offline") setNotice("无法建立与服务端的连接");
      else setNotice("");
    });
  }

  async function launch() {
    const r = await start({
      query,
      multiAgent,
      workflowId,
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
          {multiAgent && workflows.length > 0 && (
            <label className="mt-2 block text-[12px] text-ink-2">
              <span className="mb-1 block text-ink-3">工作流</span>
              <select
                value={workflowId}
                onChange={(e) => setWorkflowId(e.target.value)}
                disabled={running || workflowsLoading}
                className="w-full rounded-lg border border-edge bg-canvas px-2.5 py-1.5 text-[12px] outline-none focus:border-accent/60 disabled:opacity-60"
              >
                {workflows.map((workflow) => (
                  <option key={workflow.id} value={workflow.id}>{workflow.title}</option>
                ))}
              </select>
            </label>
          )}
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
          <h2 className="mb-2 px-1 text-[13px] font-semibold">后台任务</h2>
          <div className="mb-3 space-y-2">
            {bgRunning.length === 0 && (
              <div className="px-1 text-[12px] text-ink-3">无运行中的后台任务</div>
            )}
            {bgRunning.slice(0, 5).map((t) => {
              const reason = gateReason(gateCtx, t.id);
              return (
                <div key={t.id} className="rounded-xl border border-warn/40 bg-surface px-3 py-2.5">
                  <div className="truncate text-[12.5px] font-medium">{t.query}</div>
                  <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-3">
                    <span className="rounded-md bg-warn/10 px-1.5 py-0.5 font-medium text-warn">后台运行中</span>
                    <span>{formatRelative(t.updated_at)}</span>
                    <button
                      type="button"
                      onClick={() => observeTask(t.id)}
                      disabled={!!reason}
                      title={reason ?? "重新连接并回放错过的进度"}
                      className={`ml-auto rounded-md border px-2 py-0.5 text-[11px] transition-colors ${
                        reason
                          ? "cursor-not-allowed border-edge text-ink-3 opacity-60"
                          : "border-edge hover:border-accent/50 hover:text-accent"
                      }`}
                    >
                      继续观察
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
          {recoverable.length > 0 && (
            <>
              <h2 className="mb-2 px-1 text-[13px] font-semibold">可恢复任务</h2>
              <div className="mb-3 space-y-2">
                {recoverable.slice(0, 5).map((t) => {
                  const reason = gateReason(gateCtx, t.id);
                  return (
                    <div key={t.id} className="rounded-xl border border-edge bg-surface px-3 py-2.5">
                      <div className="truncate text-[12.5px] font-medium">{t.query}</div>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-3">
                        <span className="rounded-md bg-surface-2 px-1.5 py-0.5">{t.status === "interrupted" ? "进程中断" : t.status === "failed" ? "执行失败" : "已取消"}</span>
                        <span>{formatRelative(t.updated_at)}</span>
                        <button
                          type="button"
                          onClick={() => { void restart(t).then((res) => { if (res === "offline") setNotice("无法建立与服务端的连接"); }); }}
                          disabled={!!reason}
                          title={reason || undefined}
                          className={`ml-auto rounded-md border border-edge px-2 py-0.5 text-[11px] transition-colors ${
                            reason
                              ? "cursor-not-allowed opacity-60"
                              : "hover:border-accent/50 hover:text-accent"
                          }`}
                        >
                          重新运行
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
          <h2 className="mb-2 px-1 text-[13px] font-semibold">运行历史</h2>
          <div className="space-y-2">
            {runsLoading && runs.length === 0 && (
              // 行内骨架（R15）：历史拉取期不再白等文字，占位形似 RunItem 卡
              <div aria-hidden className="space-y-2">
                {[0, 1, 2].map((i) => (
                  <div
                    key={i}
                    className="h-[58px] animate-pulse rounded-xl border border-edge/60 bg-surface"
                    style={{ animationDelay: `${i * 120}ms`, opacity: 1 - i * 0.25 }}
                  />
                ))}
              </div>
            )}
            {!runsLoading && runs.length === 0 && (
              <div className="px-1 text-[12px] text-ink-3">暂无运行记录</div>
            )}
            {runs.slice(0, 20).map((r) => (
              <RunItem
                key={r.name}
                run={r}
                selected={r.name === selectedRun}
                onSelect={setSelectedRun}
                resumeBlocked={gateReason(gateCtx)}
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
                onClick={() => setConfirmStop(true)}
                className="rounded-lg border border-edge bg-surface px-2.5 py-1 text-[12px] font-medium text-danger transition-colors hover:bg-surface-2"
              >
                停止
              </button>
            )}
          </div>
        </div>

        <WorkflowPlan taskId={task.taskId} statusHint={`${task.lastStage}-${task.phase}`} />
        <AgentPanel taskId={task.taskId} statusHint={`${task.lastStage}-${task.phase}`} />

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

      {/* 右侧产出 dock（R12 P3/C6）：展示选中运行的 writing_outputs/<name> 目录 */}
      <div className="hidden shrink-0 border-l border-edge bg-canvas md:block">
        {dockCollapsed ? (
          <button
            type="button"
            onClick={toggleDock}
            title="展开产出文件"
            aria-label="展开产出文件面板"
            className="flex h-full w-8 flex-col items-center gap-2 pt-3 text-ink-3 transition-colors hover:text-accent"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
              strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
              <path d="m9 18 6-6-6-6" />
            </svg>
            <span
              className="text-[11px] font-medium"
              style={{ writingMode: "vertical-rl" }}
            >
              产出文件
            </span>
          </button>
        ) : (
          <div className="flex h-full w-72 flex-col">
            <ArtifactsPanel
              rootRelPath={dockRoot}
              refreshKey={dockRefreshKey}
              emptyRootHint={
                <>
                  暂无选中的运行。
                  <br />
                  从左侧选择一次运行，或启动新任务。
                </>
              }
              onCollapse={toggleDock}
            />
          </div>
        )}
      </div>

      {/* 停止确认（R15）：中断运行不可恢复，二次确认防手滑 */}
      <ConfirmDialog
        open={confirmStop}
        title="停止当前任务？"
        description="任务会在下一个安全点中断，已完成的阶段性产物保留；之后可从「可恢复任务」重新运行。"
        confirmLabel="停止任务"
        danger
        busy={stopBusy}
        onCancel={() => setConfirmStop(false)}
        onConfirm={() => void performStop()}
      />
    </div>
  );
}
