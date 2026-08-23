/* 产物路径纯逻辑（R12 P3/C1）：dock 树与工具卡 chip 共用。
 *
 * 后端 /api/workspace/file|tree 以「工作区根 / 参数」拼接后 safe_resolve
 * 围栏（web/workspace.py::_fence）——根内绝对路径与相对路径都能预览；
 * chip 文本来自模型回显，可能是 Windows 绝对路径或带引号的 token，
 * 统一在此归一化。相对路径的确定性落点是会话产物目录（双轨制），
 * 故候选序 anchor 在前、原样在后：fetch 按序尝试，命中即停。
 */

/** 树中不展示的前缀：frozen_exec 的进程内临时脚本文件落点。 */
export const IGNORED_TREE_PREFIXES = ["_ra_exec"] as const;

/** 归一化 chip 路径：去空白与包裹引号/反引号，反斜杠转正斜杠。 */
export function normalizeArtifactPath(raw: string): string {
  let s = raw.trim();
  if (
    (s.startsWith("'") && s.endsWith("'")) ||
    (s.startsWith('"') && s.endsWith('"')) ||
    (s.startsWith("`") && s.endsWith("`"))
  ) {
    if (s.length >= 2) s = s.slice(1, -1);
  }
  return s.trim().replace(/\\/g, "/");
}

function isAbsolutePosixLike(s: string): boolean {
  return /^[a-z]:\//i.test(s) || s.startsWith("/");
}

/**
 * chip 路径 → 预览候选（按优先级）：
 * - 绝对路径 → [归一化自身]；
 * - 相对路径且有产物目录 → [anchorJoin, 原样]；无则 [原样]。
 * 去重保序；空输入返回 []。
 */
export function candidatePreviewPaths(
  raw: string,
  outputsDir: string | null,
): string[] {
  const p = normalizeArtifactPath(raw);
  if (!p) return [];
  if (isAbsolutePosixLike(p)) return [p];
  const out: string[] = [];
  // 路径已落在产物目录内（模型常回显 outputs/<sid>/x.png）则不再二次拼接
  const anchored =
    outputsDir != null &&
    outputsDir !== "" &&
    (p === outputsDir.replace(/\/+$/, "") ||
      p.startsWith(`${outputsDir.replace(/\/+$/, "")}/`));
  if (outputsDir && !anchored) {
    out.push(`${outputsDir.replace(/\/+$/, "")}/${p}`);
  }
  if (!out.includes(p)) out.push(p);
  return out;
}

/** 目录树条目名是否应被 dock 忽略（临时执行文件等）。 */
export function isIgnoredTreeName(name: string): boolean {
  return IGNORED_TREE_PREFIXES.some((p) => name.startsWith(p));
}

/* ---- dock 折叠偏好（localStorage 记忆，跨视图共享） ---- */

export const DOCK_COLLAPSED_KEY = "ra.artifacts.dock.collapsed";

/** 读取折叠偏好：无记忆时按视口宽度默认——xl(1280px) 以上展开。 */
export function loadDockCollapsed(): boolean {
  try {
    const saved = localStorage.getItem(DOCK_COLLAPSED_KEY);
    if (saved != null) return saved === "1";
  } catch {
    /* 存储不可用走默认 */
  }
  return typeof window !== "undefined" && window.innerWidth < 1280;
}

/** 持久化折叠偏好；失败静默（仅影响下次记忆）。 */
export function saveDockCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(DOCK_COLLAPSED_KEY, collapsed ? "1" : "0");
  } catch {
    /* 忽略持久化失败 */
  }
}
