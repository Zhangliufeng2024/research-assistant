/* 命令面板匹配模型（阶段 4）：fuse.js 模糊匹配的纯逻辑封装。
 *
 * 与组件解耦以便 node 环境单测：输入条目只需携带 title（可选 detail），
 * 输出保持原条目引用、按相关度排序。空查询原样返回（展示默认列表）。
 */
import Fuse from "fuse.js";

export interface MatchableItem {
  title: string;
  detail?: string;
}

/** 模糊过滤：大小写不敏感；title/detail 参与匹配；空查询原样返回。 */
export function filterItems<T extends MatchableItem>(items: T[], query: string): T[] {
  const q = query.trim();
  if (!q) return items;
  const fuse = new Fuse(items, {
    keys: ["title", "detail"],
    threshold: 0.4,
    ignoreLocation: true,
  });
  return fuse.search(q).map((r) => r.item);
}
