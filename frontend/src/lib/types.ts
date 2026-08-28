/* 共享类型定义。协议语义见 docs/protocol.md 与后端 web/chat.py、web/ws.py；
 * 归约器（protocolChat/protocolTask）是旧前端同名模块的忠实移植。 */

export type ConnStatus =
  | "idle"
  | "connecting"
  | "open"
  /** 断连后的自动重连进行中（R16：回合在服务端继续跑，非致命） */
  | "reconnecting"
  | "error"
  | "closed";

export type WsChannel = "task" | "chat";

/** 服务端 WS 帧：字段按帧型动态，保持宽松（与后端 json 帧一一对应）。 */
export type ServerFrame = Record<string, any>;

export interface FileRef {
  path: string;
}

/** 用户消息携带的附件引用（R16）：上传后由服务端返回，发送时随 user 帧
 * 透传；历史恢复时来自 history.json 的 attachments 字段。 */
export interface AttachmentRef {
  name: string;
  /** 服务端绝对路径（上传返回）；历史里的条目同样带路径供模型读取 */
  path: string;
  size?: number;
}

export interface ToolCard {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  status: string;
  preview: string;
  files: FileRef[];
  t: number;
}

export type ChatItem =
  | {
      kind: "user";
      text: string;
      t: number;
      steer?: boolean;
      attachments?: AttachmentRef[];
    }
  | { kind: "text"; text: string; t: number; /** 被打断/失败的残缺回答 */ partial?: boolean }
  | { kind: "tool"; ref: string; t: number };

export type ChatPhase = "idle" | "running" | "done" | "error";

export interface ApprovalInfo {
  id: string;
  tool: string;
  summary: string;
  agentId?: string;
  role?: string;
  /** 绝对截止时间（ms）；倒计时由视图渲染 */
  deadline: number;
}

/** Plan 确认门（方案 1）：/plan 回合的待决计划卡。
 * 服务端超时 600s 按 deny 收场，本地到点只置灰按钮。 */
export interface PlanProposal {
  id: string;
  /** planner 产出的计划全文（已在消息流中直播过，卡内再完整呈现） */
  plan: string;
  /** 绝对截止时间（ms） */
  deadline: number;
}

/** BudgetGuard.snapshot() 帧（含 cost_cap_enforceable 标记）。 */
export type BudgetSnapshot = Record<string, any>;

export interface ChatState {
  sessionId: string | null;
  /** 本会话产物目录（相对工作区根的 POSIX 路径）；权威源是 connected 帧
   * （R12 B4），REST 列表仅作恢复期兜底，旧会话为 null。 */
  outputsDir: string | null;
  /** 有序聊天流：用户气泡 / 助手文本气泡 / 工具卡占位（卡片实体在 cards） */
  items: ChatItem[];
  cards: Record<string, ToolCard>;
  approval: ApprovalInfo | null;
  /** Plan 确认门待决计划（/plan 回合中间态，result 帧清除） */
  plan: PlanProposal | null;
  budget: BudgetSnapshot | null;
  phase: ChatPhase;
  error: string | null;
  stopReason: string | null;
  turns: number;
  startedAt: number | null;
  finishedAt: number | null;
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
  attachments?: AttachmentRef[];
  /** cancelled/failed 回合的残缺回答标记（R16 全路径持久化） */
  partial?: boolean;
}

export interface SessionSummary {
  id: string;
  title: string | null;
  last_message: string;
  turns: number;
  created_at: number | string;
  updated_at: number | string;
  /** 会话产物目录（相对 POSIX 路径）；B4 之前的旧会话为 null。 */
  outputs_dir?: string | null;
}

/* ---------- 任务（generate 流水线）状态 ---------- */

export type TimelineStatus = "pending" | "active" | "done";

export type ActivityKind =
  | "log"
  | "ok"
  | "err"
  | "warn"
  | "info"
  | "stage"
  | "text";

export interface ActivityEntry {
  t: number;
  kind: ActivityKind;
  text: string;
  content?: string;
}

export type TaskPhase =
  | "idle"
  | "running"
  | "done"
  | "failed"
  | "error"
  | "cancelled";

export interface TaskState {
  phase: TaskPhase;
  taskId: string | null;
  query: string;
  /** pipeline | single | resume:<name> */
  mode: string | null;
  resumeRun: string | null;
  startedAt: number | null;
  finishedAt: number | null;
  timeline: TimelineStatus[];
  tlNote: Record<string, string>;
  activity: ActivityEntry[];
  budget: BudgetSnapshot | null;
  approval: ApprovalInfo | null;
  result: ServerFrame | null;
  error: string | null;
  lastStage: string;
}

/* ---------- 设置 ---------- */

export interface SettingsData {
  llm_provider: string;
  llm_model: string;
  llm_base_url: string;
  llm_api_key: string; // 掩码回显：first4***last4 或 ***
  cost_cap_enforceable?: boolean;
  [k: string]: unknown;
}

/* ---------- 轻提示（R14-T：全局 toast 体系） ---------- */

export type ToastKind = "info" | "success" | "error";

export interface ToastData {
  id: string;
  kind: ToastKind;
  message: string;
  /** 自动消失毫秒数；info/success 默认 4000、error 默认 8000，可按条覆盖 */
  duration: number;
}

/* ---------- 全局审批信号（R14-A：跨会话/任务通道聚合） ---------- */

/** 审批来源通道（chatStore.chat.approval / taskStore.task.approval 二选一）。 */
export type ApprovalSource = "chat" | "task";

/** 最近一次「新审批到达」的信号（他页 toast 提醒用）。
 * 只在审批首次出现或换新 id 时更新；随后被解决与否不影响保留。 */
export interface ApprovalSignal {
  id: string;
  /** 到达时刻（Date.now()，ms） */
  at: number;
  source: ApprovalSource;
  /** 冗余字段，供提醒文案直接取用，免回查源 store */
  tool: string;
  summary: string;
}

/* ---------- 工作区（R8：界面内切换工作目录） ---------- */

/** GET /api/workspace 名片；POST /api/workspace/root 切换后同构返回。 */
export interface WorkspaceInfo {
  root: string;
  name: string;
  output_folder: string | null;
  has_git: boolean;
}
