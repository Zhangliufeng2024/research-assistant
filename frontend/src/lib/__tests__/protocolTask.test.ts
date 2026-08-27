import { describe, expect, it } from "vitest";
import { ACTIVITY_CAP, emptyTask, reduceTask } from "../protocolTask";

describe("reduceTask", () => {
  it("connected 置 running 并记录 taskId/startedAt", () => {
    const s = reduceTask(emptyTask(), { type: "connected", task_id: "t1" });
    expect(s.phase).toBe("running");
    expect(s.taskId).toBe("t1");
    expect(s.startedAt).not.toBeNull();
  });

  it("progress 推进时间轴：research 并行激活 figures，且只前进不回退", () => {
    let t = reduceTask(emptyTask(), { type: "progress", stage: "planning" });
    expect(t.timeline[0]).toBe("active");
    t = reduceTask(t, { type: "progress", stage: "research" });
    expect(t.timeline[1]).toBe("active");
    expect(t.timeline[2]).toBe("active"); // 图表并行
    // 回到 compilation(6) 正常前进
    t = reduceTask(t, { type: "progress", stage: "compilation" });
    expect(t.timeline[6]).toBe("active");
    // 不从 6 退回 3
    t = reduceTask(t, { type: "progress", stage: "writing", message: "写作中" });
    expect(t.timeline[6]).toBe("active");
    expect(t.timeline[3]).not.toBe("active");
  });

  it("消息文本细分阶段：质量门→4、修订→5（refineIdx 只前进）", () => {
    let t = reduceTask(emptyTask(), { type: "progress", stage: "planning" });
    t = reduceTask(t, { type: "progress", message: "运行质量门检查" });
    expect(t.timeline.lastIndexOf("active")).toBeGreaterThanOrEqual(4);
  });

  it("stage=cancelled 直接收束为 cancelled", () => {
    const t = reduceTask(emptyTask(), {
      type: "progress", stage: "cancelled", message: "任务已停止",
    });
    expect(t.phase).toBe("cancelled");
  });

  it("result 成功：timeline 全 done、result 帧、审批清空；failed：error 汇总", () => {
    const ok = reduceTask(emptyTask(), {
      type: "result", status: "complete", metadata: { title: "测试论文" },
    });
    expect(ok.phase).toBe("done");
    expect(ok.timeline.every((x) => x === "done")).toBe(true);
    expect(ok.approval).toBeNull();

    const bad = reduceTask(emptyTask(), {
      type: "result", status: "failed", errors: ["编译失败"],
    });
    expect(bad.phase).toBe("failed");
    expect(bad.error).toContain("编译失败");
  });

  it("approval_request 记录待办 + activity 警示；steer_ok 记录 info", () => {
    let t = reduceTask(emptyTask(), {
      type: "approval_request", id: "a1", tool: "bash", summary: "rm",
    });
    expect(t.approval!.id).toBe("a1");
    expect(t.activity.at(-1)!.kind).toBe("warn");
    t = reduceTask(t, { type: "steer_ok" });
    expect(t.activity.at(-1)!.kind).toBe("info");
  });

  it("text 帧入活动流（带 content）；activity 上限 ACTIVITY_CAP 截断", () => {
    let t = reduceTask(emptyTask(), { type: "text", content: "模型输出片段" });
    expect(t.activity[0]).toMatchObject({ kind: "text", content: "模型输出片段" });
    for (let i = 0; i < ACTIVITY_CAP + 20; i++) {
      t = reduceTask(t, { type: "text", content: `x${i}` });
    }
    expect(t.activity.length).toBe(ACTIVITY_CAP);
  });
});

/* ---------- 克隆契约（R13-K）：无可观测变化返回原引用 ---------- */
describe("reduceTask 克隆契约（R13-K）", () => {
  it("未知帧型返回原引用（高频无关帧不触发重绘）", () => {
    const s = emptyTask();
    expect(reduceTask(s, { type: "mystery" })).toBe(s);
    expect(reduceTask(s, {} as never)).toBe(s);
  });

  it("空 usage / 空白 text 返回原引用", () => {
    const s = emptyTask();
    expect(reduceTask(s, { type: "usage" })).toBe(s);
    expect(reduceTask(s, { type: "usage", budget: null })).toBe(s);
    expect(reduceTask(s, { type: "text" })).toBe(s);
    expect(reduceTask(s, { type: "text", content: "   " })).toBe(s);
  });

  it("有预算的 usage / 非空白 text 才产生新引用", () => {
    const s = emptyTask();
    const withBudget = reduceTask(s, { type: "usage", budget: { cost_usd: 1 } });
    expect(withBudget).not.toBe(s);
    expect(withBudget.budget).toEqual({ cost_usd: 1 });
    const withText = reduceTask(s, { type: "text", content: "输出" });
    expect(withText).not.toBe(s);
  });

  it("已收束后的重复 done 返回原引用；首个 done 正常收束", () => {
    let t = reduceTask(emptyTask(), { type: "connected" });
    const first = reduceTask(t, { type: "done" });
    expect(first.phase).toBe("done");
    expect(first.finishedAt).not.toBeNull();
    expect(reduceTask(first, { type: "done" })).toBe(first);
    // idle 态收到 done：finishedAt 未记 → 补记并出新引用
    const idleDone = reduceTask(emptyTask(), { type: "done" });
    expect(idleDone.finishedAt).not.toBeNull();
  });

  it("入参不被修改（timeline/tlNote/activity 均为新容器或整体替换）", () => {
    const base = reduceTask(emptyTask(), { type: "progress", stage: "planning" });
    const snapshot = JSON.stringify(base);
    reduceTask(base, { type: "progress", stage: "research" });
    reduceTask(base, { type: "approval_request", id: "a", tool: "bash" });
    expect(JSON.stringify(base)).toBe(snapshot);
  });
});
