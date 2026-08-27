/* taskStore 回归（R13-E，此前该 store 零测试）。
 *
 * 覆盖三块：
 * - respondApproval 的 null/过期守卫与「先发后清」（E① / R13-C）；
 * - observe 握手帧不得清零持久化 seq（E②，lastAction 标记区分路径）；
 * - start → progress/result 的基本 reduceTask 编排接线。
 * api / ws 层整体 mock（同 chatStore.test.ts 手法），localStorage 用 Map 替身。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { emptyTask } from "@/lib/protocolTask";
import type { ServerFrame } from "@/lib/types";
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

/** node 测试环境无 localStorage：Map 后备替身，返回底层 Map 供断言。 */
function stubStorage(): Map<string, string> {
  const map = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
    setItem: (k: string, v: string) => void map.set(k, v),
    removeItem: (k: string) => void map.delete(k),
  });
  return map;
}

/** 捕获 onMessage 并让建连立即 open——模拟服务端推帧的入口。 */
let deliverFrame: ((msg: ServerFrame) => void) | null = null;

function fakeOpenChannel(): void {
  h.wsConnect.mockImplementation(
    (opts: { onMessage?: (m: ServerFrame) => void; onStatus?: (s: string) => void }) => {
      deliverFrame = opts.onMessage ?? null;
      opts.onStatus?.("open");
    },
  );
  h.wsSend.mockReturnValue(true);
}

describe("taskStore（R13-E）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    deliverFrame = null;
    stubStorage();
    useTaskStore.setState({
      conn: "idle",
      task: emptyTask(),
      lastSeq: 0,
      runs: [],
      runsLoading: false,
      durableTasks: [],
      durableLoading: false,
      workflows: [],
      workflowsLoading: false,
    });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /* ---- E①：respondApproval 守卫 ---- */

  it("无待审时早退：不发空帧、不动状态", () => {
    expect(useTaskStore.getState().task.approval).toBeNull();
    useTaskStore.getState().respondApproval(true);
    expect(h.wsSend).not.toHaveBeenCalled();
  });

  it("正常审批：先发后清；发送失败保留卡片可重试", () => {
    const live = { id: "a1", tool: "bash", summary: "", deadline: Date.now() + 60_000 };
    useTaskStore.setState({ task: { ...emptyTask(), approval: live } });
    h.wsSend.mockReturnValueOnce(true);
    useTaskStore.getState().respondApproval(true);
    expect(h.wsSend).toHaveBeenCalledWith(
      { action: "approval", id: "a1", approved: true },
      "task",
    );
    expect(useTaskStore.getState().task.approval).toBeNull();

    const retry = { id: "a2", tool: "bash", summary: "", deadline: Date.now() + 60_000 };
    useTaskStore.setState({ task: { ...emptyTask(), approval: retry } });
    h.wsSend.mockReturnValueOnce(false);
    useTaskStore.getState().respondApproval(false);
    expect(useTaskStore.getState().task.approval?.id).toBe("a2");
  });

  it("过期审批 no-op（后端 120s 已自动 deny，R13-C）", () => {
    useTaskStore.setState({
      task: {
        ...emptyTask(),
        approval: { id: "a-old", tool: "bash", summary: "", deadline: Date.now() - 1000 },
      },
    });
    useTaskStore.getState().respondApproval(true);
    expect(h.wsSend).not.toHaveBeenCalled();
    // 卡片保留：由视图呈现「已超时」置灰态
    expect(useTaskStore.getState().task.approval?.id).toBe("a-old");
  });

  /* ---- E②：observe 握手不清零持久化 seq ---- */

  it("observe 的握手帧（带 task_id 无 seq）不清零已存水位", async () => {
    const map = stubStorage();
    fakeOpenChannel();
    expect(await useTaskStore.getState().observe("t-bg", 42)).toBe("ok");

    deliverFrame!({ type: "connected", task_id: "t-bg" });

    expect(map.get("ra.activeTaskId")).toBe("t-bg");
    expect(map.get("ra.activeTaskSeq")).toBe("42"); // 绝不许被抹成 0
    expect(useTaskStore.getState().lastSeq).toBe(42);
  });

  it("对照组：start 的握手帧落 taskId 且 seq 从 0 起持久化", async () => {
    const map = stubStorage();
    fakeOpenChannel();
    expect(await useTaskStore.getState().start({ query: "钙钛矿稳定性" })).toBe("ok");

    deliverFrame!({ type: "connected", task_id: "t-new" });

    expect(map.get("ra.activeTaskId")).toBe("t-new");
    expect(map.get("ra.activeTaskSeq")).toBe("0");
  });

  it("seq>0 帧推进 lastSeq 并同步持久化水位", async () => {
    const map = stubStorage();
    fakeOpenChannel();
    await useTaskStore.getState().start({ query: "主题" });
    deliverFrame!({ type: "connected", task_id: "t-new" });
    deliverFrame!({ type: "usage", seq: 7, budget: { cost_usd: 0.5 } });

    expect(useTaskStore.getState().lastSeq).toBe(7);
    expect(map.get("ra.activeTaskSeq")).toBe("7");
  });

  /* ---- 基本 reduceTask 编排 ---- */

  it("start → progress → result 全程驱动任务态", async () => {
    fakeOpenChannel();
    await useTaskStore.getState().start({ query: "量子点研究" });
    expect(useTaskStore.getState().task.phase).toBe("idle"); // connected 前保持本地初值

    deliverFrame!({ type: "connected", task_id: "t-1" });
    expect(useTaskStore.getState().task.phase).toBe("running");
    expect(useTaskStore.getState().task.taskId).toBe("t-1");

    deliverFrame!({ type: "progress", stage: "planning", message: "规划中" });
    expect(useTaskStore.getState().task.timeline[0]).toBe("active");

    deliverFrame!({ type: "result", status: "complete", metadata: { title: "论文" } });
    const done = useTaskStore.getState().task;
    expect(done.phase).toBe("done");
    expect(done.approval).toBeNull();
    expect(done.activity.at(-1)?.kind).toBe("ok");
  });

  it("resume 复用 launch 通道：以 start 帧携带 resume_run 字段（现状线格式）", async () => {
    fakeOpenChannel();
    expect(await useTaskStore.getState().resume("run_1")).toBe("ok");
    expect(h.wsConnect).toHaveBeenCalled();
    expect(h.wsSend).toHaveBeenCalledWith(
      expect.objectContaining({ action: "start", resume_run: "run_1" }),
      "task",
    );
    expect(useTaskStore.getState().task.resumeRun).toBe("run_1");
  });
});
