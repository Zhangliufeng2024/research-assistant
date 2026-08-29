/* 命令面板匹配模型（paletteModel）：fuse.js 过滤的纯逻辑单测（node 环境）。 */
import { describe, expect, it } from "vitest";
import { filterItems } from "@/components/layout/paletteModel";

const items = [
  { id: "1", title: "新建会话" },
  { id: "2", title: "打开设置" },
  { id: "3", title: "Foo", detail: "会话归档说明" },
];

describe("filterItems", () => {
  it("空查询原样返回全部条目", () => {
    expect(filterItems(items, "")).toHaveLength(3);
    expect(filterItems(items, "   ")).toHaveLength(3);
  });

  it("标题子串命中并保持命中项", () => {
    const r = filterItems(items, "设置");
    expect(r).toHaveLength(1);
    expect(r[0]!.id).toBe("2");
  });

  it("detail 参与匹配", () => {
    const r = filterItems(items, "归档");
    expect(r.some((i) => i.id === "3")).toBe(true);
  });

  it("无命中返回空数组", () => {
    expect(filterItems(items, "完全不相关的查询词")).toHaveLength(0);
  });
});
