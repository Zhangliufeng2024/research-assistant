/* 行级 diff 纯函数（方案 2b）：LCS 算法 + 公共前后缀修剪，供工具卡的
 * 内联 diff 卡渲染 edit_file / apply_patch 的变更预览。无第三方依赖，
 * 纯函数可 vitest 覆盖。
 *
 * 复杂度：中段 O(n*m) 内存/时间；超大输入退化为整体替换（先按行数上限
 * 修剪——diff 卡是给人扫一眼的预览，不是版本库级的精确补丁）。
 */

export type DiffRowType = "add" | "del" | "ctx";

export interface DiffRow {
  type: DiffRowType;
  text: string;
}

/** 触发退化保护的中段行数上限（约 2000×2000 的 DP 表 ≈ 16MB，封住极端输入）。 */
const MAX_DIFF_LINES = 2000;

/** 逐行 diff：oldText → newText 的行级变更序列（上下文行 type="ctx"）。 */
export function diffLines(oldText: string, newText: string): DiffRow[] {
  // 空串 = 零行（"".split("\n") 会得到 [""] 一个空行，产生假删除）
  const a = oldText ? oldText.split("\n") : [];
  const b = newText ? newText.split("\n") : [];

  // 公共前后缀修剪：O(n) 预处理把 LCS 只留在真正变化的中段
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1;
  let endA = a.length - 1;
  let endB = b.length - 1;
  while (endA >= start && endB >= start && a[endA] === b[endB]) {
    endA -= 1;
    endB -= 1;
  }
  const midA = a.slice(start, endA + 1);
  const midB = b.slice(start, endB + 1);

  const rows: DiffRow[] = [];
  for (let i = 0; i < start; i++) rows.push({ type: "ctx", text: a[i]! });
  if (midA.length > MAX_DIFF_LINES || midB.length > MAX_DIFF_LINES) {
    // 超大中段：退化为整体替换（先删后加），保正确性弃紧凑性
    for (const t of midA) rows.push({ type: "del", text: t });
    for (const t of midB) rows.push({ type: "add", text: t });
  } else {
    rows.push(...lcsRows(midA, midB));
  }
  for (let i = endA + 1; i < a.length; i++) rows.push({ type: "ctx", text: a[i]! });
  return rows;
}

/** 标准 LCS 回溯：返回中段的 add/del/ctx 序列（删除优先于插入，diff 惯例）。 */
function lcsRows(a: string[], b: string[]): DiffRow[] {
  const n = a.length;
  const m = b.length;
  // dp[i][j] = a[i..] 与 b[j..] 的 LCS 长度（自底向上，末行/列恒 0）
  const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    const row = dp[i]!;
    const next = dp[i + 1]!;
    for (let j = m - 1; j >= 0; j--) {
      row[j] = a[i] === b[j] ? next[j + 1]! + 1 : Math.max(next[j]!, row[j + 1]!);
    }
  }
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      rows.push({ type: "ctx", text: a[i]! });
      i += 1;
      j += 1;
    } else if (dp[i + 1]![j]! >= dp[i]![j + 1]!) {
      rows.push({ type: "del", text: a[i]! });
      i += 1;
    } else {
      rows.push({ type: "add", text: b[j]! });
      j += 1;
    }
  }
  while (i < n) {
    rows.push({ type: "del", text: a[i]! });
    i += 1;
  }
  while (j < m) {
    rows.push({ type: "add", text: b[j]! });
    j += 1;
  }
  return rows;
}

/** diff 摘要：增/删行数（diff 卡头部的 +n / -n 徽标用）。 */
export function diffStats(rows: DiffRow[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const r of rows) {
    if (r.type === "add") added += 1;
    else if (r.type === "del") removed += 1;
  }
  return { added, removed };
}
