/* 会话视图状态（zustand）：WS 生命周期 + 归约器接线。
 *
 * 语义对齐旧前端 views/chat.js：
 * - 空闲发送 {action:"user"}（≤8000 字），运行中发送 {action:"steer"}（≤2000 字）；
 * - 审批回执先发后清（applyApprovalResponse 仅在发送成功后应用）；
 * - 打开既有会话：先 GET history 恢复聊天流，再带 ?session= 重连；
 * - 连接为模块级单例：路由切换不断开（双通道设计，见 lib/ws.ts）。
 * 改进点（有意为之）：新会话改为「首条消息发出时才建目录+连接」，
 * 避免打开应用即产生空会话目录。
 */
import { create } from "zustand";
import { api } from "@/lib/api";
import {
  applyApprovalResponse,
  applyUserMessage,
  emptyChat,
  historyToItems,
  reduceChat,
} from "@/lib/protocolChat";
import type {
  ChatState,
  ConnStatus,
  HistoryMessage,
  ServerFrame,
  SessionSummary,
} from "@/lib/types";
import { wsClose, wsConnect, wsConnected, wsSend } from "@/lib/ws";

const MAX_USER_LENGTH = 8_000;
const MAX_STEER_LENGTH = 2_000;

/** 当前 socket 附着的会话查询串（模块级，与连接同生命周期）。 */
let activeQuery = "";

interface ChatStore {
  conn: ConnStatus;
  chat: ChatState;
  sessions: SessionSummary[];
  sessionsLoading: boolean;

  /** 空闲/运行中统一入口；返回结果供视图 toast。 */
  send(text: string): Promise<"ok" | "empty" | "offline">;
  respondApproval(ok: boolean): void;
  stop(): void;
  /** 新会话：清空本地流；真正建目录延迟到首条消息。 */
  newSession(): void;
  /** 打开既有会话：恢复历史 + 建连。 */
  openSession(id: string): Promise<void>;
  refreshSessions(): Promise<void>;
  deleteSession(id: string): Promise<void>;
}

function connectSocket(query: string): Promise<void> {
  activeQuery = query;
  return new Promise((resolve, reject) => {
    wsConnect({
      channel: "chat",
      query,
      onMessage: (msg: ServerFrame) => {
        useChatStore.setState((s) => ({ chat: reduceChat(s.chat, msg) }));
      },
      onStatus: (st) => {
        useChatStore.setState({ conn: st });
        if (st === "open") resolve();
        else if (st === "error") reject(new Error("chat-ws-error"));
      },
    });
  });
}

export const useChatStore = create<ChatStore>()((set, get) => ({
  conn: "idle",
  chat: emptyChat(),
  sessions: [],
  sessionsLoading: false,

  send: async (text) => {
    const v = text.trim();
    if (!v) return "empty";
    const running = get().chat.phase === "running";
    // 乐观上屏（与旧版一致：本地先归约，不等服务端回显）
    set((s) => ({ chat: applyUserMessage(s.chat, v) }));

    if (running) {
      if (!wsSend({ action: "steer", message: v.slice(0, MAX_STEER_LENGTH) }, "chat")) {
        return "offline";
      }
      return "ok";
    }

    // 空闲发送：确保有会话目录与活跃连接
    if (!wsConnected("chat")) {
      try {
        let sid = get().chat.sessionId;
        if (!sid) {
          const created = await api.post<{ id: string }>("/api/chat/sessions", {
            title: v.slice(0, 40),
          });
          sid = created.id;
          set((s) => ({ chat: { ...s.chat, sessionId: sid } }));
        }
        await connectSocket(`session=${encodeURIComponent(sid)}`);
      } catch {
        set({ conn: "error" });
        return "offline";
      }
    }
    if (!wsSend({ action: "user", text: v.slice(0, MAX_USER_LENGTH) }, "chat")) {
      return "offline";
    }
    return "ok";
  },

  respondApproval: (ok) => {
    const appr = get().chat.approval;
    if (!appr) return;
    if (!wsSend({ action: "approval", id: appr.id, approved: ok }, "chat")) return;
    set((s) => ({ chat: applyApprovalResponse(s.chat) }));
  },

  stop: () => {
    wsSend({ action: "stop" }, "chat");
  },

  newSession: () => {
    wsClose("chat");
    activeQuery = "";
    set({ conn: "idle", chat: emptyChat() });
  },

  openSession: async (id) => {
    if (get().chat.sessionId === id && wsConnected("chat")) return;
    const hist = await api.get<{ messages: HistoryMessage[] }>(
      `/api/chat/sessions/${encodeURIComponent(id)}`,
    );
    const items = historyToItems(hist.messages || []);
    wsClose("chat");
    set({ conn: "connecting", chat: { ...emptyChat(), sessionId: id, items } });
    try {
      await connectSocket(`session=${encodeURIComponent(id)}`);
    } catch {
      /* conn 已由 onStatus 置 error；横幅呈现 */
    }
  },

  refreshSessions: async () => {
    set({ sessionsLoading: true });
    try {
      const res = await api.get<SessionSummary[] | { sessions: SessionSummary[] }>(
        "/api/chat/sessions",
      );
      const list = Array.isArray(res) ? res : res.sessions || [];
      set({ sessions: list });
    } finally {
      set({ sessionsLoading: false });
    }
  },

  deleteSession: async (id) => {
    await api.del(`/api/chat/sessions/${encodeURIComponent(id)}`);
    if (get().chat.sessionId === id) get().newSession();
    await get().refreshSessions();
  },
}));

/** 当前连接附着的查询串（调试/视图判断用）。 */
export function activeChatQuery() {
  return activeQuery;
}
