/* R17 会话时间分组（纯函数，便于 node 单测）。
 *
 * 分组规则：置顶 → 今天 → 本周 → 更早。输入列表应已按
 * 「pinned 优先，组内 updated_at 倒序」排好（服务端 list_sessions 的
 * 输出即此口径）；本模块只做稳定分段，不重排。
 */

import type { SessionSummary } from "@/lib/types";

export interface SessionGroup {
  key: "pinned" | "today" | "week" | "earlier";
  label: string;
  items: SessionSummary[];
}

const DAY_MS = 86_400_000;

/** updated_at 兼容 number（epoch 秒）与 string（ISO）两种口径。 */
export function sessionTimeMs(value: number | string): number {
  if (typeof value === "number") {
    // 秒级 epoch（后端 time.time()）→ ms；已是 ms 的超大值原样
    return value < 1e12 ? value * 1000 : value;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** 本地日历日起点（今天 00:00）与本周起点（周一 00:00）。 */
export function dayAndWeekStart(now: number): { dayStart: number; weekStart: number } {
  const d = new Date(now);
  d.setHours(0, 0, 0, 0);
  const dayStart = d.getTime();
  // 周一为一周起点：getDay() 周日=0 … 周六=6
  const dow = (d.getDay() + 6) % 7;
  return { dayStart, weekStart: dayStart - dow * DAY_MS };
}

/** 把已排序会话分入时间段组；空组不产出。 */
export function groupSessions(
  sessions: SessionSummary[],
  now: number = Date.now(),
): SessionGroup[] {
  const { dayStart, weekStart } = dayAndWeekStart(now);
  const groups: SessionGroup[] = [
    { key: "pinned", label: "置顶", items: [] },
    { key: "today", label: "今天", items: [] },
    { key: "week", label: "本周", items: [] },
    { key: "earlier", label: "更早", items: [] },
  ];
  for (const s of sessions) {
    if (s.pinned) {
      groups[0].items.push(s);
      continue;
    }
    const t = sessionTimeMs(s.updated_at);
    if (t >= dayStart) groups[1].items.push(s);
    else if (t >= weekStart) groups[2].items.push(s);
    else groups[3].items.push(s);
  }
  return groups.filter((g) => g.items.length > 0);
}
