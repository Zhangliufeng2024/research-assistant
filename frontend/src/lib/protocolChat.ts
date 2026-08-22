/* 会话 WS 消息 → 会话态的纯函数归约（旧前端 protocol_chat.js 的忠实移植）。
 *
 * 与 docs/protocol.md「§ 会话协议 (/ws/chat)」及后端 web/chat.py 对齐；
 * 纯函数不碰 DOM，供 vitest 覆盖。
 *
 * 流模型：items 是有序聊天流（用户气泡 / 助手文本气泡 / 工具卡占位），
 * 卡片实体存于 cards 映射、按 ref 引用——工具卡的多次推送合并在同一位置。
 */
import type {
  ChatItem,
  ChatPhase,
  ChatState,
  FileRef,
  HistoryMessage,
  ServerFrame,
  ToolCard,
} from "./types";

export const APPROVAL_TIMEOUT_S = 120;

export function emptyChat(): ChatState {
  return {
    sessionId: null,
    items: [],
    cards: {},
    approval: null,
    budget: null,
    phase: "idle",
    error: null,
    stopReason: null,
    turns: 0,
    startedAt: null,
    finishedAt: null,
  };
}

function clone(c: ChatState): ChatState {
  return { ...c, items: [...c.items], cards: { ...c.cards } };
}

/* ---- 本地动作（不经服务端回显，由视图在发送时调用） ---- */

/** 用户发言；agent 运行中发送视为 steer（服务端并入下一步），
 * 不重启回合计时，也不清除已有错误之外的状态。 */
export function applyUserMessage(prev: ChatState, text: string): ChatState {
  if (!text) return prev;
  const c = clone(prev);
  c.items.push({
    kind: "user",
    text,
    t: Date.now(),
    steer: prev.phase === "running",
  });
  if (prev.phase !== "running") {
    c.phase = "running";
    c.error = null;
    c.stopReason = null;
    c.turns = 0;
    c.startedAt = Date.now();
    c.finishedAt = null;
  }
  return c;
}

export function applyApprovalResponse(prev: ChatState): ChatState {
  if (!prev.approval) return prev;
  const c = clone(prev);
  c.approval = null;
  return c;
}

/** 发送失败兜底（R9）：乐观置位的 running 必须有人复位。
 * applyUserMessage 在连接建立前就把 phase 置为 running——若随后 WS 连不上，
 * 旧逻辑只弹 toast，状态永远停在「思考中」（用户看到的褐色原点死转）。
 * 这里把 running 显式落到 error，让红点与错误横幅如实呈现。 */
export function applySendFailure(prev: ChatState, message: string): ChatState {
  if (prev.phase !== "running") return prev;
  const c = clone(prev);
  c.phase = "error";
  c.error = message;
  c.finishedAt = Date.now();
  return c;
}

/* ---- 服务端消息归约 ---- */

/** 文本增量：接续最后一个 text 气泡；被工具卡/用户消息打断后另起新气泡。 */
function appendDelta(items: ChatItem[], delta: string): ChatItem[] {
  const last = items[items.length - 1];
  if (last && last.kind === "text") {
    return [...items.slice(0, -1), { kind: "text", text: last.text + delta, t: last.t }];
  }
  return [...items, { kind: "text", text: delta, t: Date.now() }];
}

function mergeFiles(oldFiles: FileRef[], incoming: unknown): FileRef[] {
  if (!Array.isArray(incoming)) return oldFiles;
  const seen = new Set(oldFiles.map((f) => f.path));
  return oldFiles.concat(
    incoming.filter(
      (f): f is FileRef =>
        !!f &&
        typeof f === "object" &&
        typeof (f as FileRef).path === "string" &&
        !seen.has((f as FileRef).path),
    ),
  );
}

/** 归约单条服务端消息；无可观测变化时返回原引用（订阅方按引用跳过重绘）。 */
export function reduceChat(prev: ChatState, msg: ServerFrame): ChatState {
  switch (msg.type) {
    case "connected": {
      if (!msg.session_id || msg.session_id === prev.sessionId) return prev;
      const c = clone(prev);
      c.sessionId = msg.session_id;
      return c;
    }

    case "text": {
      if (!msg.delta) return prev;
      const c = clone(prev);
      c.items = appendDelta(c.items, msg.delta);
      return c;
    }

    case "tool_card": {
      if (!msg.id) return prev;
      const c = clone(prev);
      const old = c.cards[msg.id];
      if (!old) {
        const card: ToolCard = {
          id: msg.id,
          tool: msg.tool || "",
          args: msg.arguments || {},
          status: msg.status || "running",
          preview: msg.result_preview || "",
          files: mergeFiles([], msg.files),
          t: Date.now(),
        };
        c.cards[msg.id] = card;
        c.items.push({ kind: "tool", ref: msg.id, t: Date.now() });
      } else {
        c.cards[msg.id] = {
          ...old,
          status: msg.status || old.status,
          preview:
            msg.result_preview !== undefined ? msg.result_preview : old.preview,
          files: mergeFiles(old.files, msg.files),
        };
      }
      return c;
    }

    case "usage": {
      if (!msg.budget) return prev;
      const c = clone(prev);
      c.budget = msg.budget;
      return c;
    }

    case "approval_request": {
      const c = clone(prev);
      c.approval = {
        id: msg.id,
        tool: msg.tool || "",
        summary: msg.summary || "",
        deadline: Date.now() + APPROVAL_TIMEOUT_S * 1000,
      };
      return c;
    }

    case "result": {
      const c = clone(prev);
      c.phase = "done";
      c.finishedAt = Date.now();
      c.stopReason = msg.stop_reason || c.stopReason;
      if (typeof msg.turns === "number") c.turns = msg.turns;
      c.approval = null;
      return c;
    }

    case "error": {
      const c = clone(prev);
      c.phase = "error";
      c.error = msg.message || "未知错误";
      c.finishedAt = Date.now();
      c.approval = null;
      return c;
    }

    case "done":
      if (prev.phase === "running") {
        const c = clone(prev);
        c.phase = "done";
        c.finishedAt = c.finishedAt || Date.now();
        return c;
      }
      return prev;

    default:
      return prev;
  }
}

/** history.json 归约历史 → 聊天流条目（会话恢复用；t=0 表示无时间信息）。 */
export function historyToItems(messages: HistoryMessage[]): ChatItem[] {
  return messages.map((m) =>
    m.role === "user"
      ? { kind: "user" as const, text: m.content, t: 0 }
      : { kind: "text" as const, text: m.content, t: 0 },
  );
}

export const CHAT_PHASE_LABEL: Record<ChatPhase, string> = {
  idle: "待命",
  running: "思考中",
  done: "已完成",
  error: "出错",
};
