/* 会话视图状态（zustand）：WS 生命周期 + 归约器接线。
 *
 * 语义对齐 docs/protocol.md「§ 会话协议 (/ws/chat)」（R16 耐久化后）：
 * - 空闲发送 {action:"user"}（≤8000 字），运行中发送 {action:"steer"}（≤2000 字）；
 * - 审批回执先发后清（applyApprovalResponse 仅在发送成功后应用）；
 * - 打开既有会话：先 GET history 恢复聊天流，再带 ?session= 重连；
 * - 连接为模块级单例：路由切换不断开（双通道设计，见 lib/ws.ts）。
 * - 断线自动重连（R16）：断开只减少服务端观察者，回合继续跑——前端按
 *   指数退避重连，成功后发 {"action":"attach","after":<lastSeq>} 从环形
 *   缓冲续播错过的帧。重连期间 phase 不复位（非致命），放弃后给出横幅
 *   与手动「重连」入口。冷打开（REST 恢复历史）不 attach；但「放弃自动
 *   重连后用户直接再问」触发的全新连接必须带 lastSeq 续播——否则上一
 *   回合在离线期产生的尾流帧既不回放也不直播，UI 永久缺尾。
 * 改进点（有意为之）：新会话改为「首条消息发出时才建目录+连接」，
 * 避免打开应用即产生空会话目录。
 */
import { create } from "zustand";
import { api } from "@/lib/api";
import {
  applyApprovalResponse,
  applySendFailure,
  applyUserMessage,
  emptyChat,
  historyToItems,
  reduceChat,
} from "@/lib/protocolChat";
import type {
  AttachmentRef,
  ChatItem,
  ChatState,
  ConnStatus,
  HistoryMessage,
  ServerFrame,
  SessionSummary,
} from "@/lib/types";
import {
  isValidUserIndex,
  resolveRegenerateTarget,
  type MessageOpResult,
} from "@/lib/messageOps";
import { isCommand, parseCommand } from "@/lib/commands";
import { wsClose, wsConnect, wsConnected, wsSend } from "@/lib/ws";

const MAX_USER_LENGTH = 8_000;
const MAX_STEER_LENGTH = 2_000;
/** 单条消息附件上限（与服务端 ATTACHMENTS_MAX 对齐） */
const MAX_ATTACHMENTS = 8;
/** 断线自动重连上限：约 0.8+1.6+3.2+6.4+8+8 ≈ 28s 后放弃转手动 */
const MAX_RECONNECT_ATTEMPTS = 6;

/** 当前 socket 附着的会话查询串（模块级，与连接同生命周期）。 */
let activeQuery = "";

/* ---- R16 重连机制（模块级状态与连接同生命周期） ---- */
/** 期望保持连接：true 时断线走自动重连；主动关闭前先置 false 抑制。 */
let wantConnected = false;
let reconnectAttempts = 0;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
/** 本会话已收到的最大帧 seq（attach 回放的续传游标）。切换会话即清零。 */
let lastSeq = 0;

/** openSession 竞态守卫（R13-D）：快速连点两个会话时，先发起的那次
 * 会在两次 await 之间被后发起的反超——历史返回后若不校验，旧会话的
 * state/wsClose 会把新会话刚建好的连接掐掉、聊天流错挂。递增序号，
 * 每次 await 后仍是最新的才允许落位，否则静默放弃。 */
let openToken = 0;

interface ChatStore {
  conn: ConnStatus;
  chat: ChatState;
  sessions: SessionSummary[];
  sessionsLoading: boolean;
  /** 已上传待随下一条消息发送的附件引用（R16） */
  pendingAttachments: AttachmentRef[];
  /** 附件批量上传进行中（Composer 据此禁发送钮） */
  attaching: boolean;

