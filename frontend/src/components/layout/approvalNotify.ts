/* 审批全局感知的判定逻辑（R15）：纯函数，node 环境可测。
 *
 * ApprovalToastWatcher 订阅 useLastApprovalSignal：新信号到达且用户不在
 * 对应来源页面时弹 toast 提醒。本文件回答「在不在对应页面」与「提醒文案」，
 * 便于脱离 React/DOM 断言。
 */
import type { ApprovalSource } from "@/lib/types";
import { isPathWithin } from "./navModel";

/** 各审批来源对应的页面归属：chat → 会话；task → 任务中心聚合组三页。 */
const SOURCE_PAGE_PREFIXES: Record<ApprovalSource, readonly string[]> = {
  chat: ["/chat"],
  task: ["/tasks", "/scheduler", "/analysis"],
};

export function isOnSourcePage(pathname: string, source: ApprovalSource): boolean {
  return isPathWithin(pathname, SOURCE_PAGE_PREFIXES[source]);
}

/** 是否应当弹 toast：新审批到达时用户不在对应页面。 */
export function shouldNotifyApproval(pathname: string, source: ApprovalSource): boolean {
  return !isOnSourcePage(pathname, source);
}

/** toast 文案：待审批：{tool} — {summary}。 */
export function formatApprovalNotice(signal: { tool: string; summary: string }): string {
  return `待审批：${signal.tool} — ${signal.summary}`;
}
