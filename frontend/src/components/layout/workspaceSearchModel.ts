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
  /** 迭代2：产物文件命中携带所属会话（深链直达该会话）。 */
  sessionId?: string;
}

export const SEARCH_KIND_LABELS: Record<string, string> = {
  thread: "线程",
  task: "任务",
  source: "资料",
  research_item: "研究对象",
  claim: "主张",
  decision: "决策",
  artifact: "产物",
  artifact_file: "产物文件",
};

/** 命中 → 深链：线程直达详情，产物文件直达所属会话，其余落对应成员页。 */
export function searchHitPath(hit: SearchHit): string {
  if (hit.kind === "thread") return `/threads/${hit.id}`;
  if (hit.kind === "artifact_file" && hit.sessionId) {
    return `/chat/${encodeURIComponent(hit.sessionId)}`;
  }
  if (hit.kind === "artifact") return "/artifacts";
  if (hit.kind === "source") return "/sources";
  if (hit.kind === "task") return "/tasks";
  return "/research";
}

/** /api/search?scope=artifacts 的行结构。 */
export interface ArtifactRow {
  session_id: string;
  path: string;
  name: string;
  ext: string;
  size: number;
}

/** 迭代2：把产物文件行并入命中列表（去重、artifact_file 在前便于直达）。
 * 纯函数，node 可测。 */
export function mergeArtifactHits(
  base: SearchHit[],
  artifacts: ArtifactRow[],
  cap = 8,
): SearchHit[] {
  const seen = new Set(base.map((h) => `${h.kind}:${h.id}`));
  const extra: SearchHit[] = [];
  for (const row of artifacts) {
    const key = `artifact_file:${row.session_id}/${row.path}`;
    if (seen.has(key)) continue;
    seen.add(key);
    extra.push({
      kind: "artifact_file",
      id: key,
      title: row.name,
      detail: row.path,
      sessionId: row.session_id,
    });
    if (extra.length >= cap) break;
  }
  return [...extra, ...base];
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
