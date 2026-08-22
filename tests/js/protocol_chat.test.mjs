import test from "node:test";
import assert from "node:assert/strict";
import {
  emptyChat, applyUserMessage, applyApprovalResponse, reduceChat,
  chatBadgeClass, CHAT_PHASE_LABEL,
} from "../../research_assistant/web/static/js/protocol_chat.js";

test("emptyChat 初始形状", () => {
  const c = emptyChat();
  assert.equal(c.phase, "idle");
  assert.equal(c.sessionId, null);
  assert.deepEqual(c.items, []);
  assert.deepEqual(c.cards, {});
  assert.equal(c.approval, null);
});

test("applyUserMessage 进入 running 并入列 user 项", () => {
  const c = applyUserMessage(emptyChat(), "帮我看看 data 目录");
  assert.equal(c.phase, "running");
  assert.equal(c.items.length, 1);
  assert.equal(c.items[0].kind, "user");
  assert.equal(c.items[0].text, "帮我看看 data 目录");
  assert.equal(c.items[0].steer, false);
  assert.ok(c.startedAt > 0);
});

test("空文本不产生变化", () => {
  const s = emptyChat();
  assert.equal(applyUserMessage(s, ""), s);
});

test("文本增量拼接为同一气泡", () => {
  let c = applyUserMessage(emptyChat(), "hi");
  c = reduceChat(c, { type: "text", delta: "你" });
  c = reduceChat(c, { type: "text", delta: "好" });
  assert.equal(c.items.length, 2); // user + 一个 text 气泡
  assert.equal(c.items[1].kind, "text");
  assert.equal(c.items[1].text, "你好");
});

test("工具卡片打断后文本另起新气泡", () => {
  let c = applyUserMessage(emptyChat(), "q");
  c = reduceChat(c, { type: "text", delta: "先看" });
  c = reduceChat(c, { type: "tool_card", id: "t1", tool: "read_file", arguments: { path: "a.csv" }, status: "running" });
  c = reduceChat(c, { type: "text", delta: "再看" });
  assert.deepEqual(c.items.map((i) => i.kind), ["user", "text", "tool", "text"]);
  assert.equal(c.items[3].text, "再看");
});

test("同 id tool_card 合并：不重复占位、更新状态与预览", () => {
  let c = emptyChat();
  c = reduceChat(c, { type: "tool_card", id: "t1", tool: "run_python", arguments: { code: "..." } });
  c = reduceChat(c, { type: "tool_card", id: "t1", status: "done", result_preview: "图已生成" });
  assert.equal(c.items.length, 1);
  assert.equal(c.items[0].kind, "tool");
  assert.equal(c.cards.t1.status, "done");
  assert.equal(c.cards.t1.preview, "图已生成");
  assert.equal(c.cards.t1.tool, "run_python"); // 首见字段保留
});

test("files 按 path 去重合并", () => {
  let c = emptyChat();
  c = reduceChat(c, { type: "tool_card", id: "t1", tool: "run_python", files: [{ path: "figures/f.png" }] });
  c = reduceChat(c, { type: "tool_card", id: "t1", status: "done", files: [{ path: "figures/f.png" }, { path: "out.docx" }] });
  assert.deepEqual(c.cards.t1.files.map((f) => f.path), ["figures/f.png", "out.docx"]);
});

test("approval_request 设置 ~120s 截止，回应后清除", () => {
  let c = emptyChat();
  const before = Date.now();
  c = reduceChat(c, { type: "approval_request", id: "ap1", tool: "bash", summary: "rm -rf tmp" });
  assert.ok(c.approval.deadline - before >= 119_000 && c.approval.deadline - before <= 121_000);
  c = applyApprovalResponse(c);
  assert.equal(c.approval, null);
});

test("usage 写入 budget；无 budget 返回原引用", () => {
  const s = applyUserMessage(emptyChat(), "q");
  assert.equal(reduceChat(s, { type: "usage" }), s);
  const c = reduceChat(s, { type: "usage", budget: { cost_usd: 0.5 } });
  assert.equal(c.budget.cost_usd, 0.5);
});

test("result 收尾：done + turns + stop_reason，审批清空", () => {
  let c = applyUserMessage(emptyChat(), "q");
  c = reduceChat(c, { type: "approval_request", id: "a", tool: "bash" });
  c = reduceChat(c, { type: "result", stop_reason: "end_turn", turns: 4 });
  assert.equal(c.phase, "done");
  assert.equal(c.turns, 4);
  assert.equal(c.stopReason, "end_turn");
  assert.equal(c.approval, null);
  assert.ok(c.finishedAt >= c.startedAt);
});

test("error 置错误态并清审批", () => {
  let c = applyUserMessage(emptyChat(), "q");
  c = reduceChat(c, { type: "error", message: "预算耗尽" });
  assert.equal(c.phase, "error");
  assert.equal(c.error, "预算耗尽");
});

test("done 仅把 running 推到 done；未知类型与 connected 无变化时返回原引用", () => {
  let c = applyUserMessage(emptyChat(), "q");
  assert.notEqual(reduceChat(c, { type: "done" }), c);
  assert.equal(reduceChat(c, { type: "done" }).phase, "done");

  const idle = emptyChat();
  assert.equal(reduceChat(idle, { type: "mystery" }), idle);
  assert.equal(reduceChat(idle, { type: "connected" }), idle);
  const bound = reduceChat(idle, { type: "connected", session_id: "s1" });
  assert.equal(bound.sessionId, "s1");
  assert.equal(bound.phase, "idle"); // connected 本身不启动回合
});

test("运行中发言标记为 steer 且保留回合起点", () => {
  let c = applyUserMessage(emptyChat(), "开始整理");
  const started = c.startedAt;
  c = reduceChat(c, { type: "text", delta: "好的" });
  c = applyUserMessage(c, "改成英文");
  const steerItem = c.items[c.items.length - 1];
  assert.equal(steerItem.steer, true);
  assert.equal(c.startedAt, started);
  assert.equal(c.phase, "running");
});

test("徽标映射与阶段标签完备", () => {
  assert.equal(chatBadgeClass("running"), "b-run");
  assert.equal(chatBadgeClass("done"), "b-ok");
  assert.equal(chatBadgeClass("error"), "b-err");
  assert.equal(chatBadgeClass("idle"), "");
  for (const p of ["idle", "running", "done", "error"]) assert.ok(CHAT_PHASE_LABEL[p]);
});
