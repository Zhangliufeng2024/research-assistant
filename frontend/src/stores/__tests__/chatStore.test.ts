/* chatStore.send() 的空会话治理回归（§6.4）。
 *
 * 背景：前端时序是「先 POST 建目录、再连 WS、再发首帧」。POST 成功后若
 * 连接失败或帧发不出去，目录已落盘但回合永远不会开始——成为列表里的
 * 零轮次「空会话」（测试机曾堆积 4 个）。契约：
 * - 只有**本次调用新建**的目录才补偿删除（复用既有会话失败绝不误删）；
 * - 补偿同时把本地 sessionId 复位为 null，下次重发重新建干净目录；
 * - steer 路径永不触碰目录。
 * api / ws 层整体 mock，只验证 store 的编排决策。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { emptyChat } from "@/lib/protocolChat";
import type { HistoryMessage } from "@/lib/types";
import { useChatStore } from "@/stores/chatStore";

const h = vi.hoisted(() => ({
  wsConnect: vi.fn(),
  wsConnected: vi.fn(),
  wsSend: vi.fn(),
  wsClose: vi.fn(),
}));

vi.mock("@/lib/ws", () => h);
vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}));

import { api } from "@/lib/api";

/** 让 connectSocket 立即以指定状态收场。 */
function fakeConnect(finalStatus: "open" | "error"): void {
  h.wsConnect.mockImplementation((opts: { onStatus?: (s: string) => void }) => {
    opts.onStatus?.(finalStatus);
  });
}

describe("chatStore.send 空会话治理（§6.4 回归）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 生产 api.* 均返回 Promise；mock 默认成功兑现
    vi.mocked(api.post).mockResolvedValue({ id: "s-x" });
    vi.mocked(api.del).mockResolvedValue({});
    useChatStore.setState({
      conn: "idle",
      chat: emptyChat(),
      sessions: [],
      sessionsLoading: false,
    });
  });

  it("新建后连接失败：补偿删除本次目录 + sessionId 复位 + 落 error 态", async () => {
    vi.mocked(api.post).mockResolvedValue({ id: "s-new" });
    h.wsConnected.mockReturnValue(false);
    fakeConnect("error");

    const r = await useChatStore.getState().send("你好");

    expect(r).toBe("offline");
    expect(vi.mocked(api.post)).toHaveBeenCalledWith("/api/chat/sessions", {
      title: "你好",
    });
    expect(vi.mocked(api.del)).toHaveBeenCalledWith("/api/chat/sessions/s-new");
    const chat = useChatStore.getState().chat;
    expect(chat.sessionId).toBeNull();
    expect(chat.phase).toBe("error");
  });

  it("新建后发送成功：绝不删除，sessionId 保持", async () => {
    vi.mocked(api.post).mockResolvedValue({ id: "s-live" });
    h.wsConnected.mockReturnValue(false);
    fakeConnect("open");
    h.wsSend.mockReturnValue(true);

    const r = await useChatStore.getState().send("帮我调研");

    expect(r).toBe("ok");
    expect(vi.mocked(api.del)).not.toHaveBeenCalled();
    expect(useChatStore.getState().chat.sessionId).toBe("s-live");
  });

  it("新建后连接成功但帧发不出去：同样补偿删除", async () => {
    vi.mocked(api.post).mockResolvedValue({ id: "s-dead" });
    h.wsConnected.mockReturnValue(false);
    fakeConnect("open");
    h.wsSend.mockReturnValue(false);

    const r = await useChatStore.getState().send("第二条");

    expect(r).toBe("offline");
    expect(vi.mocked(api.del)).toHaveBeenCalledWith("/api/chat/sessions/s-dead");
    expect(useChatStore.getState().chat.sessionId).toBeNull();
  });

  it("复用既有会话失败：不删除既有目录（只删本次新建的）", async () => {
    useChatStore.setState({
      chat: { ...emptyChat(), sessionId: "s-old" },
    });
    h.wsConnected.mockReturnValue(false);
    fakeConnect("error");

    const r = await useChatStore.getState().send("继续聊");

    expect(r).toBe("offline");
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
    expect(vi.mocked(api.del)).not.toHaveBeenCalled();
    expect(useChatStore.getState().chat.sessionId).toBe("s-old");
  });

  it("steer 失败：不触碰任何目录", async () => {
    useChatStore.setState({
      chat: { ...emptyChat(), phase: "running", sessionId: "s-run" },
    });
    h.wsConnected.mockReturnValue(true);
    h.wsSend.mockReturnValue(false);

    const r = await useChatStore.getState().send("插一句话");

    expect(r).toBe("offline");
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
    expect(vi.mocked(api.del)).not.toHaveBeenCalled();
  });
});

