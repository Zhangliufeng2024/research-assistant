/* 会话 WS 消息 → 会话态的纯函数归约（旧前端 protocol_chat.js 的忠实移植）。
 *
 * 与 docs/protocol.md「§ 会话协议 (/ws/chat)」及后端 web/chat.py 对齐；
 * 纯函数不碰 DOM，供 vitest 覆盖。
 *
 * 流模型：items 是有序聊天流（用户气泡 / 助手文本气泡 / 工具卡占位），
 * 卡片实体存于 cards 映射、按 ref 引用——工具卡的多次推送合并在同一位置。
 */
import type {
  AttachmentRef,
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
    outputsDir: null,
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
 * 不重启回合计时，也不清除已有错误之外的状态。
 * attachments（R16）：随消息上传的附件引用，乐观上屏到同一气泡。 */
export function applyUserMessage(
  prev: ChatState,
  text: string,
  attachments?: AttachmentRef[],
): ChatState {
  if (!text) return prev;
  const c = clone(prev);
  c.items.push({
    kind: "user",
    text,
    t: Date.now(),
    steer: prev.phase === "running",
    ...(attachments && attachments.length ? { attachments } : {}),
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
      // R12 B4：outputs_dir 是 dock 的权威源（REST 列表在工作区切换后会把
      // dock 错接到另一工作区的同名目录）。旧服务端/空串归 null。
      const dir =
        typeof msg.outputs_dir === "string" && msg.outputs_dir
          ? msg.outputs_dir
          : null;
      if (
        !msg.session_id ||
        (msg.session_id === prev.sessionId && dir === prev.outputsDir)
      ) {
        return prev;
      }
      const c = clone(prev);
      c.sessionId = msg.session_id;
      c.outputsDir = dir;
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
        agentId: msg.agent_id || "",
        role: msg.role || "",
        deadline: Date.now() + APPROVAL_TIMEOUT_S * 1000,
      };
      return c;
    }

    case "result": {
      const c = clone(prev);
      // 后端口径：result 是唯一收尾帧。stop_reason=error 时终态就是出错——
      // 若无条件置 done，工具条会亮绿点「已完成」而红色出错横幅同时挂着，
      // 「终态是谁」前后端互相打架（对抗性审查抓出）。
      const failed = String(msg.stop_reason || "") === "error";
      c.phase = failed ? "error" : "done";
      c.finishedAt = Date.now();
      c.stopReason = msg.stop_reason || c.stopReason;
      if (typeof msg.turns === "number") c.turns = msg.turns;
      // cancelled/error 的流式文本是残缺回答：标记末条文本气泡（与
      // history.json 落盘的 partial 标记同口径），视图据此提示续问。
      const stop = String(msg.stop_reason || "");
      if (stop === "cancelled" || stop === "error") {
        for (let i = c.items.length - 1; i >= 0; i--) {
          const it = c.items[i]!;
          if (it.kind === "text") {
            c.items[i] = { ...it, partial: true };
            break;
          }
          if (it.kind === "user") break; // 本回合没有文本气泡，无需标记
        }
      }
      c.approval = null;
      return c;
    }

    case "replay_begin": {
      // R16 断线重连回放：服务端回合仍在跑时恢复「思考中」——否则重连后
      // 帧继续流入而 phase 还停在 idle，停止按钮/占位符全错位。
      if (msg.status === "running" && prev.phase !== "running") {
        const c = clone(prev);
        c.phase = "running";
        c.startedAt = c.startedAt || Date.now();
        return c;
      }
      return prev;
    }

    case "error": {
      // error 是伴随通知、不是终态帧：失败回合后端紧跟着还会发
      // result{stop_reason:"error"}（唯一收尾帧），请求级拒绝（steer 为空/
      // 超长等）则根本没有 result。这里只记录消息与清理审批，相位留给
      // 真正的收尾帧决定——否则先到的 error 把 phase 打成 error、随后
      // 的 result 又改写成 done，重放同一帧序同样复现。
      const c = clone(prev);
      c.error = msg.message || "未知错误";
      c.approval = null;
      return c;
    }

    // 注：chat 通道不存在 {type:"done"} 帧（server→client 帧型见协议文档
    // §10.3；/ws/task 任务通道的 done 由 protocolTask 自行归约）。旧代码
    // 的死分支已删，避免误导协议读者。

    default:
      return prev;
  }
}

/** history.json 归约历史 → 聊天流条目（会话恢复用；t=0 表示无时间信息）。
 * 附件与 partial 标记随条目透传（R16 全路径持久化的 UI 口径）。 */
export function historyToItems(messages: HistoryMessage[]): ChatItem[] {
  return messages.map((m) =>
    m.role === "user"
      ? {
          kind: "user" as const,
          text: m.content,
          t: 0,
          ...(m.attachments && m.attachments.length
            ? { attachments: m.attachments }
            : {}),
        }
      : {
          kind: "text" as const,
          text: m.content,
          t: 0,
          ...(m.partial ? { partial: true } : {}),
        },
  );
}

export const CHAT_PHASE_LABEL: Record<ChatPhase, string> = {
  idle: "待命",
  running: "思考中",
  done: "已完成",
  error: "出错",
};
