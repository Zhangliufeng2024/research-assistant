/* artifacts.ts 纯逻辑回归（R12 P3/C1）。
 *
 * dock 与工具卡 chip 共用的路径归一化/候选序：后端 /api/workspace/file|tree
 * 以工作区根围栏解析（root / raw 后 safe_resolve），根内绝对路径与相对路径
 * 都可用；chip 里可能是模型回显的 Windows 绝对路径或带引号的 token。
 */
import { describe, expect, it, vi } from "vitest";
import {
  DOCK_COLLAPSED_KEY,
  IGNORED_TREE_PREFIXES,
  candidatePreviewPaths,
  isIgnoredTreeName,
  loadDockCollapsed,
  normalizeArtifactPath,
  saveDockCollapsed,
} from "../artifacts";

describe("normalizeArtifactPath", () => {
  it("反斜杠转正斜杠、去首尾空白与包裹引号", () => {
    expect(normalizeArtifactPath("  figures\\loss.png ")).toBe("figures/loss.png");
    expect(normalizeArtifactPath("'outputs/s1/f.png'")).toBe("outputs/s1/f.png");
    expect(normalizeArtifactPath('"D:\\ws\\a.png"')).toBe("D:/ws/a.png");
    expect(normalizeArtifactPath("`fig.png`")).toBe("fig.png");
  });

  it("已是干净路径原样返回；空串返回空串", () => {
    expect(normalizeArtifactPath("a/b.md")).toBe("a/b.md");
    expect(normalizeArtifactPath("")).toBe("");
  });
});

describe("candidatePreviewPaths（anchor 优先的候选序列）", () => {
  const dir = "outputs/20260823_103512_ai";

  it("相对路径 → [产物目录拼接, 原样]（fetch 按序带回退）", () => {
    expect(candidatePreviewPaths("fig7.png", dir)).toEqual([
      "outputs/20260823_103512_ai/fig7.png",
      "fig7.png",
    ]);
    expect(candidatePreviewPaths("sub/a.csv", dir)).toEqual([
      "outputs/20260823_103512_ai/sub/a.csv",
      "sub/a.csv",
    ]);
  });

  it("无 outputsDir 时只有原样候选", () => {
    expect(candidatePreviewPaths("fig7.png", null)).toEqual(["fig7.png"]);
  });

  it("盘符绝对路径 → 只用归一化后的自身", () => {
    const raw = "D:\\workspace\\outputs\\s\\f.png";
    expect(candidatePreviewPaths(raw, dir)).toEqual(["D:/workspace/outputs/s/f.png"]);
  });

  it("POSIX 绝对路径同理", () => {
    expect(candidatePreviewPaths("/home/ws/out.png", dir)).toEqual([
      "/home/ws/out.png",
    ]);
  });

  it("候选去重：路径恰好等于拼接结果时只留一条", () => {
    expect(candidatePreviewPaths(`${dir}/f.png`, dir)).toEqual([`${dir}/f.png`]);
  });

  it("空输入返回空数组", () => {
    expect(candidatePreviewPaths("", dir)).toEqual([]);
    expect(candidatePreviewPaths("   ", dir)).toEqual([]);
  });
});

describe("树过滤（_ra_exec 临时目录不进 dock）", () => {
  it("IGNORED_TREE_PREFIXES 收录 _ra_exec", () => {
    expect(IGNORED_TREE_PREFIXES).toContain("_ra_exec");
  });

  it("isIgnoredTreeName 命中前缀且放过普通名", () => {
    expect(isIgnoredTreeName("_ra_exec_abc123.py")).toBe(true);
    expect(isIgnoredTreeName("_ra_exec")).toBe(true);
    expect(isIgnoredTreeName("figures")).toBe(false);
    // 隐藏项由后端 tree 端点过滤，这里只管前缀
    expect(isIgnoredTreeName(".gitignore")).toBe(false);
  });
});

describe("dock 折叠偏好（loadDockCollapsed / saveDockCollapsed）", () => {
  it("键名稳定（会话页与任务页共享同一记忆）", () => {
    expect(DOCK_COLLAPSED_KEY).toBe("ra.artifacts.dock.collapsed");
  });

  it("无 localStorage 环境：读取走默认展开、保存静默", () => {
    // node 测试环境没有 localStorage——访问即 ReferenceError，须被吞掉
    expect(loadDockCollapsed()).toBe(false);
    expect(() => saveDockCollapsed(true)).not.toThrow();
    expect(loadDockCollapsed()).toBe(false); // 仍未写入
  });

  it("有记忆时记忆优先；无记忆时按视口宽度回退", () => {
    const store = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    });
    vi.stubGlobal("window", { innerWidth: 800 });
    try {
      expect(loadDockCollapsed()).toBe(true); // 无记忆：<1280 默认收起
      saveDockCollapsed(false);
      expect(loadDockCollapsed()).toBe(false); // 记忆覆盖视口默认
      saveDockCollapsed(true);
      expect(loadDockCollapsed()).toBe(true);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("损坏的存储值视为未记忆（回退视口默认）", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => "yes",
      setItem: () => undefined,
    });
    vi.stubGlobal("window", { innerWidth: 1600 });
    try {
      expect(loadDockCollapsed()).toBe(false); // "yes" !== "1" → 未记忆 → 宽屏展开
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