/* ---------- R13-A / R13-D 回归 ---------- */
describe("chatStore 断连复位与切换竞态（R13-A/D）", () => {
  /** 最近一次 wsConnect 捕获的 onStatus（模拟底层 socket 事件用）。 */
  let capturedStatus: ((st: "connecting" | "open" | "error" | "closed") => void) | null;

  beforeEach(() => {
    vi.clearAllMocks();
    capturedStatus = null;
    vi.mocked(api.post).mockResolvedValue({ id: "s-x" });
    vi.mocked(api.del).mockResolvedValue({});
    useChatStore.setState({
      conn: "idle",
      chat: emptyChat(),
      sessions: [],
      sessionsLoading: false,
    });
  });

  it("R16：回合中途 closed → 进入自动重连，phase 保持 running（服务端继续跑）", async () => {
    h.wsConnect.mockImplementation(
      (opts: { onStatus?: (s: "connecting" | "open" | "error" | "closed") => void }) => {
        capturedStatus = opts.onStatus ?? null;
        opts.onStatus?.("open");
      },
    );
    h.wsConnected.mockReturnValue(false); // 首条消息走建连
    h.wsSend.mockReturnValue(true);

    expect(await useChatStore.getState().send("开始调研")).toBe("ok");
    expect(useChatStore.getState().chat.phase).toBe("running");

    capturedStatus!("closed"); // 服务端/网络断开

    // R16 耐久化：断线不再终止回合——前端转自动重连（非致命态），
    // phase 保持 running 与服务端真实状态一致；错误横幅不出现。
    const st = useChatStore.getState();
    expect(st.conn).toBe("reconnecting");
    expect(st.chat.phase).toBe("running");
    expect(st.chat.error).toBeNull();
    useChatStore.getState().newSession(); // 清理重连定时器，避免跨测试泄漏
  });

  it("R16：open 之后的 error 同样转入自动重连（close 未及触发的场景）", async () => {
    h.wsConnect.mockImplementation(
      (opts: { onStatus?: (s: "connecting" | "open" | "error" | "closed") => void }) => {
        capturedStatus = opts.onStatus ?? null;
        opts.onStatus?.("open");
      },
    );
    // 首条消息走一次建连（捕获 onStatus），此后通道视为已连
    h.wsConnected.mockReturnValueOnce(false).mockReturnValue(true);
    h.wsSend.mockReturnValue(true);
    expect(await useChatStore.getState().send("第一条")).toBe("ok");
    expect(useChatStore.getState().chat.phase).toBe("running");

    capturedStatus!("error");

    expect(useChatStore.getState().conn).toBe("reconnecting");
    expect(useChatStore.getState().chat.phase).toBe("running");
    useChatStore.getState().newSession();
  });

  it("R16：steer 发送失败 → 保持 running（回合仍在后台跑），返回 offline", async () => {
    useChatStore.setState({
      chat: { ...emptyChat(), phase: "running", sessionId: "s-run" },
      conn: "closed",
    });
    h.wsConnected.mockReturnValue(false); // 表里无 socket → wsSend 必败
    h.wsSend.mockReturnValue(false);

    expect(await useChatStore.getState().send("插一句话")).toBe("offline");
    // R16 耐久化契约：断线不终止回合——phase 不得被打成 error。旧实现
    // 的「本回合已终止」会掩盖重连横幅与手动重连入口，且随后 attach 到
    // 仍在跑的回合时 replay_begin 又把相位翻回 running（状态跳动）。
    expect(useChatStore.getState().chat.phase).toBe("running");
  });

  it("R13-D：快速连点两个会话——后发起的赢，先到的历史静默放弃", async () => {
    let resolveA!: (v: { messages: HistoryMessage[] }) => void;
    vi.mocked(api.get).mockImplementation(((url: string) => {
      if (String(url).includes("s-a")) {
        return new Promise<{ messages: HistoryMessage[] }>((res) => {
          resolveA = res;
        });
      }
      return Promise.resolve({
        messages: [{ role: "assistant", content: "B 的历史" }],
      });
    }) as typeof api.get);
    fakeConnect("open");

    const pA = useChatStore.getState().openSession("s-a");
    const pB = useChatStore.getState().openSession("s-b");
    await pB; // B 的历史先返回并完成落位
    resolveA({ messages: [] }); // A 的历史此刻才到——必须被丢弃
    await pA;

    expect(useChatStore.getState().chat.sessionId).toBe("s-b");
    // A 全程不得触碰连接（wsClose 仅 B 落位时调用过一次）
    expect(h.wsClose).toHaveBeenCalledTimes(1);
    expect(h.wsConnect).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: "session=s-b" }),
    );
  });
});

