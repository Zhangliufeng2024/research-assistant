/* chatStore 消息操作（R16 真替换）：regenerateMessage / editAndResend。
 *
 * 契约要点：
 * - 流式中一律 busy（放行会被 send() 当 steer，语义相反）；
 * - 真替换语义（R16）：先 GET history 定位目标用户提问的物理下标，
 *   POST truncate 截断至其之前，本地 items 同步裁剪，再重发——旧回答
 *   真正从对话流消失，而非追加一轮「平行答案」（R14-M 的保守重发仅在
 *   草稿态/离线时作为回落保留）；
 * - 编辑重发是文档口径的三步：PATCH 原消息文本 → truncate → 重发
 *   （三步全部服务端落盘，缺 PATCH 会让编辑端点成 UI 死代码）；
 * - **原消息的 attachments 必须随重发入史**：truncate 会把带附件的旧
 *   user 条目整条删掉，不显式携带就永久断链（对抗性审查抓出）；
 * - 定位失败 / 提示词为空 / 会话错位 / 序号失配 → empty；发送链路结果透传。
 * api / ws 层整体 mock（同 chatStore.test.ts 手法）。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { isValidUserIndex, resolveRegenerateTarget } from "@/lib/messageOps";
import { emptyChat } from "@/lib/protocolChat";
import type { ChatItem } from "@/lib/types";
import { useChatStore } from "@/stores/chatStore";

const h = vi.hoisted(() => ({
  wsConnect: vi.fn(),
  wsConnected: vi.fn(),
  wsSend: vi.fn(),
  wsClose: vi.fn(),
}));

vi.mock("@/lib/ws", () => h);
vi.mock("@/lib/api", () => ({
  api: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
    upload: vi.fn(),
  },
}));

import { api } from "@/lib/api";

const CONVO: ChatItem[] = [
  { kind: "user", text: "第一问", t: 1 },
  { kind: "text", text: "第一答", t: 2 },
  { kind: "user", text: "第二问", t: 3 },
  { kind: "text", text: "第二答", t: 4 },
];

/** 以固定会话与聊天流播种 store。 */
function seed(items: ChatItem[], phase: "idle" | "running" = "idle"): void {
  useChatStore.setState({
    conn: "open",
    chat: { ...emptyChat(), sessionId: "s-op", phase, items },
  });
}

describe("messageOps 纯函数", () => {
  it("resolveRegenerateTarget：assistant 下标向前找最近 user；指向 user 时返回自身", () => {
    expect(resolveRegenerateTarget(CONVO, 3)).toBe(2); // 第二答 → 第二问
    expect(resolveRegenerateTarget(CONVO, 1)).toBe(0); // 第一答 → 第一问
    expect(resolveRegenerateTarget(CONVO, 2)).toBe(2); // 直接指 user
    // 工具卡占位同样向前穿透
    const withTool: ChatItem[] = [
      ...CONVO,
      { kind: "tool", ref: "c1", t: 5 },
    ];
    expect(resolveRegenerateTarget(withTool, 4)).toBe(2);
  });

  it("resolveRegenerateTarget：越界/非整数/无前置 user → null", () => {
    expect(resolveRegenerateTarget(CONVO, -1)).toBeNull();
    expect(resolveRegenerateTarget(CONVO, 99)).toBeNull();
    expect(resolveRegenerateTarget(CONVO, 1.5)).toBeNull();
    expect(resolveRegenerateTarget([{ kind: "text", text: "a", t: 1 }], 0)).toBeNull();
  });

  it("isValidUserIndex：恰好指向 user 气泡才为真（assistant 不借用前置）", () => {
    expect(isValidUserIndex(CONVO, 0)).toBe(true);
    expect(isValidUserIndex(CONVO, 3)).toBe(false);
    expect(isValidUserIndex(CONVO, 4)).toBe(false);
  });
});

/** 服务端 history.json 的镜像（与 CONVO 对应的两轮问答）。 */
const HISTORY = {
  messages: [
    { role: "user", content: "第一问" },
    { role: "assistant", content: "第一答" },
    { role: "user", content: "第二问" },
    { role: "assistant", content: "第二答" },
  ],
};

