/* chatStore 流式增量合帧（R14-S）。
 *
 * 契约：
 * - 运行中的 text 增量进缓冲，至多每 ~50ms 合并写入一次 store；
 * - 工具卡/审批/result/error/done 等关键帧先冲刷保序、再即时归约；
 * - 流结束（result/error/断连）同步冲刷，最终文本绝不丢字；
 * - 会话切换/新建丢弃缓冲，绝不串话（服务端 history 是权威）。
 * api / ws 层整体 mock；用假定时器驱动 50ms 窗口。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { emptyChat } from "@/lib/protocolChat";
import type { ChatState, ServerFrame } from "@/lib/types";
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

let deliver: ((m: ServerFrame) => void) | null = null;
let setStatus: ((s: "open" | "error" | "closed") => void) | null = null;

/** 开一轮运行中的回合：捕获 onMessage/onStatus 入口，返回推帧函数。 */
async function startTurn(prompt = "写一段长文"): Promise<void> {
  h.wsConnected.mockReturnValue(false);
  h.wsConnect.mockImplementation(
    (opts: {
      onMessage?: (m: ServerFrame) => void;
      onStatus?: (s: "open" | "error" | "closed") => void;
    }) => {
      deliver = opts.onMessage ?? null;
      setStatus = opts.onStatus ?? null;
      opts.onStatus?.("open");
    },
  );
  h.wsSend.mockReturnValue(true);
  vi.mocked(api.post).mockResolvedValue({ id: "s-co" });
  expect(await useChatStore.getState().send(prompt)).toBe("ok");
  expect(useChatStore.getState().chat.phase).toBe("running");
}

/** 统计「订阅之后」chat 引用变化次数（≈ 归约应用次数），基线为当前值。 */
function countChatApplications(): { count(): number; unsub(): void } {
  let n = 0;
  let lastRef: ChatState = useChatStore.getState().chat;
  const unsub = useChatStore.subscribe((s) => {
    if (s.chat !== lastRef) {
      n += 1;
      lastRef = s.chat;
    }
  });
  return { count: () => n, unsub };
}

function lastTextItem(): { kind: string; text: string } | undefined {
  const items = useChatStore.getState().chat.items;
  return items[items.length - 1] as { kind: string; text: string } | undefined;
}

