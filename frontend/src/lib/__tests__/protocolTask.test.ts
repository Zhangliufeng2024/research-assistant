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