describe("chatStore.regenerateMessage / editAndResend（R16 真替换）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    h.wsConnected.mockReturnValue(true);
    h.wsSend.mockReturnValue(true);
    vi.mocked(api.get).mockResolvedValue(HISTORY);
    vi.mocked(api.post).mockResolvedValue({ ok: true });
    vi.mocked(api.patch).mockResolvedValue({ ok: true });
    seed(CONVO);
  });

  it("regenerate：对 assistant 气泡 → truncate 至其前最近 user 提问，旧回答移除后重发", async () => {
    const r = await useChatStore.getState().regenerateMessage("s-op", 3);

    expect(r).toBe("ok");
    // 「第二问」是第 2 条真实用户气泡 → 史中下标 2；截断保留其之前两条
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/api/chat/sessions/s-op/truncate",
      { keep: 2 },
    );
    const items = useChatStore.getState().chat.items;
    // 本地同步裁剪：旧的「第二问/第二答」消失，仅剩首轮 + 重发的提问
    expect(items).toHaveLength(3);
    expect(items[0]).toMatchObject({ kind: "user", text: "第一问" });
    expect(items[1]).toMatchObject({ kind: "text", text: "第一答" });
    expect(items[2]).toMatchObject({ kind: "user", text: "第二问" });
    expect(h.wsSend).toHaveBeenCalledWith(
      { action: "user", text: "第二问" },
      "chat",
    );
  });

  it("regenerate：直接指向首条 user 气泡 → truncate keep=0 后整流重发", async () => {
    const r = await useChatStore.getState().regenerateMessage("s-op", 0);
    expect(r).toBe("ok");
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/api/chat/sessions/s-op/truncate",
      { keep: 0 },
    );
    const items = useChatStore.getState().chat.items;
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "user", text: "第一问" });
  });

  it("regenerate：史中序号失配（历史被外部改动）→ empty 且不截断不发帧", async () => {
    vi.mocked(api.get).mockResolvedValue({
      messages: [{ role: "user", content: "只有一条" }],
    });
    const r = await useChatStore.getState().regenerateMessage("s-op", 3);
    expect(r).toBe("empty");
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
    expect(h.wsSend).not.toHaveBeenCalled();
  });

  it("regenerate：assistant 前没有 user（如纯历史恢复残缺）→ empty", async () => {
    seed([{ kind: "text", text: "孤儿回答", t: 1 }]);
    const r = await useChatStore.getState().regenerateMessage("s-op", 0);
    expect(r).toBe("empty");
    expect(h.wsSend).not.toHaveBeenCalled();
  });

  it("regenerate：越界下标 / 会话错位 → empty 且不发帧", async () => {
    expect(await useChatStore.getState().regenerateMessage("s-op", 99)).toBe("empty");
    expect(await useChatStore.getState().regenerateMessage("s-别的会话", 3)).toBe(
      "empty",
    );
    expect(h.wsSend).not.toHaveBeenCalled();
  });

  it("regenerate：草稿态（sessionId=null）传 null 走完整发送路径（建目录+发帧）", async () => {
    seed([{ kind: "user", text: "还没建目录的问题", t: 1 }]);
    useChatStore.setState((s) => ({ chat: { ...s.chat, sessionId: null } }));
    h.wsConnected.mockReturnValue(false);
    h.wsConnect.mockImplementation(
      (opts: { onStatus?: (s: string) => void }) => opts.onStatus?.("open"),
    );
    vi.mocked(api.post).mockResolvedValue({ id: "s-draft" });

    const r = await useChatStore.getState().regenerateMessage(null, 0);

    expect(r).toBe("ok");
    expect(vi.mocked(api.post)).toHaveBeenCalledWith("/api/chat/sessions", {
      title: "还没建目录的问题",
    });
    expect(h.wsSend).toHaveBeenCalledWith(
      { action: "user", text: "还没建目录的问题" },
      "chat",
    );
  });

  it("editAndResend：三步口径 PATCH→truncate→新文本重发（原气泡连同旧回答一并移除）", async () => {
    const r = await useChatStore.getState().editAndResend("s-op", 0, "  改后的问题  ");

    expect(r).toBe("ok");
    // 第一步：原消息文本先服务端落盘（审计轨迹与文档一致）
    expect(vi.mocked(api.patch)).toHaveBeenCalledWith(
      "/api/chat/sessions/s-op/messages/0",
      { text: "改后的问题" },
    );
    // 第二步：截断保留其之前
    expect(vi.mocked(api.post)).toHaveBeenCalledWith(
      "/api/chat/sessions/s-op/truncate",
      { keep: 0 },
    );
    const items = useChatStore.getState().chat.items;
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: "user", text: "改后的问题" });
    expect(h.wsSend).toHaveBeenCalledWith(
      { action: "user", text: "改后的问题" },
      "chat",
    );
  });

  it("regenerate/editAndResend：原消息的 attachments 必须随重发入史", async () => {
    const atts = [{ name: "数据.csv", path: "X:/w/outputs/s-op/uploads/数据.csv" }];
    const seeded = (): ChatItem[] => [
      { kind: "user", text: "第一问", t: 1 },
      { kind: "text", text: "第一答", t: 2 },
      { kind: "user", text: "第二问", t: 3, attachments: atts },
      { kind: "text", text: "第二答", t: 4 },
    ];

    seed(seeded());
    await useChatStore.getState().regenerateMessage("s-op", 3);
    expect(h.wsSend).toHaveBeenLastCalledWith(
      { action: "user", text: "第二问", attachments: atts },
      "chat",
    );

    // 重发后 phase 停在乐观 running（无服务端帧回推），重播种再验编辑流
    seed(seeded());
    await useChatStore.getState().editAndResend("s-op", 2, "换个问法");
    expect(h.wsSend).toHaveBeenLastCalledWith(
      { action: "user", text: "换个问法", attachments: atts },
      "chat",
    );
  });

  it("无附件的原消息重发不得夹带输入框暂存 chips；显式空数组即明确不带", async () => {
    useChatStore.setState({ pendingAttachments: [
      { name: "顺手传的.pdf", path: "X:/w/outputs/s-op/uploads/x.pdf" },
    ] });

    await useChatStore.getState().regenerateMessage("s-op", 3);
    expect(h.wsSend).toHaveBeenLastCalledWith(
      { action: "user", text: "第二问" },
      "chat",
    );
    // 暂存 chips 不被真替换流程消费，留给下一条普通消息
    expect(useChatStore.getState().pendingAttachments).toHaveLength(1);
  });

  it("editAndResend：PATCH 被 4xx 拒绝 → empty 且不截断不发帧", async () => {
    vi.mocked(api.patch).mockRejectedValue(new Error("HTTP 409"));
    const r = await useChatStore.getState().editAndResend("s-op", 0, "改不动");
    expect(r).toBe("empty");
    expect(vi.mocked(api.post)).not.toHaveBeenCalled();
    expect(h.wsSend).not.toHaveBeenCalled();
  });

  it("editAndResend：目标不是 user 气泡 / 新文本为空白 → empty", async () => {
    expect(await useChatStore.getState().editAndResend("s-op", 1, "x")).toBe("empty");
    expect(await useChatStore.getState().editAndResend("s-op", 0, "   ")).toBe("empty");
    expect(h.wsSend).not.toHaveBeenCalled();
  });

  it("两个操作在流式中一律 busy 拒绝且绝不发帧（防被当 steer）", async () => {
    seed(CONVO, "running");

    expect(await useChatStore.getState().regenerateMessage("s-op", 3)).toBe("busy");
    expect(await useChatStore.getState().editAndResend("s-op", 0, "插队")).toBe(
      "busy",
    );
    expect(h.wsSend).not.toHaveBeenCalled();
  });

  it("发送链路失败透传 offline：wsSend 失败时 running 被复位", async () => {
    h.wsConnected.mockReturnValue(false); // 视为通道已死
    h.wsConnect.mockImplementation(
      (opts: { onStatus?: (s: string) => void }) => opts.onStatus?.("error"),
    );

    const r = await useChatStore.getState().editAndResend("s-op", 0, "再来一次");

    expect(r).toBe("offline");
    expect(useChatStore.getState().chat.phase).toBe("error");
  });
});
