/* 服务端 WS 消息 → 前端任务态的纯函数归约。
 *
 * 旧前端 protocol.js 的忠实移植；与 docs/protocol.md「生成协议 (/ws/generate)」
 * 及 web/ws.py 对齐。时间轴阶段与 pipeline 状态机一一映射。
 */
import type {
  ActivityEntry,
  ActivityKind,
  ApprovalInfo,
  ServerFrame,
  TaskState,
  TimelineStatus,
} from "./types";

export const APPROVAL_TIMEOUT_S = 120;
export const ACTIVITY_CAP = 400;

/** 阶段时间轴定义：与 pipeline 状态机对齐。 */
export const TL_STAGES = [
  { key: "plan", label: "规划" },
  { key: "research", label: "研究" },
  { key: "figures", label: "图表" },
  { key: "assemble", label: "组装" },
  { key: "gates", label: "质量门" },
  { key: "revision", label: "修订" },
  { key: "finalize", label: "定稿" },
] as const;

/** progress.stage → 时间轴下标；undefined = 不改变。 */
const PROGRESS_IDX: Record<string, number> = {
  planning: 0,
  research: 1,
  writing: 3,
  compilation: 6,
};

export function emptyTask(): TaskState {
  return {
    phase: "idle",
    taskId: null,
    query: "",
    mode: null,
    resumeRun: null,
    startedAt: null,
    finishedAt: null,
    timeline: TL_STAGES.map(() => "pending"),
    tlNote: {},
    activity: [],
    budget: null,
    approval: null,
    result: null,
    error: null,
    lastStage: "",
  };
}

function addActivity(
  task: TaskState,
  kind: ActivityKind,
  text: string,
  content?: string,
): ActivityEntry[] {
  const entry: ActivityEntry = content !== undefined
    ? { t: Date.now(), kind, text, content }
    : { t: Date.now(), kind, text };
  const activity = task.activity.concat(entry);
  if (activity.length > ACTIVITY_CAP) {
    activity.splice(0, activity.length - ACTIVITY_CAP);
  }
  return activity;
}

/** 推进时间轴到 idx：之前的 done、当前 active（research 阶段并行激活 figures）。 */
function applyTimeline(tl: TimelineStatus[], idx: number): TimelineStatus[] {
  return tl.map((_, i) => {
    if (i < idx) return "done";
    if (i === idx) return "active";
    // 研究与图表并行执行（research_figures 阶段）
    if (idx === 1 && i === 2) return "active";
    return "pending";
  });
}

function completeTimeline(tl: TimelineStatus[]): TimelineStatus[] {
  return tl.map(() => "done");
}

/** 由消息文本推断更细的阶段（质量门/修订轮）；只前进不回退。 */
function refineIdx(current: number, message: string): number {
  if (/质量门|gates/i.test(message)) return Math.max(current, 4);
  if (/修订|revision/i.test(message)) return Math.max(current, 5);
  return current;
}

/** 归约单条消息；返回新 task 对象（不修改入参）。 */
export function reduceTask(prev: TaskState, msg: ServerFrame): TaskState {
  const t: TaskState = {
    ...prev,
    timeline: [...prev.timeline],
    tlNote: { ...prev.tlNote },
  };

  switch (msg.type) {
    case "connected":
      t.phase = "running";
      t.taskId = msg.task_id || t.taskId;
      t.startedAt = t.startedAt || Date.now();
      return t;

    case "progress": {
      // 未收到 connected 的 progress（如重放/异常路径）也应推进状态
      if (t.phase === "idle") t.phase = "running";
      if (msg.stage === "cancelled") {
        t.phase = "cancelled";
        t.finishedAt = Date.now();
        t.activity = addActivity(t, "warn", msg.message || "任务已停止");
        return t;
      }
      const stage: string = msg.stage || "";
      const stageChanged = !!stage && stage !== t.lastStage;
      t.lastStage = stage || t.lastStage;

      if (msg.message) {
        const kind: ActivityKind = /失败|错误|error/i.test(msg.message)
          ? "err"
          : /完成|成功|通过|✓/i.test(msg.message)
            ? "ok"
            : "log";
        t.activity = addActivity(t, kind, msg.message);
      }

      if (stage === "complete") {
        t.timeline = completeTimeline(t.timeline);
        return t;
      }

      let idx = PROGRESS_IDX[stage];
      if (idx === undefined) idx = msg.message ? refineIdx(-1, msg.message) : -1;
      else if (msg.message) idx = refineIdx(idx, msg.message);
      if (idx >= 0 && t.phase === "running") {
        // 只前进：修订(5)之后回到 compilation(6) 正常；但不要从 6 退回 3
        const cur = t.timeline.lastIndexOf("active");
        if (idx >= cur || cur === -1) t.timeline = applyTimeline(t.timeline, idx);
      }
      if (stageChanged && stage) {
        const label =
          { initialization: "初始化", planning: "规划", research: "研究",
            writing: "写作", compilation: "定稿", complete: "完成" }[stage] || stage;
        t.activity = addActivity(t, "stage", `▶ ${label} ${stage.toUpperCase()}`);
      }
      return t;
    }

    case "text":
      if (msg.content && msg.content.trim()) {
        t.activity = addActivity(t, "text", "模型输出", msg.content);
      }
      return t;

    case "usage":
      if (msg.budget) t.budget = msg.budget;
      return t;

    case "approval_request": {
      const approval: ApprovalInfo = {
        id: msg.id,
        tool: msg.tool || "",
        summary: msg.summary || "",
        deadline: Date.now() + APPROVAL_TIMEOUT_S * 1000,
      };
      t.approval = approval;
      t.activity = addActivity(t, "warn", `待审批：${msg.tool || "工具调用"}`);
      return t;
    }

    case "steer_ok":
      t.activity = addActivity(t, "info", "转向指令已注入 agent");
      return t;

    case "result": {
      t.finishedAt = Date.now();
      t.result = msg;
      if (msg.status === "failed") {
        t.phase = "failed";
        const errText = (msg.errors || []).join("\n") || "文档生成失败";
        t.error = errText;
        t.activity = addActivity(t, "err", errText);
      } else {
        t.phase = "done";
        t.timeline = completeTimeline(t.timeline);
        t.activity = addActivity(
          t,
          "ok",
          `生成完成：${(msg.metadata || {}).title || msg.paper_name || ""}`,
        );
      }
      t.approval = null;
      return t;
    }

    case "error": {
      const errText = msg.message || "未知错误";
      t.phase = "error";
      t.error = errText;
      t.finishedAt = Date.now();
      t.approval = null;
      t.activity = addActivity(t, "err", errText);
      return t;
    }

    case "done":
      if (t.phase === "running") t.phase = "done";
      t.finishedAt = t.finishedAt || Date.now();
      return t;

    default:
      return t;
  }
}

export const RUN_STATUS_LABEL: Record<string, string> = {
  running: "运行中",
  complete: "完成",
  failed: "失败",
  cancelled: "已停止",
  legacy: "早期文档",
};
