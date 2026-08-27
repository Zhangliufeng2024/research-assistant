/* 全局搜索交互模型（R15 键盘层）：深链映射、↑↓ 高亮移动、Enter 选择判定。
 */
import { describe, expect, it } from "vitest";
import {
  moveHighlight,
  pickEnterIndex,
  SEARCH_KIND_LABELS,
  searchHitPath,
  type SearchHit,
} from "@/components/layout/workspaceSearchModel";

const hit = (kind: string, id = "x1"): SearchHit => ({ kind, id });

describe("searchHitPath（深链映射：收敛后仍直达成员页）", () => {
  it("线程直达详情页 /threads/:id", () => {
    expect(searchHitPath({ kind: "thread", id: "t-9" })).toBe("/threads/t-9");
  });

  it("其余类别落到对应成员页", () => {
    expect(searchHitPath(hit("task"))).toBe("/tasks");
    expect(searchHitPath(hit("source"))).toBe("/sources");
    expect(searchHitPath(hit("artifact"))).toBe("/artifacts");
    expect(searchHitPath(hit("research_item"))).toBe("/research");
    expect(searchHitPath(hit("claim"))).toBe("/research");
    expect(searchHitPath(hit("decision"))).toBe("/research");
  });

  it("未知类别兜底到研究工作台", () => {
    expect(searchHitPath(hit("mystery"))).toBe("/research");
  });

  it("分类标签覆盖服务端已知 kind", () => {
    for (const k of ["thread", "task", "source", "research_item", "claim", "decision", "artifact"]) {
      expect(SEARCH_KIND_LABELS[k]).toBeTruthy();
    }
  });
});

describe("moveHighlight（↑↓ 循环滚动）", () => {
  it("中间区域 ±1 平移", () => {
    expect(moveHighlight(1, 1, 5)).toBe(2);
    expect(moveHighlight(2, -1, 5)).toBe(1);
  });

  it("末条 ↓ 回首条；首条 ↑ 到末条", () => {
    expect(moveHighlight(4, 1, 5)).toBe(0);
    expect(moveHighlight(0, -1, 5)).toBe(4);
  });

  it("单条候选时原地不动（循环到自己）", () => {
    expect(moveHighlight(0, 1, 1)).toBe(0);
    expect(moveHighlight(0, -1, 1)).toBe(0);
  });

  it("无候选维持 -1（无高亮态）", () => {
    expect(moveHighlight(-1, 1, 0)).toBe(-1);
    expect(moveHighlight(-1, -1, 0)).toBe(-1);
  });
});

describe("pickEnterIndex（Enter 不误触）", () => {
  it("有高亮且在界内：返回该索引", () => {
    expect(pickEnterIndex(0, 3)).toBe(0);
    expect(pickEnterIndex(2, 3)).toBe(2);
  });

  it("空结果 / 输入中（length=0）：null，不关闭不导航", () => {
    expect(pickEnterIndex(0, 0)).toBeNull();
    expect(pickEnterIndex(-1, 0)).toBeNull();
  });

  it("越界高亮（候选刷新后残留索引）：null", () => {
    expect(pickEnterIndex(5, 3)).toBeNull();
    expect(pickEnterIndex(-1, 3)).toBeNull();
  });
});
