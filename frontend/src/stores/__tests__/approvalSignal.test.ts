/* 全局审批 pending 信号（R14-A）：跨 chat/task 通道聚合。
 *
 * 契约：
 * - count = 两通道未决审批数之和（各至多 1，故 0-2）；
 * - last 仅在「新到达」（首次出现或换新 id）时更新；同 id 重推不覆盖；
 * - 审批被解决（清空）后 count 回落，last 保留供提醒文案使用。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { emptyChat } from "@/lib/protocolChat";
import { emptyTask } from "@/lib/protocolTask";
import {
  getLastApprovalSignal,
  getPendingApprovalCount,
  useApprovalSignalStore,
} from "@/stores/approvalSignal";
import { useChatStore } from "@/stores/chatStore";
import { useTaskStore } from "@/stores/taskStore";

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

function appr(id: string) {
  return { id, tool: `tool-${id}`, summary: `${id} 的摘要`, deadline: Date.now() + 60_000 };
}

describe("approvalSignal（R14-A）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
    useChatStore.setState({ conn: "idle", chat: emptyChat() });
    useTaskStore.setState({ conn: "idle", task: emptyTask(), lastSeq: 0 });
    useApprovalSignalStore.setState({ count: 0, last: null });
  });
  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
  });

  it("初始：count=0、last=null", () => {
    expect(getPendingApprovalCount()).toBe(0);
    expect(getLastApprovalSignal()).toBeNull();
  });

  it("chat 审批到达：count=1，last 记录来源/工具/摘要/到达时刻", () => {
    const before = Date.now();
    useChatStore.setState((s) => ({ chat: { ...s.chat, approval: appr("a-chat") } }));

    expect(getPendingApprovalCount()).toBe(1);
    const last = getLastApprovalSignal()!;
    expect(last).toMatchObject({
      id: "a-chat",
      source: "chat",
      tool: "tool-a-chat",
      summary: "a-chat 的摘要",
    });
    expect(last.at).toBeGreaterThanOrEqual(before);
  });

  it("双通道并发：count=2；task 到达把 last 切到 task 来源", () => {
    useChatStore.setState((s) => ({ chat: { ...s.chat, approval: appr("a-1") } }));
    useTaskStore.setState((s) => ({ task: { ...s.task, approval: appr("a-2") } }));

    expect(getPendingApprovalCount()).toBe(2);
    expect(getLastApprovalSignal()?.source).toBe("task");

    // 解决其一：count 回落、last 不回退
    useChatStore.setState((s) => ({ chat: { ...s.chat, approval: null } }));
    expect(getPendingApprovalCount()).toBe(1);
    expect(getLastApprovalSignal()?.id).toBe("a-2");
  });

  it("同通道换新 id：count 不变，last 更新为新请求", () => {
    useChatStore.setState((s) => ({ chat: { ...s.chat, approval: appr("旧") } }));
    vi.advanceTimersByTime(1000);
    useChatStore.setState((s) => ({ chat: { ...s.chat, approval: appr("新") } }));

    expect(getPendingApprovalCount()).toBe(1);
    expect(getLastApprovalSignal()?.id).toBe("新");
  });

  it("同 id 重推（服务端重发同一请求）不重复记录到达时刻", () => {
    const first = appr("同帧");
    useChatStore.setState((s) => ({ chat: { ...s.chat, approval: first } }));
    const firstAt = getLastApprovalSignal()!.at;

    vi.advanceTimersByTime(5000);
    // 新对象、同 id：模拟服务端重推
    useChatStore.setState((s) => ({ chat: { ...s.chat, approval: appr("同帧") } }));

    expect(getLastApprovalSignal()!.at).toBe(firstAt);
  });

  it("React hooks 选择器与 store 状态一致（usePendingApprovalCount/useLastApprovalSignal 的数据源）", () => {
    expect(useApprovalSignalStore.getState()).toEqual({
      count: getPendingApprovalCount(),
      last: getLastApprovalSignal(),
    });
    useTaskStore.setState((s) => ({ task: { ...s.task, approval: appr("t-9") } }));
    expect(useApprovalSignalStore.getState().count).toBe(1);
    expect(useApprovalSignalStore.getState().last?.source).toBe("task");
  });
});
