/* 方案 1 / 方案 4 前端归约测试：command 帧与 plan_proposal 帧进 ChatState、
 * result 帧收场清理 Plan 门。纯函数直测，不起 WS。 */
import { describe, expect, it } from "vitest";
import { PLAN_DECISION_TIMEOUT_S, emptyChat, reduceChat } from "@/lib/protocolChat";
import { commandSuggestions, parseCommand } from "@/lib/commands";

describe("slash 命令下拉建议（方案 4 前端）", () => {
  it("裸 / 列出全部命令", () => {
    expect(commandSuggestions("/")).toHaveLength(6);
  });

  it("前缀过滤且大小写不敏感", () => {
    expect(commandSuggestions("/B").map((c) => c.name)).toEqual(["budget"]);
    expect(commandSuggestions("/p").map((c) => c.name)).toEqual(["plan"]);
  });

  it("完整命令名仍提示（回车即选），带空格后不再提示", () => {
    expect(commandSuggestions("/help").map((c) => c.name)).toEqual(["help"]);
    expect(commandSuggestions("/help ")).toEqual([]);
  });

  it("普通文本与多行输入不弹菜单", () => {
    expect(commandSuggestions("hello /h")).toEqual([]);
    expect(commandSuggestions("画个图")).toEqual([]);
  });
});

describe("本地命令错误渲染路径的解析输入", () => {
  it("未知命令带 error 文案（chatStore 据此本地渲染）", () => {
    expect(parseCommand("/foo bar").error).toContain("Unknown command");
  });

  it("budget 非法键/非法值带 error 文案", () => {
    expect(parseCommand("/budget foo=1").error).toContain("Unknown budget key");
    expect(parseCommand("/budget cost=abc").error).toContain("positive number");
  });

  it("合法命令无 error", () => {
    expect(parseCommand("/budget tokens=100").error).toBeUndefined();
    expect(parseCommand("/role planner").error).toBeUndefined();
  });
});

describe("command 帧归约（方案 4）", () => {
  it("raw + message 分别渲染成用户气泡与助手文本", () => {
    let c = emptyChat();
    c = reduceChat(c, {
      type: "command",
      raw: "/help",
      message: "可用命令：…",
    } as never);
    expect(c.items).toHaveLength(2);
    expect(c.items[0]).toMatchObject({ kind: "user", text: "/help" });
    expect(c.items[1]).toMatchObject({ kind: "text", text: "可用命令：…" });
  });

  it("空帧原引用返回（订阅方跳过重绘）", () => {
    const c = emptyChat();
    expect(reduceChat(c, { type: "command" } as never)).toBe(c);
  });

  it("命令不改变相位", () => {
    let c = emptyChat();
    c = reduceChat(c, { type: "command", raw: "/x", message: "y" } as never);
    expect(c.phase).toBe("idle");
  });
});

describe("plan_proposal 归约与收场（方案 1）", () => {
  it("plan_proposal 写入待决计划，deadline 按 600s 口径", () => {
    let c = emptyChat();
    c = reduceChat(c, { type: "plan_proposal", id: "p1", plan: "1. 先读数据" } as never);
    expect(c.plan).not.toBeNull();
    expect(c.plan!.id).toBe("p1");
    expect(c.plan!.plan).toBe("1. 先读数据");
    const delta = c.plan!.deadline - Date.now();
    expect(delta).toBeGreaterThan((PLAN_DECISION_TIMEOUT_S - 5) * 1000);
    expect(delta).toBeLessThanOrEqual(PLAN_DECISION_TIMEOUT_S * 1000);
  });

  it("result 帧清除待决计划（批准执行完/拒绝/超时统一收场）", () => {
    let c = emptyChat();
    c = reduceChat(c, { type: "plan_proposal", id: "p1", plan: "x" } as never);
    c = reduceChat(c, { type: "result", stop_reason: "cancelled", turns: 0 } as never);
    expect(c.plan).toBeNull();
  });

  it("无 id 的 plan_proposal 原引用返回", () => {
    const c = emptyChat();
    expect(reduceChat(c, { type: "plan_proposal" } as never)).toBe(c);
  });

  it("emptyChat 初始 plan 为 null", () => {
    expect(emptyChat().plan).toBeNull();
  });
});
