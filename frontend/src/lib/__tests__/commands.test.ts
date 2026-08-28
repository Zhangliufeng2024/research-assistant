import { describe, expect, it } from "vitest";
import {
  COMMAND_CATALOG,
  formatHelp,
  isCommand,
  parseCommand,
} from "@/lib/commands";

describe("isCommand", () => {
  it("以 / 加非空字符判定为命令", () => {
    expect(isCommand("/budget cost=5")).toBe(true);
    expect(isCommand("  /help")).toBe(true);
    expect(isCommand("hello")).toBe(false);
    expect(isCommand("/")).toBe(false);
    expect(isCommand("/ ")).toBe(false);
  });
});

describe("parseCommand.budget", () => {
  it("解析键值对", () => {
    const r = parseCommand("/budget cost=50 tokens=100000 turns=50 wall_seconds=600");
    expect(r.kind).toBe("budget");
    expect(r.args).toEqual({ cost: "50", tokens: "100000", turns: "50", wall_seconds: "600" });
    expect(r.error).toBeUndefined();
  });

  it("拒绝非法 key", () => {
    expect(parseCommand("/budget cost=5 foo=bar").error).toMatch(/Unknown budget key/);
  });

  it("拒绝非正数", () => {
    expect(parseCommand("/budget cost=0").error).toMatch(/positive number/);
    expect(parseCommand("/budget tokens=abc").error).toMatch(/positive number/);
  });

  it("拒绝 positional arg", () => {
    expect(parseCommand("/budget 5").error).toMatch(/key=value/);
  });
});

describe("parseCommand.role/model/skill", () => {
  it("role 取单词为 value", () => {
    expect(parseCommand("/role planner").args).toEqual({ value: "planner" });
    expect(parseCommand("/role planner").kind).toBe("role");
  });

  it("model 取单词为 value", () => {
    expect(parseCommand("/model gpt-4o").args).toEqual({ value: "gpt-4o" });
    expect(parseCommand("/model gpt-4o").kind).toBe("model");
  });

  it("skill 取单词为 value", () => {
    expect(parseCommand("/skill scientific-writing").args).toEqual({ value: "scientific-writing" });
  });

  it("未带 arg 的 role 返回空 args（让下游提示）", () => {
    expect(parseCommand("/role").args).toEqual({});
  });
});

describe("parseCommand.plan/help", () => {
  it("/plan", () => {
    expect(parseCommand("/plan")).toEqual({ raw: "/plan", name: "plan", kind: "plan", args: {} });
  });
  it("/help", () => {
    expect(parseCommand("/help").kind).toBe("help");
  });
});

describe("parseCommand.unknown", () => {
  it("未知命令带 error 且透传 name", () => {
    const r = parseCommand("/xyz foo=1");
    expect(r.kind).toBe("unknown");
    expect(r.name).toBe("xyz");
    expect(r.error).toMatch(/Unknown command/);
  });

  it("非命令文本返回 not a command", () => {
    expect(parseCommand("hi").kind).toBe("unknown");
    expect(parseCommand("hi").error).toBe("not a command");
  });
});

describe("formatHelp & catalog", () => {
  it("每个 catalog 项完整", () => {
    for (const c of COMMAND_CATALOG) {
      expect(c.name).toBeTruthy();
      expect(c.description).toBeTruthy();
      expect(c.usage).toBeTruthy();
    }
    const names = COMMAND_CATALOG.map((c) => c.name);
    expect(new Set(names).size).toBe(names.length);
  });

  it("formatHelp 列出所有命令", () => {
    const help = formatHelp();
    for (const c of COMMAND_CATALOG) expect(help).toContain(`/${c.name}`);
  });
});