  /** 空闲/运行中统一入口；返回结果供视图 toast。
   * opts.attachments（真替换重发用）：显式指定随帧附件——传空数组表示
   * 「本条不带附件」，不会回落到输入框暂存的 chips。 */
  send(
    text: string,
    opts?: { attachments?: AttachmentRef[] },
  ): Promise<"ok" | "empty" | "offline">;
  /** 上传并暂存附件（R16）：无会话时懒创建目录（零轮次残骸由服务端清退）。
   * limit=超出单条附件上限；offline=建目/上传失败；empty=空列表。 */
  attachFiles(files: File[]): Promise<"ok" | "empty" | "offline" | "limit">;
  removePendingAttachment(path: string): void;
  /** 重新生成（R16 真替换）：定位目标用户提问在 history.json 的位置，
   * 服务端 truncate 到其之前、本地同步裁剪，再以原文重发——旧回复真正
     从对话流消失，而非追加一轮「平行答案」。草稿态/离线回落保守重发。
     返回值：busy=流式中拒绝、empty=目标定位失败、offline=网络失败。 */
  regenerateMessage(sessionId: string | null, messageId: number): Promise<MessageOpResult>;
  /** 编辑重发（R16 真替换）：同上，但以新文本入史——原提问与新回答一并
   * 替换。messageId 必须指向 user 气泡。 */
  editAndResend(
    sessionId: string | null,
    messageId: number,
    newText: string,
  ): Promise<MessageOpResult>;
  respondApproval(ok: boolean): void;
  /** Plan 门裁决（方案 1）：/plan 计划卡上的批准/拒绝。 */
  respondPlan(ok: boolean): void;
  stop(): void;
  /** 新会话：清空本地流；真正建目录延迟到首条消息。 */
  newSession(): void;
  /** 打开既有会话：恢复历史 + 建连。 */
  openSession(id: string): Promise<void>;
  refreshSessions(): Promise<void>;
  deleteSession(id: string): Promise<void>;
  /** R17：把会话转为后台任务（对话→任务互链）；返回 job_id。 */
  promoteSession(id: string, prompt?: string): Promise<string | null>;
  /** 手动重连（R16）：自动重连放弃后的恢复入口，从 lastSeq 续播。 */
  reconnectNow(): void;
}

/* ---- 流式增量合帧（R14-S）：至多每 ~50ms 批量写入一次 store ────────────
 * 背景：text 增量此前逐帧 setState，长回答期间每个 token 都触发全量订阅者
 * 重渲染（视图层对全文重跑 Markdown+KaTeX+高亮）。这里只对「运行中的纯
 * 文本增量」做缓冲合并；工具卡/审批/result/error/done 等关键帧先冲刷缓冲
 * 再即时归约——既保住了帧序（先到的文本不会被后到的卡片顶乱），又保证
 * 结束时刻同步冲刷、最终文本绝不丢字。
 * 定时器用 setTimeout 而非 rAF：无头测试环境与后台标签页里 rAF 不跑。 */
const COALESCE_MS = 50;

/** 待冲刷的 text 增量（按到达序拼接）。 */
let pendingDeltas: string[] = [];
let flushTimer: ReturnType<typeof setTimeout> | null = null;

/** 立即把缓冲增量合并为一帧 text 写入 store（空缓冲为无操作；幂等可重入）。 */
function flushPendingDeltas(): void {
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (pendingDeltas.length === 0) return;
  const merged = pendingDeltas.join("");
  pendingDeltas = [];
  useChatStore.setState((s) => ({
    chat: reduceChat(s.chat, { type: "text", delta: merged }),
  }));
}

/** 丢弃缓冲（会话切换/新建时防串话）：被弃的回合服务端 history.json 已有
 * 权威记录，重开会话经 GET history 恢复全文，本地无需也不应补写。 */
function discardPendingDeltas(): void {
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  pendingDeltas = [];
}

/* ---- R16 断线处理 ---- */

/** 放弃自动重连：横幅由视图按 conn==="closed" 呈现（含手动重连入口）。 */
function giveUpReconnect(): void {
  useChatStore.setState({ conn: "closed" });
}