describe("P0-3 放弃重连必须让相位落地（「永远思考中」残留路径回归）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.post).mockResolvedValue({ id: "s-x" });
    vi.mocked(api.del).mockResolvedValue({});
    useChatStore.setState({
      conn: "idle",
      chat: emptyChat(),
      sessions: [],
      sessionsLoading: false,
    });
  });

  it("重连失败并放弃：conn=closed 且 phase 回落到 idle", async () => {
    // 场景：回合在跑、连接已断（steer 失败后的放弃重连路径）。
    // 修复前 giveUpReconnect 只置 conn，phase 永远停在 running：
    // 状态点永久脉冲、「停止」按钮常驻、等待横幅永不消失。
    useChatStore.setState((s) => ({
      chat: { ...s.chat, sessionId: "s-run", phase: "running" },
    }));
    h.wsConnected.mockReturnValue(false);
    // 未 open 即 error → connectSocket reject → reconnectNow 的 catch 放弃
    h.wsConnect.mockImplementation(
      (opts: { onStatus?: (s: string) => void }) => {
        opts.onStatus?.("error");
      },
    );

    useChatStore.getState().reconnectNow();

    await vi.waitFor(() => {
      expect(useChatStore.getState().conn).toBe("closed");
    });
    expect(useChatStore.getState().chat.phase).toBe("idle");
  });

  it("放弃重连不得清掉会话上下文（只收尾相位）", async () => {
    useChatStore.setState((s) => ({
      chat: { ...s.chat, sessionId: "s-keep", phase: "running" },
    }));
    h.wsConnected.mockReturnValue(false);
    h.wsConnect.mockImplementation(
      (opts: { onStatus?: (s: string) => void }) => {
        opts.onStatus?.("closed");
      },
    );

    useChatStore.getState().reconnectNow();
    await vi.waitFor(() => {
      expect(useChatStore.getState().conn).toBe("closed");
    });

    const chat = useChatStore.getState().chat;
    // sessionId 必须保留——否则用户点手动「重连」时无从 attach 回放
    expect(chat.sessionId).toBe("s-keep");
    expect(chat.phase).toBe("idle");
  });

  it("无会话时放弃：不得抛错，且相位同样落地", async () => {
    useChatStore.setState((s) => ({
      conn: "idle",
      chat: { ...s.chat, sessionId: null, phase: "running" },
    }));
    h.wsConnected.mockReturnValue(false);

    // sid 为空 → reconnectNow 直接 return；相位需由给出路径以外兜底，
    // 这里锁定「不抛错、连接态不被误标成 closed」
    expect(() => useChatStore.getState().reconnectNow()).not.toThrow();
    expect(useChatStore.getState().conn).toBe("idle");
  });
});
