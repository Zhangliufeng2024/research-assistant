/* 任务视图状态（zustand）：/ws/generate 生命周期 + reduceTask 接线。
 *
 * 协议要点（web/ws.py）：
 * - 连接后首帧必须是 {action:"start", query, multi_agent?, max_cost_usd?,
 *   max_wall_seconds?, resume_run?}；
 * - WS 泵只路由审批与 steer；停止走 REST /api/tasks/{id}/stop；
 * - 断连即取消：socket 为模块级单例，路由切换不断开。
 */
import { create } from "zustand";
import { api } from "@/lib/api";
import { emptyTask, reduceTask } from "@/lib/protocolTask";
import type { ConnStatus, ServerFrame, TaskState } from "@/lib/types";
import { wsClose, wsConnect, wsSend } from "@/lib/ws";

export interface StartOptions {
  query: string;
  multiAgent?: boolean;
  maxCostUsd?: number | null;
  maxWallSeconds?: number | null;
}

export interface PaperSummary {
  name: string;
  topic: string;
  date: string;
  status: string;
  title: string | null;
  word_count: number | null;
  figures_count: number;
  citations_count: number;
}

export interface RunSummary {
  name: string;
  query: string;
  mode: string | null;
  status: string;
  stage: string | null;
  created_at: number | string;
  updated_at: number | string;
  paper: PaperSummary | null;
}

function connectSocket(): Promise<void> {
  return new Promise((resolve, reject) => {
    wsConnect({
      channel: "task",
      onMessage: (msg: ServerFrame) => {
        useTaskStore.setState((s) => ({ task: reduceTask(s.task, msg) }));
      },
      onStatus: (st: ConnStatus) => {
        useTaskStore.setState({ conn: st });
        if (st === "open") resolve();
        else if (st === "error") reject(new Error("task-ws-error"));
      },
    });
  });
}

async function launch(payload: Record<string, unknown>): Promise<"ok" | "offline"> {
  try {
    await connectSocket();
  } catch {
    useTaskStore.setState({ conn: "error" });
    return "offline";
  }
  // 连接已 open；发送 start 帧
  if (!wsSend({ action: "start", ...payload }, "task")) return "offline";
  return "ok";
}

interface TaskStore {
  conn: ConnStatus;
  task: TaskState;
  runs: RunSummary[];
  runsLoading: boolean;

  start(opts: StartOptions): Promise<"ok" | "empty" | "offline">;
  resume(name: string): Promise<"ok" | "offline">;
  respondApproval(ok: boolean): void;
  steer(text: string): void;
  /** 停止当前运行（REST，服务端协作取消）。 */
  stop(): Promise<void>;
  refreshRuns(): Promise<void>;
  reset(): void;
}

export const useTaskStore = create<TaskStore>()((set, get) => ({
  conn: "idle",
  task: emptyTask(),
  runs: [],
  runsLoading: false,

  start: async (opts) => {
    const q = opts.query.trim();
    if (!q) return "empty";
    set({
      task: { ...emptyTask(), query: q, mode: opts.multiAgent === false ? "single" : "pipeline" },
    });
    return launch({
      query: q,
      multi_agent: opts.multiAgent !== false,
      max_cost_usd: opts.maxCostUsd || null,
      max_wall_seconds: opts.maxWallSeconds || null,
    });
  },

  resume: async (name) => {
    set({ task: { ...emptyTask(), mode: `resume:${name}`, resumeRun: name } });
    return launch({ resume_run: name });
  },

  respondApproval: (ok) => {
    wsSend({ action: "approval", approved: ok }, "task");
    set((s) => ({ task: { ...s.task, approval: null } }));
  },

  steer: (text) => {
    const v = text.trim();
    if (!v) return;
    wsSend({ action: "steer", message: v.slice(0, 2000) }, "task");
  },

  stop: async () => {
    const taskId = get().task.taskId;
    if (!taskId) return;
    try {
      await api.post(`/api/tasks/${encodeURIComponent(taskId)}/stop`);
    } catch {
      /* 已结束等场景忽略 */
    }
  },

  refreshRuns: async () => {
    set({ runsLoading: true });
    try {
      const runs = await api.get<RunSummary[]>("/api/runs");
      set({ runs });
    } finally {
      set({ runsLoading: false });
    }
  },

  reset: () => {
    wsClose("task");
    set({ conn: "idle", task: emptyTask() });
  },
}));
