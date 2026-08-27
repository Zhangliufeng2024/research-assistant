/* Top10-A 会话搜索纯函数回归：filterSessions / sessionDisplayTitle。 */
import { describe, expect, it } from "vitest";
import {
  filterSessions,
  sessionDisplayTitle,
} from "@/components/chat/sessionSearch";
import type { SessionSummary } from "@/lib/types";

function s(partial: Partial<SessionSummary> & { id: string }): SessionSummary {
  return {
    title: null,
    last_message: "",
    turns: 0,
    created_at: 1000,
    updated_at: 2000,
    ...partial,
  };
}

const FIXTURES: SessionSummary[] = [
  s({ id: "a", title: "量子计算综述", last_message: "最新回复" }),
  s({ id: "b", title: "LCA Carbon Footprint", last_message: "done" }),
  s({ id: "c", title: null, last_message: "帮我画一张碳流图" }),
  s({ id: "d", title: "   ", last_message: "空白标题回退首条消息" }),
];

describe("sessionDisplayTitle：与列表渲染同源的展示标题", () => {
  it("title 优先", () => {
    expect(sessionDisplayTitle(FIXTURES[0]!)).toBe("量子计算综述");
  });

  it("title 为空/纯空白时回退 last_message 切片口径（sessionTitle）", () => {
    expect(sessionDisplayTitle(FIXTURES[2]!)).toBe("帮我画一张碳流图");
    expect(sessionDisplayTitle(FIXTURES[3]!)).toBe("空白标题回退首条消息");
    expect(
      sessionDisplayTitle(s({ id: "e", title: null, last_message: "" })),
    ).toBe("未命名会话");
  });
});

describe("filterSessions：不区分大小写子串匹配", () => {
  it("空串不过滤，返回全部（新数组）", () => {
    const out = filterSessions(FIXTURES, "");
    expect(out).toHaveLength(4);
    expect(out).not.toBe(FIXTURES); // 纯函数：返回副本
  });

  it("纯空白查询等价于空串", () => {
    expect(filterSessions(FIXTURES, "   ")).toHaveLength(4);
  });

  it("大小写不敏感（拉丁字母）", () => {
    expect(filterSessions(FIXTURES, "lca").map((x) => x.id)).toEqual(["b"]);
    expect(filterSessions(FIXTURES, "CARBON").map((x) => x.id)).toEqual(["b"]);
  });

  it("CJK 子串命中", () => {
    expect(filterSessions(FIXTURES, "量子").map((x) => x.id)).toEqual(["a"]);
    // 命中回退标题（last_message），不只是 title 字段
    expect(filterSessions(FIXTURES, "碳流图").map((x) => x.id)).toEqual(["c"]);
  });

  it("无命中返回空数组", () => {
    expect(filterSessions(FIXTURES, "不存在的关键词xyz")).toEqual([]);
  });

  it("前后空白被 trim 后仍能命中", () => {
    expect(filterSessions(FIXTURES, "  量子  ").map((x) => x.id)).toEqual(["a"]);
  });
});
