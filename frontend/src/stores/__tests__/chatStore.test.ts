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