function scheduleReconnect(): void {
  if (!wantConnected || reconnectTimer !== null) return;
  if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
    giveUpReconnect();
    return;
  }
  const delay = Math.min(800 * 2 ** reconnectAttempts, 8_000);
  reconnectAttempts += 1;
  useChatStore.setState({ conn: "reconnecting" });
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    if (!wantConnected) return;
    const sid = useChatStore.getState().chat.sessionId;
    if (!sid) {
      giveUpReconnect();
      return;
    }
    connectSocket(`session=${encodeURIComponent(sid)}`, {
      attachAfter: lastSeq,
    }).catch(() => scheduleReconnect());
  }, delay);
}

function cancelReconnect(): void {
  if (reconnectTimer !== null) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  wantConnected = false;
}

function connectSocket(
  query: string,
  opts: { attachAfter?: number } = {},
): Promise<void> {
  activeQuery = query;
  return new Promise((resolve, reject) => {
    // 未 open 即错：交由 send() 的 catch 给出「无法建立连接」文案；
    // 已 open 后的 error/close 才按「断线重连」处理。
    let opened = false;
    wsConnect({
      channel: "chat",
      query,
      onMessage: (msg: ServerFrame) => {
        // 回放/直播帧统一推进 seq 游标（attach 的 after 参数取自这里）
        if (typeof msg.seq === "number" && msg.seq > lastSeq) {
          lastSeq = msg.seq;
        }
        // R14-S 合帧：仅运行中的纯文本增量进缓冲；其余帧是关键节点，
        // 先冲刷保序再即时归约（非文本状态变更不受节流影响）。
        if (
          msg.type === "text" &&
          msg.delta &&
          useChatStore.getState().chat.phase === "running"
        ) {
          pendingDeltas.push(msg.delta);
          if (flushTimer === null) {
            flushTimer = setTimeout(flushPendingDeltas, COALESCE_MS);
          }
          return;
        }
        flushPendingDeltas();
        useChatStore.setState((s) => ({ chat: reduceChat(s.chat, msg) }));
      },
      onStatus: (st) => {
        useChatStore.setState({ conn: st });
        if (st === "open") {
          opened = true;
          wantConnected = true;
          reconnectAttempts = 0;
          // 断线重连路径才 attach：after=最后收到的 seq，服务端只补差额。
          if (opts.attachAfter !== undefined) {
            wsSend({ action: "attach", after: opts.attachAfter }, "chat");
          }
          resolve();
        } else if (st === "error") {
          if (opened) {
            // R14-S 协同：断线前已到达的增量必须先落屏再转重连
            flushPendingDeltas();
            scheduleReconnect();
          }
          reject(new Error("chat-ws-error"));
        } else if (st === "closed") {
          if (opened) {
            flushPendingDeltas();
            scheduleReconnect();
          } else {
            reject(new Error("chat-ws-closed"));
          }
        }
      },
    });
  });
}

/** 补偿删除刚建的会话目录（§6.4）：连接失败/帧未发出时回合不可能开始，
 * 该目录只会成为列表里的零轮次残骸。尽力而为——删除失败交给后端
 * 列表清退（ZERO_TURN_TTL_S）兜底；同时复位本地 sessionId，让重发
 * 重新走一遍干净的建目录流程。 */
function discardJustCreated(sid: string): void {
  void api
    .del(`/api/chat/sessions/${encodeURIComponent(sid)}`)
    .catch(() => {});
  useChatStore.setState((s) => ({
    chat:
      s.chat.sessionId === sid ? { ...s.chat, sessionId: null } : s.chat,
  }));
}

/* ---- R16 真替换：把某条本地用户气泡映射到 history.json 的物理下标 ----
 * 本地 items 与历史不是一一对应：steer 气泡、工具卡、流式文本都不落史；
 * 史里只有 [user, assistant] 交替对（全路径持久化保证每个 user 条目都有
 * assistant 尾随）。因此按「第 k 条真实（非 steer）用户气泡 ↔ 史中第 k 个
 * user 条目」做序号映射，天然免疫空气回复/重复提问造成的错位。
 * 返回：物理下标；null=序号失配或服务端拒绝（历史疑似被外部改动，
 * 宁可不动手）；"error"=网络故障。 */
