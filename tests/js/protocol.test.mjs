/* protocol.js 纯函数测试（node --test tests/js/） */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  emptyTask, reduceTask, TL_STAGES, APPROVAL_TIMEOUT_S, runBadgeClass,
} from "../../research_assistant/web/static/js/protocol.js";

const P = (stage, message) => ({ type: "progress", stage, message });

test("emptyTask 形状：7 阶段全 pending", () => {
  const t = emptyTask();
  assert.equal(t.phase, "idle");
  assert.equal(t.timeline.length, TL_STAGES.length);
  assert.ok(t.timeline.every((s) => s === "pending"));
});

test("planning 激活规划阶段", () => {
  const t = reduceTask(emptyTask(), P("planning", "开始规划"));
  assert.equal(t.timeline[0], "active");
  assert.equal(t.phase, "running");
});

test("research 并行激活研究与图表", () => {
  const t = reduceTask(emptyTask(), P("research", "并行检索"));
  assert.equal(t.timeline[1], "active");
  assert.equal(t.timeline[2], "active"); // figures
});

test("writing 将研究/图表置为完成并激活组装", () => {
  let t = reduceTask(emptyTask(), P("research", ""));
  t = reduceTask(t, P("writing", "开始组装"));
  assert.deepEqual(t.timeline.slice(0, 4), ["done", "done", "done", "active"]);
});

test("compilation 激活定稿", () => {
  let t = reduceTask(emptyTask(), P("writing", ""));
  t = reduceTask(t, P("compilation", "定稿中"));
  assert.equal(t.timeline[6], "active");
});

test("complete 全部置为完成", () => {
  let t = reduceTask(emptyTask(), P("planning", ""));
  t = reduceTask(t, P("complete", "完成"));
  assert.ok(t.timeline.every((s) => s === "done"));
});

test("消息文本中的质量门/修订关键词推进时间轴（只前进）", () => {
  let t = reduceTask(emptyTask(), P("writing", "组装中"));
  t = reduceTask(t, P("writing", "质量门未通过，启动修订"));
  assert.equal(t.timeline[4], "active"); // gates
  t = reduceTask(t, P("writing", "修订轮 1/3"));
  assert.equal(t.timeline[5], "active"); // revision
});

test("时间轴不回退：定稿后收到 writing 不回退到组装", () => {
  let t = reduceTask(emptyTask(), P("compilation", ""));
  t = reduceTask(t, P("writing", "迟到的写作消息"));
  assert.equal(t.timeline[6], "active");
  assert.notEqual(t.timeline[3], "active");
});

test("text 消息进入活动流并保留全文", () => {
  const t = reduceTask(emptyTask(), { type: "text", content: "分析数据中…".repeat(30) });
  const last = t.activity.at(-1);
  assert.equal(last.kind, "text");
  assert.ok(last.content.includes("分析数据中"));
});

test("usage 更新预算快照", () => {
  const t = reduceTask(emptyTask(), {
    type: "usage",
    budget: { cost_usd: 0.42, total_tokens: 38000, turns: 12 },
  });
  assert.equal(t.budget.cost_usd, 0.42);
  assert.equal(t.budget.turns, 12);
});

test("approval_request 设置审批与截止时间", () => {
  const before = Date.now();
  const t = reduceTask(emptyTask(), { type: "approval_request", id: "t1", tool: "bash", summary: "rm -rf /" });
  assert.equal(t.approval.id, "t1");
  assert.ok(t.approval.deadline - before >= (APPROVAL_TIMEOUT_S - 1) * 1000);
});

test("result 失败：phase=failed 且带错误；成功：全阶段完成", () => {
  const bad = reduceTask(emptyTask(), { type: "result", status: "failed", errors: ["gate"] });
  assert.equal(bad.phase, "failed");
  assert.match(bad.error, /gate/);

  const good = reduceTask(emptyTask(), {
    type: "result", status: "success", paper_name: "p",
    metadata: { title: "T" }, files: {},
  });
  assert.equal(good.phase, "done");
  assert.ok(good.timeline.every((s) => s === "done"));
});

test("error 与 cancelled 终态", () => {
  assert.equal(reduceTask(emptyTask(), { type: "error", message: "boom" }).phase, "error");
  const c = reduceTask(emptyTask(), P("cancelled", "任务已停止"));
  assert.equal(c.phase, "cancelled");
});

test("活动流容量封顶", async () => {
  const { ACTIVITY_CAP } = await import("../../research_assistant/web/static/js/protocol.js");
  let t = emptyTask();
  for (let i = 0; i < ACTIVITY_CAP + 50; i++) t = reduceTask(t, P("", `m${i}`));
  assert.equal(t.activity.length, ACTIVITY_CAP);
});

test("runBadgeClass 映射", () => {
  assert.equal(runBadgeClass("running"), "b-run");
  assert.equal(runBadgeClass("unknown"), "");
});
