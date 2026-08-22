/* 会话 WS 消息 → 会话态的纯函数归约（R2 会话模式）。
 *
 * 与 docs/plans/2026-08-22-desktop-workspace.md §3-C2 协议对齐；
 * 本文件不碰 DOM，供 node:test 覆盖。
 *
 * 流模型：items 是有序聊天流（用户气泡 / 助手文本气泡 / 工具卡占位），
 * 卡片实体存于 cards 映射、按 ref 引用——工具卡的多次推送合并在同一位置。
 */

export const APPROVAL_TIMEOUT_S = 120;

export function emptyChat() {
  return {
    sessionId: null,
    items: [],      // {kind:"user",text,t,steer?} | {kind:"text",text,t} | {kind:"tool",ref,t}
    cards: {},      // ref → {id,tool,args,status,preview,files,t}
    approval: null, // {id,tool,summary,deadline}
    budget: null,
    phase: "idle",  // idle|running|done|error
    error: null,
    stopReason: null,
    turns: 0,
    startedAt: null,
    finishedAt: null,
  };
}

function clone(c) {
  return { ...c, items: [...c.items], cards: { ...c.cards } };
}

/* ---- 本地动作（不经服务端回显，由视图在发送时调用） ---- */

/* 用户发言；agent 运行中发送视为 steer（服务端并入下一步），
 * 不重启回合计时，也不清除已有错误之外的状态 */
export function applyUserMessage(prev, text) {
  if (!text) return prev;
  const c = clone(prev);
  c.items.push({ kind: "user", text, t: Date.now(), steer: prev.phase === "running" });
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

export function applyApprovalResponse(prev) {
  if (!prev.approval) return prev;
  const c = clone(prev);
  c.approval = null;
  return c;
}

/* ---- 服务端消息归约 ---- */

/* 文本增量：接续最后一个 text 气泡；被工具卡/用户消息打断后另起新气泡 */
function appendDelta(items, delta) {
  const last = items[items.length - 1];
  if (last && last.kind === "text") {
    return [...items.slice(0, -1), { kind: "text", text: last.text + delta, t: last.t }];
  }
  return [...items, { kind: "text", text: delta, t: Date.now() }];
}

function mergeFiles(oldFiles, incoming) {
  if (!Array.isArray(incoming)) return oldFiles;
  const seen = new Set(oldFiles.map((f) => f.path));
  return oldFiles.concat(incoming.filter((f) => f && f.path && !seen.has(f.path)));
}

/* 归约单条服务端消息；无可观测变化时返回原引用（订阅方按引用跳过重绘） */
export function reduceChat(prev, msg) {
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
        c.cards[msg.id] = {
          id: msg.id,
          tool: msg.tool || "",
          args: msg.arguments || {},
          status: msg.status || "running",
          preview: msg.result_preview || "",
          files: mergeFiles([], msg.files),
          t: Date.now(),
        };
        c.items.push({ kind: "tool", ref: msg.id, t: Date.now() });
      } else {
        c.cards[msg.id] = {
          ...old,
          status: msg.status || old.status,
          preview: msg.result_preview !== undefined ? msg.result_preview : old.preview,
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

export function chatBadgeClass(phase) {
  return { running: "b-run", done: "b-ok", error: "b-err" }[phase] || "";
}

export const CHAT_PHASE_LABEL = { idle: "待命", running: "思考中", done: "已完成", error: "出错" };