async function locateUserHistoryIndex(
  sid: string,
  items: ChatItem[],
  idx: number,
): Promise<number | null | "error"> {
  let k = 0; // 目标气泡之前的真实用户气泡数 = 它自己的 0 基序号
  for (let i = 0; i < idx; i++) {
    const it = items[i];
    if (it?.kind === "user" && !it.steer) k += 1;
  }
  try {
    const hist = await api.get<{ messages: HistoryMessage[] }>(
      `/api/chat/sessions/${encodeURIComponent(sid)}`,
    );
    const msgs = hist.messages || [];
    const userIdxs: number[] = [];
    msgs.forEach((m, i) => {
      if (m.role === "user") userIdxs.push(i);
    });
    const histIdx = userIdxs[k];
    return histIdx === undefined ? null : histIdx;
  } catch (err) {
    const msgText = err instanceof Error ? err.message : String(err);
    if (/^HTTP 4/.test(msgText)) return null; // 404 已删等
    return "error";
  }
}

/** 服务端截断到前 keep 条；HTTP 4xx 归 null（运行中冲突/已删等）。 */
async function truncateHistory(
  sid: string,
  keep: number,
): Promise<"ok" | null | "error"> {
  try {
    await api.post(`/api/chat/sessions/${encodeURIComponent(sid)}/truncate`, {
      keep,
    });
    return "ok";
  } catch (err) {
    const msgText = err instanceof Error ? err.message : String(err);
    if (/^HTTP 4/.test(msgText)) return null;
    return "error";
  }
}

