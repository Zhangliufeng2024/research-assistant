/* 会话搜索纯函数（Top10-A）：客户端过滤，可单测。
 *
 * 口径：对**展示标题**（title 为空时回退 last_message，与列表渲染同源，
 * 见 lib/format.ts sessionTitle）做不区分大小写的子串匹配；查询为空白串
 * 时不过滤。返回新数组，不改入参。
 */
import { sessionTitle } from "@/lib/format";
import type { SessionSummary } from "@/lib/types";

/** 列表条目的展示标题（重命名覆盖层也用它，保证渲染/过滤/搜索同一口径）。 */
export function sessionDisplayTitle(s: SessionSummary): string {
  return sessionTitle(s.title, s.last_message);
}

/** 按查询串过滤会话（不区分大小写子串匹配展示标题）。 */
export function filterSessions(
  sessions: SessionSummary[],
  query: string,
): SessionSummary[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...sessions];
  return sessions.filter((s) => sessionDisplayTitle(s).toLowerCase().includes(q));
}
