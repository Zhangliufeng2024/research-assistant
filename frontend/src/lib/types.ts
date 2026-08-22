/* 共享类型定义。协议语义见 docs/protocol.md 与后端 web/chat.py、web/ws.py；
 * 归约器（protocolChat/protocolTask）是旧前端同名模块的忠实移植。 */

export type ConnStatus = "idle" | "connecting" | "open" | "error" | "closed";

export type WsChannel = "task" | "chat";

/** 服务端 WS 帧：字段按帧型动态，保持宽松（与后端 json 帧一一对应）。 */
export type ServerFrame = Record<string, any>;

export interface FileRef {
  path: string;
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
  | { kind: "user"; text: string; t: number; steer?: boolean }
  | { kind: "text"; text: string; t: number }
  | { kind: "tool"; ref: string; t: number };

export type ChatPhase = "idle" | "running" | "done" | "error";

export interface ApprovalInfo {
  id: string;
  tool: string;
  summary: string;
  /** 绝对截止时间（ms）；倒计时由视图渲染 */
  deadline: number;
}

/** BudgetGuard.snapshot() 帧（含 cost_cap_enforceable 标记）。 */
export type BudgetSnapshot = Record<string, any>;

export interface ChatState {
  sessionId: string | null;
  /** 有序聊天流：用户气泡 / 助手文本气泡 / 工具卡占位（卡片实体在 cards） */
  items: ChatItem[];
  cards: Record<string, ToolCard>;
  approval: ApprovalInfo | null;
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
}

export interface SessionSummary {
  id: string;
  title: string | null;
  last_message: string;
  turns: number;
  created_at: number | string;
  updated_at: number | string;
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
