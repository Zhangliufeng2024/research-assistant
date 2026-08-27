/* 侧栏导航模型（R15 导航收敛 13→6）。
 *
 * 六项侧栏入口中三项是聚合组：入口指向组内主路由，但激活态按「成员路由
 * 前缀数组」计算（react-router NavLink 的 end/前缀语义覆盖不了跨路径分组，
 * 故手写匹配）。深链（如 /threads/:id）不受影响——路由表保持全量，只收敛
 * 侧栏入口；聚合组成员页由 GroupShell 挂共享二级 tab 条。
 *
 * 本文件刻意保持纯逻辑（无 React 渲染）：isPathWithin / isNavActive /
 * findGroupLayout 可被 node 环境单测直接覆盖。
 */
import type { ComponentType, SVGProps } from "react";
import {
  IconChat,
  IconFlask,
  IconHome,
  IconLibrary,
  IconSettings,
  IconTasks,
} from "@/components/icons";

export type NavIcon = ComponentType<SVGProps<SVGSVGElement>>;

export interface NavItemDef {
  /** 入口点击后落地的主路由（= 组内第一个成员）。 */
  to: string;
  label: string;
  icon: NavIcon;
  /** 激活匹配前缀（含自身）；聚合组列出全部成员根路径。 */
  match: readonly string[];
}

/** 侧栏六项：总览 / 会话 / 任务中心 / 研究工作台 / 资料库 / 设置。 */
export const NAV_ITEMS: readonly NavItemDef[] = [
  { to: "/", label: "总览", icon: IconHome, match: ["/"] },
  { to: "/chat", label: "会话", icon: IconChat, match: ["/chat"] },
  {
    to: "/tasks",
    label: "任务中心",
    icon: IconTasks,
    match: ["/tasks", "/scheduler", "/analysis"],
  },
  {
    to: "/research",
    label: "研究工作台",
    icon: IconFlask,
    match: ["/research", "/threads", "/changes"],
  },
  {
    to: "/papers",
    label: "资料库",
    icon: IconLibrary,
    match: ["/papers", "/sources", "/artifacts"],
  },
  { to: "/settings", label: "设置", icon: IconSettings, match: ["/settings"] },
] as const;

/** 会话项在 Sidebar 中需要审批徽标的标记（数据驱动，避免字符串特判散落）。 */
export function isChatEntry(item: NavItemDef): boolean {
  return item.to === "/chat";
}

/**
 * 段边界感知的前缀匹配：`/tasks` 匹配 `/tasks` 与 `/tasks/x`，
 * 不匹配 `/tasks-x`；`/` 只匹配根自身。pathname 来自 useLocation
 * （HashRouter 下不含 query），无需处理查询串。
 */
export function isPathWithin(pathname: string, prefixes: readonly string[]): boolean {
  return prefixes.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

/** 侧栏项激活判断。 */
export function isNavActive(pathname: string, item: Pick<NavItemDef, "match">): boolean {
  return isPathWithin(pathname, item.match);
}

/* ---------- 聚合组的页内二级 tab ---------- */

export interface GroupTabDef {
  to: string;
  label: string;
}

export interface GroupLayoutDef {
  /** 组标识（调试/测试用）。 */
  key: string;
  tabs: readonly GroupTabDef[];
}

interface GroupLayoutRule {
  match: readonly string[];
  layout: GroupLayoutDef;
}

/** 三个聚合组的共享 tab 条定义；顺序即展示顺序。 */
const GROUP_LAYOUT_RULES: readonly GroupLayoutRule[] = [
  {
    match: ["/tasks", "/scheduler", "/analysis"],
    layout: {
      key: "task-center",
      tabs: [
        { to: "/tasks", label: "任务" },
        { to: "/scheduler", label: "运行队列" },
        { to: "/analysis", label: "分析运行" },
      ],
    },
  },
  {
    match: ["/research", "/threads", "/changes"],
    layout: {
      key: "workbench",
      tabs: [
        { to: "/research", label: "研究工作台" },
        { to: "/threads", label: "研究线程" },
        { to: "/changes", label: "变更" },
      ],
    },
  },
  {
    match: ["/papers", "/sources", "/artifacts"],
    layout: {
      key: "library",
      tabs: [
        { to: "/papers", label: "文库" },
        { to: "/sources", label: "资料库" },
        { to: "/artifacts", label: "产物审阅" },
      ],
    },
  },
];

/** 当前路径所属聚合组的 tab 布局；非聚合页返回 null（不渲染 tab 条）。 */
export function findGroupLayout(pathname: string): GroupLayoutDef | null {
  for (const rule of GROUP_LAYOUT_RULES) {
    if (isPathWithin(pathname, rule.match)) return rule.layout;
  }
  return null;
}