export const useChatStore = create<ChatStore>()((set, get) => ({
  conn: "idle",
  chat: emptyChat(),
  sessions: [],
  sessionsLoading: false,
  pendingAttachments: [],
  attaching: false,

  send: async (text, opts) => {
    const v = text.trim();
    if (!v) return "empty";
    const running = get().chat.phase === "running";
    // R14-S：乐观上屏前先冲刷缓冲——否则缓冲中的助手文本会在这条用户气泡
    // 之后才落位（appendDelta 会另起新气泡），时间序错乱
    flushPendingDeltas();
    // 方案 4：slash 命令路由（空闲期）。/plan 是真实请求——走正常 user 帧
    // （服务端落盘并启动 Plan 确认门回合）；其余命令走 command 帧，不占
    // 回合不落史；解析错误（未知命令/非法用法）直接本地渲染，不打网络。
    const parsed = parseCommand(v);
    const commandSend = !running && isCommand(v) && parsed.kind !== "plan";
    if (commandSend && parsed.error) {
      set((s) => ({
        chat: {
          ...s.chat,
          items: [
            ...s.chat.items,
            { kind: "user" as const, text: v, t: Date.now() },
            { kind: "text" as const, text: parsed.error ?? "", t: Date.now() },
          ],
        },
      }));
      return "ok";
    }
    // R16：随消息发送的附件引用（steer 场景不消费，留待下一轮）。
    // 真替换重发显式传原消息的附件（含空数组＝明确不带）；普通发送取
    // 输入框暂存。?? 只对 nullish 生效——空数组不会被暂存 chips 顶替。
    const atts = running || commandSend
      ? []
      : (opts?.attachments ?? get().pendingAttachments);
    // 乐观上屏（与旧版一致：本地先归约，不等服务端回显）
    set((s) => ({ chat: applyUserMessage(s.chat, v, atts) }));
    // 连接失败兜底（R9）：乐观置位的 running 必须复位，否则界面永远「思考中」
    const failOffline = () =>
      set((s) => ({
        chat: applySendFailure(s.chat, "无法建立与服务端的连接——请重启应用；若反复出现请把日志发给开发者"),
      }));

    if (running) {
      if (!wsSend({ action: "steer", message: v.slice(0, MAX_STEER_LENGTH) }, "chat")) {
        // R16 语义重写：断线不终止回合——服务端继续跑到终态并落盘。
        // phase 必须保持 running（真实状态）：打成 error 既与契约矛盾，
        // 又会掩盖「正在自动重连/未能自动恢复」横幅和手动重连入口；
        // 重连成功 attach 回放自会补齐进度。这里只负责把重连机器转起来。
        nudgeReconnectAfterSteerFailure();
        return "offline";
      }
      return "ok";
    }

    // 空闲发送：确保有会话目录与活跃连接
    let createdSid: string | null = null; // 本次调用新建的目录（失败需补偿删除）
    if (!wsConnected("chat")) {
      try {
        let sid = get().chat.sessionId;
        if (!sid) {
          const created = await api.post<{ id: string }>("/api/chat/sessions", {
            title: v.slice(0, 40),
          });
          sid = created.id;
          createdSid = created.id;
          set((s) => ({ chat: { ...s.chat, sessionId: sid } }));
        }
        // 放弃自动重连后用户直接再问：全新连接也要从 lastSeq 续播，补上
        // 上一回合离线期的尾流（否则 UI 永久缺尾，只能重开会话恢复）。
        // lastSeq=0＝无游标（首条消息/新会话），不 attach——REST 历史
        // 已含完整旧轮次，整轮回放反而造成重复条目。
        await connectSocket(
          `session=${encodeURIComponent(sid)}`,
          lastSeq > 0 ? { attachAfter: lastSeq } : {},
        );
      } catch {
        set({ conn: "error" });
        if (createdSid) discardJustCreated(createdSid);
        failOffline();
        return "offline";
      }
    }
    const frame: Record<string, unknown> = commandSend
      ? { action: "command", text: v }
      : { action: "user", text: v.slice(0, MAX_USER_LENGTH) };
    if (!commandSend && atts.length) frame.attachments = atts;
    if (!wsSend(frame, "chat")) {
      if (createdSid) discardJustCreated(createdSid);
      failOffline();
      return "offline";
    }
    // 发送成功才消费暂存 chips；真替换重发的附件是显式传入的，不动暂存
    if (atts.length && opts?.attachments === undefined && !commandSend) {
      set({ pendingAttachments: [] });
    }
    return "ok";
  },

  /* ---- 附件（R16）：上传走 REST，发送随 user 帧。运行中也可上传——
   * 本轮用不上，chips 留着下一条消息引用。 ---- */
  attachFiles: async (files) => {
    if (!files.length) return "empty";
    const room = MAX_ATTACHMENTS - get().pendingAttachments.length;
    if (room <= 0) return "limit";
    const batch = files.slice(0, room);
    set({ attaching: true });
    try {
      let sid = get().chat.sessionId;
      if (!sid) {
        const created = await api.post<{ id: string }>("/api/chat/sessions", {
          title: "附件",
        });
        sid = created.id;
        set((s) => ({ chat: { ...s.chat, sessionId: sid } }));
      }
      const form = new FormData();
      for (const f of batch) form.append("files", f, f.name);
      const res = await api.upload<{ files: AttachmentRef[] }>(
        `/api/chat/sessions/${encodeURIComponent(sid)}/attachments`,
        form,
      );
      set((s) => ({
        pendingAttachments: [...s.pendingAttachments, ...(res.files || [])],
      }));
      return "ok";
    } catch {
      // 失败且目录是本次新建：同样会成为零轮次残骸，交给服务端清退兜底
      return "offline";
    } finally {
      set({ attaching: false });
    }
  },

  removePendingAttachment: (path) => {
    set((s) => ({
      pendingAttachments: s.pendingAttachments.filter((a) => a.path !== path),
    }));
  },

  /* ---- 消息操作（R16 真替换）----
   * 流式中一律拒绝：此刻放行会被 send() 当作 steer 并入当前回合。
   * sessionId 错位保护：动作只对当前活跃会话有意义。 */
  regenerateMessage: async (sessionId, messageId) => {
    const st = get();
    if (st.chat.phase === "running") return "busy";
    if (sessionId && st.chat.sessionId !== sessionId) return "empty";
    const idx = resolveRegenerateTarget(st.chat.items, messageId);
    if (idx === null) return "empty";
    const target = st.chat.items[idx]!;
    if (target.kind !== "user") return "empty"; // resolve 已保证，此处兜底收窄
    const prompt = target.text.trim();
    if (!prompt) return "empty";
    // 原消息的附件必须随重发入史：truncate 会把带附件的旧 user 条目整条
    // 删掉，而 send 默认只带输入框暂存（此流程为空）——不显式携带的话，
    // 「读一下我传的数据」类追问在新回合就无数据可读了。
    const atts = target.attachments ?? [];
    const sid = st.chat.sessionId;
    if (!sid || !wsConnected("chat")) {
      // 草稿态/离线：无可截断也无必要，回落保守重发（同样带原附件）
      return get().send(prompt, { attachments: atts });
    }
    const histIdx = await locateUserHistoryIndex(sid, st.chat.items, idx);
    if (histIdx === null) return "empty";
    if (histIdx === "error") return "offline";
    const cut = await truncateHistory(sid, histIdx);
    if (cut === null) return "empty";
    if (cut === "error") return "offline";
    discardPendingDeltas();
    set((s) => ({
      chat: {
        ...s.chat,
        items: s.chat.items.slice(0, idx),
        phase: "idle",
        error: null,
        stopReason: null,
        finishedAt: null,
      },
    }));
    return get().send(prompt, { attachments: atts });
  },

  editAndResend: async (sessionId, messageId, newText) => {
    const st = get();
    if (st.chat.phase === "running") return "busy";
    if (sessionId && st.chat.sessionId !== sessionId) return "empty";
    if (!isValidUserIndex(st.chat.items, messageId)) return "empty";
    const text = newText.trim();
    if (!text) return "empty";
    const target = st.chat.items[messageId]!;
    const atts = target.kind === "user" ? (target.attachments ?? []) : [];
    const sid = st.chat.sessionId;
    if (!sid || !wsConnected("chat")) return get().send(text, { attachments: atts });
    // 文档口径三步（protocol.md §10.2 / 后端 docstring）：先 PATCH 原消息
    // 文本、再截断、再重发——三步全部服务端落盘。缺了 PATCH 这步会让编辑
    // 端点成为 UI 死代码，审计轨迹也与文档不符。
    const histIdx = await locateUserHistoryIndex(sid, st.chat.items, messageId);
    if (histIdx === null) return "empty";
    if (histIdx === "error") return "offline";
    try {
      await api.patch(
        `/api/chat/sessions/${encodeURIComponent(sid)}/messages/${histIdx}`,
        { text },
      );
    } catch (err) {
      const msgText = err instanceof Error ? err.message : String(err);
      return /^HTTP 4/.test(msgText) ? "empty" : "offline";
    }
    const cut = await truncateHistory(sid, histIdx);
    if (cut === null) return "empty";
    if (cut === "error") return "offline";
    discardPendingDeltas();
    set((s) => ({
      chat: {
        ...s.chat,
        items: s.chat.items.slice(0, messageId),
        phase: "idle",
        error: null,
        stopReason: null,
        finishedAt: null,
      },
    }));
    return get().send(text, { attachments: atts });
  },

  respondApproval: (ok) => {
    const appr = get().chat.approval;
    if (!appr) return;
    // R13-C：后端 120s 超时已自动 deny 且不发清除帧——过期回执是空转，
    // 卡片由视图置灰禁点，这里再兜一道（时钟竞态/编程调用）。
    if (Date.now() >= appr.deadline) return;
    if (!wsSend({ action: "approval", id: appr.id, approved: ok }, "chat")) return;
    set((s) => ({ chat: applyApprovalResponse(s.chat) }));
  },

  /* Plan 门裁决（方案 1）：id 必须匹配当前待决计划（服务端同样校验，
   * 迟到回执双向忽略）；本地立即收卡，计划文本已留在消息流里。 */
  respondPlan: (ok) => {
    const plan = get().chat.plan;
    if (!plan) return;
    if (Date.now() >= plan.deadline) return;
    if (!wsSend({ action: "plan_decision", id: plan.id, approved: ok }, "chat")) {
      return;
    }
    set((s) => ({ chat: { ...s.chat, plan: null } }));
  },

  stop: () => {
    wsSend({ action: "stop" }, "chat");
  },

  newSession: () => {
    // R14-S：丢弃未冲刷的增量，绝不串进新会话（服务端历史是权威）
    discardPendingDeltas();
    cancelReconnect();
    wsClose("chat");
    activeQuery = "";
    lastSeq = 0;
    set({ conn: "idle", chat: emptyChat(), pendingAttachments: [] });
  },

  openSession: async (id) => {
    if (get().chat.sessionId === id && wsConnected("chat")) return;
    const token = ++openToken;
    const hist = await api.get<{ messages: HistoryMessage[] }>(
      `/api/chat/sessions/${encodeURIComponent(id)}`,
    );
    // R13-D：await 期间有更新的切换发起 → 本次静默放弃（state/wsClose 都不碰）
    if (token !== openToken) return;
    const items = historyToItems(hist.messages || []);
    // R14-S：旧会话未冲刷的增量在此一并作废（不冲进即将载入的新流）
    discardPendingDeltas();
    cancelReconnect();
    wsClose("chat");
    lastSeq = 0; // 新会话新游标：不跨会话续播
    set({ conn: "connecting", chat: { ...emptyChat(), sessionId: id, items } });
    try {
      await connectSocket(`session=${encodeURIComponent(id)}`);
      if (token !== openToken) return; // 连接期间被反超：新连接已接任，无需善后
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

  promoteSession: async (id, prompt) => {
    const res = await api.post<{ job_id?: string }>(
      `/api/chat/sessions/${encodeURIComponent(id)}/promote`,
      prompt ? { prompt } : {},
    );
    await get().refreshSessions(); // derived_run_count 徽标刷新
    return res.job_id ?? null;
  },

  reconnectNow: () => {
    cancelReconnect();
    reconnectAttempts = 0;
    const sid = get().chat.sessionId;
    if (!sid) return;
    set({ conn: "connecting" });
    connectSocket(`session=${encodeURIComponent(sid)}`, {
      attachAfter: lastSeq,
    }).catch(() => giveUpReconnect());
  },
}));

/** steer 发送失败的兜底（R16 语义重写）：断线不终止回合，服务端继续跑到
 * 终态并落盘——phase 必须保持 running。旧实现沿用 R13 的「本回合已终止」
 * 文案把 phase 打成 error：与耐久化契约直接矛盾，还会掩盖重连横幅与手动
 * 重连入口；随后 attach 到仍在跑的回合时 replay_begin 又会把相位翻回
 * running，界面出现「已终止→又思考中」的跳动。这里只冲刷缓冲并确保
 * 重连机器在转，横幅自会引导用户。 */
function nudgeReconnectAfterSteerFailure(): void {
  flushPendingDeltas();
  if (!wsConnected("chat")) scheduleReconnect();
}

/** 当前连接附着的查询串（调试/视图判断用）。 */
export function activeChatQuery() {
  return activeQuery;
}

/* 重连诊断钩子（常设）：把重连机器的模块级内部态暴露给页面外。
 * 动机：E2E 曾出现「断连横幅可见但重连从未真正建连」的环境性静默失败，
 * 三种可能（定时器被清 / wantConnected=false / sessionId=null→giveUp）
 * 只有页面内地面真值能分辨——横幅和 SENT_FRAMES 都看不到这一层。
 * 纯只读快照，无行为影响；E2E harness（e2e_smoke_r16.py 的 [dbg] 探针）
 * 与人工调试（控制台 __chatDebug()）共用。 */
if (typeof window !== "undefined") {
  (window as unknown as Record<string, unknown>).__chatDebug = () => ({
    conn: useChatStore.getState().conn,
    phase: useChatStore.getState().chat.phase,
    sid: useChatStore.getState().chat.sessionId,
    wantConnected,
    attempts: reconnectAttempts,
    timerArmed: reconnectTimer !== null,
    lastSeq,
    activeQuery,
  });
}
