import { describe, expect, it } from "vitest";
import {
  APPROVAL_TIMEOUT_S,
  applyApprovalResponse,
  applyUserMessage,
  emptyChat,
  historyToItems,
  reduceChat,
} from "../protocolChat";

describe("reduceChat", () => {
  it("connected 设置 sessionId；同 id 幂等返回原引用", () => {
    const s0 = emptyChat();
    const s1 = reduceChat(s0, { type: "connected", session_id: "s1" });
    expect(s1.sessionId).toBe("s1");
    expect(reduceChat(s1, { type: "connected", session_id: "s1" })).toBe(s1);
    expect(reduceChat(s1, { type: "connected" })).toBe(s1);
  });

  it("text 增量接续最后一个 text 气泡；空 delta 不产生变化", () => {
    let s = reduceChat(emptyChat(), { type: "text", delta: "你好" });
    s = reduceChat(s, { type: "text", delta: "，世界" });
    expect(s.items).toEqual([{ kind: "text", text: "你好，世界", t: expect.any(Number) }]);
    expect(reduceChat(s, { type: "text", delta: "" })).toBe(s);
  });

  it("tool_card 首推建卡+占位；后续按 id 合并 status/preview/files 去重", () => {
    let s = reduceChat(emptyChat(), {
      type: "tool_card", id: "c1", tool: "write_file",
      arguments: { file_path: "a.md" }, status: "running",
      result_preview: "", files: [],
    });
    expect(s.items).toEqual([{ kind: "tool", ref: "c1", t: expect.any(Number) }]);
    expect(s.cards.c1.status).toBe("running");

    s = reduceChat(s, {
      type: "tool_card", id: "c1", tool: "write_file", status: "done",
      result_preview: "ok", files: [{ path: "a.md" }, { path: "fig.png" }],
    });
    // 卡片合并在同一位置：items 不新增
    expect(s.items).toHaveLength(1);
    expect(s.cards.c1.status).toBe("done");
    expect(s.cards.c1.preview).toBe("ok");
    expect(s.cards.c1.files.map((f) => f.path)).toEqual(["a.md", "fig.png"]);

    // 重复文件不去重入
    s = reduceChat(s, {
      type: "tool_card", id: "c1", status: "done", files: [{ path: "fig.png" }],
    });
    expect(s.cards.c1.files).toHaveLength(2);
  });

  it("工具卡打断后 text 另起新气泡", () => {
    let s = reduceChat(emptyChat(), { type: "text", delta: "前" });
    s = reduceChat(s, { type: "tool_card", id: "c1", tool: "bash", status: "running" });
    s = reduceChat(s, { type: "text", delta: "后" });
    expect(s.items.map((i) => i.kind)).toEqual(["text", "tool", "text"]);
  });

  it("usage 更新 budget", () => {
    const s = reduceChat(emptyChat(), {
      type: "usage",
      budget: { total_cost_usd: 0.1, cost_cap_enforceable: true },
    });
    expect(s.budget).toEqual({ total_cost_usd: 0.1, cost_cap_enforceable: true });
  });

  it("approval_request 记录 120s 截止时间", () => {
    const before = Date.now();
    const s = reduceChat(emptyChat(), {
      type: "approval_request", id: "a1", tool: "bash", summary: "ls",
    });
    expect(s.approval!.id).toBe("a1");
    expect(s.approval!.deadline - before).toBeGreaterThanOrEqual(
      APPROVAL_TIMEOUT_S * 1000 - 50,
    );
  });

  it("result 收尾：phase=done、turns 回填、审批清空、stopReason 保留", () => {
    let s = reduceChat(emptyChat(), {
      type: "approval_request", id: "a1", tool: "x", summary: "",
    });
    s = reduceChat(s, { type: "result", stop_reason: "complete", turns: 3 });
    expect(s.phase).toBe("done");
    expect(s.turns).toBe(3);
    expect(s.stopReason).toBe("complete");
    expect(s.approval).toBeNull();
  });

  it("error 置错误态并清审批；done 在运行中收尾、空闲则原样返回", () => {
    let s = reduceChat(emptyChat(), { type: "error", message: "boom" });
    expect(s.phase).toBe("error");
    expect(s.error).toBe("boom");

    const idle = emptyChat();
    expect(reduceChat(idle, { type: "done" })).toBe(idle);

    let run = applyUserMessage(emptyChat(), "hi"); // 本地置 running
    run = reduceChat(run, { type: "done" });
    expect(run.phase).toBe("done");
  });

  it("未知帧型原样返回", () => {
    const s = emptyChat();
    expect(reduceChat(s, { type: "mystery" })).toBe(s);
  });
});

describe("本地动作", () => {
  it("applyUserMessage 空闲发送：重置回合状态并置 running", () => {
    let s = emptyChat();
    s = reduceChat(s, { type: "error", message: "旧错误" });
    s = applyUserMessage(s, "新问题");
    expect(s.phase).toBe("running");
    expect(s.error).toBeNull();
    expect(s.turns).toBe(0);
    expect(s.startedAt).not.toBeNull();
    expect(s.items[0]).toMatchObject({ kind: "user", text: "新问题", steer: false });
  });

  it("applyUserMessage 运行中发送：标记 steer 且不重置计时", () => {
    let s = applyUserMessage(emptyChat(), "第一问");
    const startedAt = s.startedAt;
    s = applyUserMessage(s, "补充一点");
    expect(s.items[1]).toMatchObject({ kind: "user", steer: true });
    expect(s.startedAt).toBe(startedAt);
    expect(applyUserMessage(s, "")).toBe(s);
  });

  it("applyApprovalResponse 清除当前审批", () => {
    let s = reduceChat(emptyChat(), {
      type: "approval_request", id: "a1", tool: "x", summary: "",
    });
    s = applyApprovalResponse(s);
    expect(s.approval).toBeNull();
  });
});

describe("historyToItems", () => {
  it("恢复历史为 user/text 气泡序列", () => {
    const items = historyToItems([
      { role: "user", content: "q" },
      { role: "assistant", content: "a" },
    ]);
    expect(items).toEqual([
      { kind: "user", text: "q", t: 0 },
      { kind: "text", text: "a", t: 0 },
    ]);
  });
});
