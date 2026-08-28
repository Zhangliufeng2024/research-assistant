/* 方案 2b：lib/diff.ts 行级 LCS diff 的纯函数测试。 */
import { describe, expect, it } from "vitest";
import { diffLines, diffStats } from "@/lib/diff";

const types = (rows: { type: string }[]) => rows.map((r) => r.type).join(",");
const texts = (rows: { text: string }[]) => rows.map((r) => r.text);

describe("diffLines（方案 2b）", () => {
  it("相同文本 → 全部上下文行，无增删", () => {
    const rows = diffLines("a\nb\nc", "a\nb\nc");
    expect(types(rows)).toBe("ctx,ctx,ctx");
    expect(diffStats(rows)).toEqual({ added: 0, removed: 0 });
  });

  it("纯追加：尾部新行标记为 add", () => {
    const rows = diffLines("a\nb", "a\nb\nc\nd");
    expect(types(rows)).toBe("ctx,ctx,add,add");
    expect(texts(rows).slice(2)).toEqual(["c", "d"]);
  });

  it("纯删除：被删行标记为 del", () => {
    const rows = diffLines("a\nb\nc", "a");
    expect(types(rows)).toBe("ctx,del,del");
  });

  it("中段替换：LCS 保住公共行，先删后加", () => {
    const rows = diffLines("head\nold1\nold2\ntail", "head\nnew1\ntail");
    expect(types(rows)).toBe("ctx,del,del,add,ctx");
    expect(texts(rows)).toEqual(["head", "old1", "old2", "new1", "tail"]);
  });

  it("中段公共行不重复输出（LCS 语义）", () => {
    // "keep" 同时出现在新旧中段，应作为 ctx 保留一次而非 删+加
    const rows = diffLines("x\nkeep\ny", "x\nkeep\nz");
    const ctxKeeps = rows.filter((r) => r.type === "ctx" && r.text === "keep");
    expect(ctxKeeps).toHaveLength(1);
    expect(types(rows)).toBe("ctx,ctx,del,add");
  });

  it("空串 ↔ 文本：全量 add", () => {
    const rows = diffLines("", "a\nb");
    expect(types(rows)).toBe("add,add");
    expect(diffStats(rows)).toEqual({ added: 2, removed: 0 });
  });

  it("多行块整体位移识别为删+加（保守正确）", () => {
    const rows = diffLines("1\n2\n3", "3\n1\n2");
    expect(diffStats(rows).added + diffStats(rows).removed).toBeGreaterThan(0);
    // 首尾公共修剪后 3 既是旧尾又是新首：两端对称时保守处理即可，
    // 但结果必须仍是合法的行序列（三类行拼接可还原新文本）
    const rebuilt = rows
      .filter((r) => r.type !== "del")
      .map((r) => r.text)
      .join("\n");
    expect(rebuilt).toBe("3\n1\n2");
  });

  it("超大中段退化保护：不炸内存且删加齐全", () => {
    const oldText = Array.from({ length: 3000 }, (_, i) => `old-${i}`).join("\n");
    const newText = Array.from({ length: 3000 }, (_, i) => `new-${i}`).join("\n");
    const rows = diffLines(oldText, newText);
    const { added, removed } = diffStats(rows);
    expect(added).toBe(3000);
    expect(removed).toBe(3000);
  });

  it("重建语义：非删除行拼接 = 新文本；非新增行拼接 = 旧文本", () => {
    const a = "function f() {\n  return 1;\n}\n";
    const b = "function f() {\n  return 2;\n  // done\n}\n";
    const rows = diffLines(a, b);
    expect(
      rows.filter((r) => r.type !== "del").map((r) => r.text).join("\n"),
    ).toBe(b);
    expect(
      rows.filter((r) => r.type !== "add").map((r) => r.text).join("\n"),
    ).toBe(a);
  });
});

describe("diffStats", () => {
  it("只统计 add/del，忽略 ctx", () => {
    expect(
      diffStats([
        { type: "ctx", text: "a" },
        { type: "add", text: "b" },
        { type: "add", text: "c" },
        { type: "del", text: "d" },
      ]),
    ).toEqual({ added: 2, removed: 1 });
  });
});
