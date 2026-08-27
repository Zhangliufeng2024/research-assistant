/* 全局搜索（Ctrl+K）交互模型（R15 键盘层）：纯逻辑，node 环境可测。
 *
 * 从 App.tsx 抽出：命中分类标签、深链映射、↑↓ 高亮移动、Enter 选择判定。
 * 组件层（WorkspaceSearch）只做渲染与事件接线。
 */

export interface SearchHit {
  kind: string;
  id: string;
  title?: string;
  detail?: string;
}

export const SEARCH_KIND_LABELS: Record<string, string> = {
  thread: "线程",
  task: "任务",
  source: "资料",
  research_item: "研究对象",
  claim: "主张",
  decision: "决策",
  artifact: "产物",
};

/** 命中 → 深链：线程直达详情，其余落对应成员页（R15 收敛后仍全量保留路由）。 */
export function searchHitPath(hit: SearchHit): string {
  if (hit.kind === "thread") return `/threads/${hit.id}`;
  if (hit.kind === "artifact") return "/artifacts";
  if (hit.kind === "source") return "/sources";
  if (hit.kind === "task") return "/tasks";
  return "/research";
}

/**
 * ↑↓ 移动高亮（循环滚动）：末条 ↓ 回到首条，首条 ↑ 到末条。
 * 无候选时维持 -1（表示无高亮）。
 */
export function moveHighlight(current: number, delta: -1 | 1, length: number): number {
  if (length <= 0) return -1;
  const next = current + delta;
  if (next < 0) return length - 1;
  if (next >= length) return 0;
  return next;
}

/** Enter 选择判定：空结果 / 输入中无候选 / 索引越界一律返回 null（不误触）。 */
export function pickEnterIndex(highlight: number, length: number): number | null {
  if (length <= 0) return null;
  if (highlight < 0 || highlight >= length) return null;
  return highlight;
}