describe("chatStore 流式增量合帧（R14-S）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    deliver = null;
    setStatus = null;
    useChatStore.setState({
      conn: "idle",
      chat: emptyChat(),
      sessions: [],
      sessionsLoading: false,
    });
  });

  afterEach(() => {
    // 丢弃残留缓冲 + 清残留定时器，绝不污染同文件后续用例
    useChatStore.getState().newSession();
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it("合帧后最终完整性：30 条增量全部落屏且合并为同一气泡", async () => {
    await startTurn();
    for (let i = 0; i < 30; i++) deliver!({ type: "text", delta: `片段${i}·` });

    vi.advanceTimersByTime(50);

    expect(useChatStore.getState().chat.items).toHaveLength(2); // user + 单一 text 气泡
    const merged = Array.from({ length: 30 }, (_, i) => `片段${i}·`).join("");
    expect(lastTextItem()!.text).toBe(merged);
  });

  it("节流窗口内多条 delta 只应用一次；窗口未到前 store 不动", async () => {
    await startTurn();
    const counter = countChatApplications(); // 基线=当前 chat 引用

    for (let i = 0; i < 10; i++) deliver!({ type: "text", delta: String(i) });

    // 窗口未到：缓冲滞留，store 未见增量
    expect(useChatStore.getState().chat.items).toHaveLength(1);
    expect(counter.count()).toBe(0);

    vi.advanceTimersByTime(49);
    expect(counter.count()).toBe(0); // 仍在窗口内

    vi.advanceTimersByTime(1);
    expect(counter.count()).toBe(1); // 恰好一次批量应用
    expect(lastTextItem()!.text).toBe("0123456789");
    counter.unsub();
  });

  it("流结束立即冲刷：result 帧无需等定时器，最终文本不丢字", async () => {
    await startTurn();
    const deltas = Array.from({ length: 8 }, (_, i) => `尾${i}`);
    for (const d of deltas) deliver!({ type: "text", delta: d });

    deliver!({ type: "result", stop_reason: "complete", turns: 1 }); // 不推进时间

    const chat = useChatStore.getState().chat;
    expect(chat.phase).toBe("done");
    expect(lastTextItem()!.text).toBe(deltas.join(""));

    // 冲刷后不得有迟到的二次追加
    vi.advanceTimersByTime(500);
    expect(useChatStore.getState().chat.items).toHaveLength(2);
    expect(lastTextItem()!.text).toBe(deltas.join(""));
  });

  it("关键帧即时生效且保序：工具卡先吃掉缓冲文本，后续增量另起新气泡", async () => {
    await startTurn();
    deliver!({ type: "text", delta: "前" });
    deliver!({ type: "text", delta: "中" });
    deliver!({
      type: "tool_card",
      id: "c1",
      tool: "bash",
      status: "running",
    });

    // 不推进时间：卡片即刻可见，且缓冲文本先于卡片落位
    const kinds = useChatStore.getState().chat.items.map((i) => i.kind);
    expect(kinds).toEqual(["user", "text", "tool"]);
    expect(
      (useChatStore.getState().chat.items[1] as { text: string }).text,
    ).toBe("前中");

    deliver!({ type: "text", delta: "后" });
    vi.advanceTimersByTime(50);
    // 卡片打断后 appendDelta 另起新气泡——顺序如实反映到达序
    expect(useChatStore.getState().chat.items.map((i) => i.kind)).toEqual([
      "user",
      "text",
      "tool",
      "text",
    ]);
  });

  it("非流式状态变更不受节流影响：审批帧即时上屏", async () => {
    await startTurn();
    deliver!({ type: "text", delta: "部分输出" }); // 在缓冲里

    deliver!({ type: "approval_request", id: "a1", tool: "bash", summary: "ls" });

    expect(useChatStore.getState().chat.approval?.id).toBe("a1"); // 即时，不等窗口
  });

  it("会话切换（newSession）丢弃缓冲：迟到定时器不把旧增量串进新会话", async () => {
    await startTurn();
    for (let i = 0; i < 5; i++) deliver!({ type: "text", delta: `残${i}` });

    useChatStore.getState().newSession();
    vi.advanceTimersByTime(500);

    const chat = useChatStore.getState().chat;
    expect(chat.phase).toBe("idle");
    expect(chat.items).toHaveLength(0);
  });

  it("会话切换（openSession）丢弃缓冲：历史恢复后无泄漏片段", async () => {
    await startTurn();
    deliver!({ type: "text", delta: "会被丢弃的尾巴" });

    vi.mocked(api.get).mockResolvedValue({
      messages: [{ role: "assistant", content: "历史回答" }],
    });
    h.wsConnect.mockImplementation(
      (opts: {
        onMessage?: (m: ServerFrame) => void;
        onStatus?: (s: string) => void;
      }) => {
        deliver = opts.onMessage ?? null;
        opts.onStatus?.("open");
      },
    );
    await useChatStore.getState().openSession("s-old");

    vi.advanceTimersByTime(500);

    const items = useChatStore.getState().chat.items;
    expect(items).toEqual([{ kind: "text", text: "历史回答", t: 0 }]);
  });

  it("断线重连（R16 协同）：closed 先冲刷缓冲（已到文本如实呈现），phase 保持 running 转重连", async () => {
    await startTurn();
    deliver!({ type: "text", delta: "断前的最后一段" });

    setStatus!("closed"); // 不推进时间：断线路径同步冲刷，不丢字

    const chat = useChatStore.getState().chat;
    // R16 耐久化：服务端回合继续跑 → phase 不再落 error；前端转自动重连
    expect(chat.phase).toBe("running");
    expect(useChatStore.getState().conn).toBe("reconnecting");
    expect(lastTextItem()!.text).toBe("断前的最后一段");
    useChatStore.getState().newSession(); // 清理重连定时器，避免跨测试泄漏
  });
});
