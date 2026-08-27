/* 会话归档（Top10-C）：本地隐藏方案的 localStorage 持久化纯函数模块。
 *
 * 设计要点：
 * - 归档只影响列表可见性，不触碰后端存储/任何业务逻辑；
 * - 读写全程 try/catch：隐私模式、容量超限等异常静默降级为「不归档」，
 *   绝不让列表因持久化失败而崩溃；保存失败仅返回 false（调用方维持
 *   本次会话内的内存态即可，刷新后丢失可接受）；
 * - 解析容错：非数组 / 含非字符串元素的脏数据一律按空处理并自愈重写。
 */

export const ARCHIVED_SESSIONS_KEY = "ra.archived-sessions.v1";

/** 最小存储接口（便于 node 环境单测注入桩，无需 jsdom）。 */
export interface KeyValueStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem?(key: string): void;
}

/** 校验并规整原始解析结果：仅保留字符串 id、去重。 */
export function parseArchivedIds(raw: unknown): string[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  for (const item of raw) {
    if (typeof item === "string" && item) seen.add(item);
  }
  return [...seen];
}

/** 读已归档会话 id 列表；缺失/损坏/不可读一律返回 []。 */
export function loadArchivedIds(
  storage: KeyValueStorage | undefined = defaultStorage(),
): string[] {
  // 无 localStorage（node 测试环境）→ 按未归档处理，与下方 try/catch 同一降级出口
  if (!storage) return [];
  try {
    const raw = storage.getItem(ARCHIVED_SESSIONS_KEY);
    if (!raw) return [];
    return parseArchivedIds(JSON.parse(raw));
  } catch {
    return [];
  }
}

/** 写已归档 id 列表；成功 true，失败（配额/占用等）false——调用方自行降级。 */
export function saveArchivedIds(
  ids: string[],
  storage: KeyValueStorage | undefined = defaultStorage(),
): boolean {
  if (!storage) return false;
  try {
    storage.setItem(ARCHIVED_SESSIONS_KEY, JSON.stringify(ids));
    return true;
  } catch {
    return false;
  }
}

/** 归档一个会话（幂等；返回新数组）。 */
export function archiveId(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids : [...ids, id];
}

/** 取消归档一个会话（幂等；返回新数组）。 */
export function unarchiveId(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((x) => x !== id) : ids;
}

function defaultStorage(): KeyValueStorage | undefined {
  // 浏览器环境用全局 localStorage；node 测试环境没有则返回 undefined，
  // 由 load/save 的 try/catch 兜底为「不归档」。
  const g = globalThis as { localStorage?: KeyValueStorage };
  return g.localStorage;
}
