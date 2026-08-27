/* 任务视图状态（zustand）：/ws/generate 生命周期 + reduceTask 接线。
 *
 * 协议要点（web/ws.py）：
 * - 连接后首帧必须是 {action:"start", query, multi_agent?, max_cost_usd?,
 *   max_wall_seconds?, resume_run?}；
 * - WS 泵只路由审批与 steer；停止走 REST /api/tasks/{id}/stop；
 * - 后台任务：断连只断开观察，不取消任务；重连用 observe + 事件回放。
 */
import { create } from "zustand";
import { api } from "@/lib/api";
import { emptyTask, reduceTask } from "@/lib/protocolTask";
import type { ConnStatus, ServerFrame, TaskState } from "@/lib/types";
import { wsClose, wsConnect, wsSend } from "@/lib/ws";

export interface StartOptions {
  query: string;
  multiAgent?: boolean;
  workflowId?: string;
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

export interface DurableTask {
  id: string;
  query: string;
  mode: string;
  status: string;
  created_at: number | string;
  updated_at: number | string;
}

export interface WorkflowSummary {
  id: string;
  title: string;
  description: string;
  specialized_executor?: string | null;
  steps: Array<{ id: string; title: string; role: string; role_title: string; depends_on: string[] }>;
}

const ACTIVE_TASK_KEY = "ra.activeTaskId";
const ACTIVE_SEQ_KEY = "ra.activeTaskSeq";

/** 最近一次通道动作（R13-E②）：区分 start/resume 与 observe。
 * connected 握手帧带 task_id 却不带 seq——observe 路径若命中
 * 「零值覆盖」分支，会把刚存好的续跑水位抹成 0，刷新后从头发全量回放。
 * 只有真正的新启动/续跑才允许把持久化 seq 清零。 */
let lastAction: "start" | "resume" | "observe" | null = null;

function loadActive(): { taskId: string | null; lastSeq: number } {
  try {
    return {
      taskId: localStorage.getItem(ACTIVE_TASK_KEY),
      lastSeq: Number(localStorage.getItem(ACTIVE_SEQ_KEY) || 0) || 0,
    };
  } catch {
    return { taskId: null, lastSeq: 0 };
  }
}

function saveActive(taskId: string | null, lastSeq: number): void {
  try {
    if (taskId) {
      localStorage.setItem(ACTIVE_TASK_KEY, taskId);
      localStorage.setItem(ACTIVE_SEQ_KEY, String(lastSeq));
    } else {
      localStorage.removeItem(ACTIVE_TASK_KEY);
      localStorage.removeItem(ACTIVE_SEQ_KEY);
    }
  } catch {
    /* 隐私模式等场景忽略 */
  }
}

function connectSocket(): Promise<void> {
  return new Promise((resolve, reject) => {
    wsConnect({
      channel: "task",
      onMessage: (msg: ServerFrame) => {
        const seq = Number(msg.seq || 0);
        if (seq > 0) {
          const cur = useTaskStore.getState();
          if (seq > (cur.lastSeq ?? 0)) {
            useTaskStore.setState({ lastSeq: seq });
            if (cur.task.taskId) saveActive(cur.task.taskId, seq);
          }
        }
        // R13-E②：observe 的握手/回放帧不做零值覆盖（见 lastAction 注释）
        if (!seq && typeof msg.task_id === "string" && lastAction !== "observe") {
          saveActive(msg.task_id, 0);
        }
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

async function launch(
  payload: Record<string, unknown>,
  action: "start" | "resume_task" = "start",
): Promise<"ok" | "offline"> {
  try {
    await connectSocket();
  } catch {
    useTaskStore.setState({ conn: "error" });
    return "offline";
  }
  // 连接已 open；发送启动或精确续跑帧
  lastAction = action === "start" ? "start" : "resume";
  if (!wsSend({ action, ...payload }, "task")) return "offline";
  return "ok";
}

interface TaskStore {
  conn: ConnStatus;
  task: TaskState;
  lastSeq: number;
  runs: RunSummary[];
  runsLoading: boolean;
  durableTasks: DurableTask[];
  durableLoading: boolean;
  workflows: WorkflowSummary[];
  workflowsLoading: boolean;

  start(opts: StartOptions): Promise<"ok" | "empty" | "offline">;
  resume(name: string): Promise<"ok" | "offline">;
  /** 观察一个后台任务（重连/回放事件）。 */
  observe(taskId: string, after?: number): Promise<"ok" | "offline">;
  /** 从持久化任务记录重新发起一次生成（用于进程重启后的恢复）。 */
  restart(task: DurableTask): Promise<"ok" | "offline">;
  respondApproval(ok: boolean): void;
  steer(text: string): void;
  /** 停止当前运行（REST，服务端协作取消）。 */
  stop(): Promise<void>;
  refreshRuns(): Promise<void>;
  refreshDurableTasks(): Promise<void>;
  refreshWorkflows(): Promise<void>;
  reset(): void;
}

export const useTaskStore = create<TaskStore>()((set, get) => ({
  conn: "idle",
  task: emptyTask(),
  lastSeq: 0,
  runs: [],
  runsLoading: false,
  durableTasks: [],
  durableLoading: false,
  workflows: [],
  workflowsLoading: false,

  start: async (opts) => {
    const q = opts.query.trim();
    if (!q) return "empty";
    set({
      task: { ...emptyTask(), query: q, mode: opts.multiAgent === false ? "single" : "pipeline" },
    });
    const r = await launch({
      query: q,
      multi_agent: opts.multiAgent !== false,
      workflow_id: opts.workflowId || (opts.multiAgent === false ? "single" : "paper"),
      max_cost_usd: opts.maxCostUsd || null,
      max_wall_seconds: opts.maxWallSeconds || null,
    });
    // connected 帧异步到达；taskId 在 onMessage 里持久化。
    return r;
  },

  resume: async (name) => {
    set({ task: { ...emptyTask(), mode: `resume:${name}`, resumeRun: name } });
    return launch({ resume_run: name });
  },

  observe: async (taskId, after) => {
    const startSeq = after ?? loadActive().lastSeq ?? 0;
    set({ task: { ...emptyTask(), taskId }, lastSeq: startSeq });
    saveActive(taskId, startSeq);
    // R13-E②：观察路径——onMessage 的零值覆盖分支必须跳过
    lastAction = "observe";
    try {
      await connectSocket();
    } catch {
      useTaskStore.setState({ conn: "error" });
      return "offline";
    }
    if (!wsSend({ action: "observe", task_id: taskId, after: startSeq }, "task"))
      return "offline";
    return "ok";
  },

  restart: async (task) => {
    const q = task.query.trim();
    if (!q) return "offline";
    set({
      task: {
        ...emptyTask(),
        query: q,
        mode: task.mode === "single" ? "single" : "pipeline",
      },
    });
    return launch({ task_id: task.id }, "resume_task");
  },

  respondApproval: (ok) => {
    // R13-E①：无待审时早退——旧实现会发出 id:undefined 的空帧并误清状态
    const approval = get().task.approval;
    if (!approval) return;
    // R13-C：后端 120s 超时已自动 deny 且不发清除帧，过期回执不再发送
    if (Date.now() >= approval.deadline) return;
    // 先发后清（对齐 chatStore）：发送失败保留卡片可重试
    if (!wsSend({ action: "approval", id: approval.id, approved: ok }, "task")) return;
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

  refreshDurableTasks: async () => {
    set({ durableLoading: true });
    try {
      const tasks = await api.get<DurableTask[]>("/api/tasks?limit=50");
      set({ durableTasks: tasks });
    } catch {
      /* 服务端旧版本等情况忽略 */
    } finally {
      set({ durableLoading: false });
    }
  },

  refreshWorkflows: async () => {
    set({ workflowsLoading: true });
    try {
      const workflows = await api.get<WorkflowSummary[]>("/api/workflows");
      set({ workflows });
    } catch {
      /* 服务端旧版本等情况使用内置论文默认值 */
    } finally {
      set({ workflowsLoading: false });
    }
  },

  reset: () => {
    wsClose("task");
    set({ conn: "idle", task: emptyTask(), lastSeq: 0 });
  },
}));
