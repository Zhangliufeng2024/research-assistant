/* R17 会话时间分组单测：分组边界（跨午夜/跨周）+ pinned 独立成组 + 空组剔除。 */
import { describe, expect, it } from "vitest";
import {
  dayAndWeekStart,
  groupSessions,
  sessionTimeMs,
} from "@/components/chat/sessionGroups";
import type { SessionSummary } from "@/lib/types";

function s(id: string, updatedMs: number, pinned = false): SessionSummary {
  return {
    id,
    title: id,
    last_message: "",
    turns: 1,
    created_at: updatedMs / 1000,
    updated_at: updatedMs / 1000,
    pinned,
  };
}

// 固定参照时刻：2026-08-28（周五）15:00 本地
const NOW = new Date(2026, 7, 28, 15, 0, 0).getTime();

describe("sessionTimeMs", () => {
  it("秒级 epoch 转毫秒", () => {
    expect(sessionTimeMs(1_700_000_000)).toBe(1_700_000_000_000);
  });
  it("已是毫秒的数值原样", () => {
    expect(sessionTimeMs(1_700_000_000_000)).toBe(1_700_000_000_000);
  });
  it("ISO 字符串解析", () => {
    expect(sessionTimeMs("2026-08-28T10:00:00")).toBe(
      new Date(2026, 7, 28, 10, 0, 0).getTime(),
    );
  });
  it("非法字符串归 0", () => {
    expect(sessionTimeMs("not-a-date")).toBe(0);
  });
});

describe("groupSessions", () => {
  it("置顶独立成组且在最前", () => {
    const groups = groupSessions(
      [s("a", NOW - 1000), s("b", NOW - 9 * 86_400_000, true)],
      NOW,
    );
    expect(groups[0]!.key).toBe("pinned");
    expect(groups[0]!.items.map((x) => x.id)).toEqual(["b"]);
    expect(groups[1]!.key).toBe("today");
  });

  it("今天/本周/更早的边界（跨午夜）", () => {
    const { dayStart, weekStart } = dayAndWeekStart(NOW);
    const groups = groupSessions(
      [
        s("today", dayStart + 1000),
        s("this-week", dayStart - 1000), // 昨天 23:59:59 → 本周（同在周内）
        s("earlier", weekStart - 1000), // 上周日 23:59:59 → 更早
      ],
      NOW,
    );
    const byKey = Object.fromEntries(groups.map((g) => [g.key, g.items.map((x) => x.id)]));
    expect(byKey["today"]).toEqual(["today"]);
    expect(byKey["week"]).toEqual(["this-week"]);
    expect(byKey["earlier"]).toEqual(["earlier"]);
  });

  it("空组不产出", () => {
    const groups = groupSessions([s("a", NOW - 1000)], NOW);
    expect(groups.map((g) => g.key)).toEqual(["today"]);
  });

  it("保持输入顺序（不重排）", () => {
    const groups = groupSessions(
      [s("new", NOW - 500), s("old", NOW - 1500)],
      NOW,
    );
    expect(groups[0]!.items.map((x) => x.id)).toEqual(["new", "old"]);
  });
});
