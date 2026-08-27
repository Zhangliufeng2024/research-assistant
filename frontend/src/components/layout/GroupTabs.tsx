/* 聚合组页内二级 tab 条（R15）：segmented pill 行。
 *
 * 由 GroupShell 在布局层按路由条件渲染，成员 view 文件零改动即共享本条。
 * NavLink 默认前缀语义正好覆盖成员页深链：/threads/:id 会点亮「研究线程」
 * tab；/tasks 与 /tasks/:id 同理——故无需 end 也无需手写匹配。
 */
import { NavLink } from "react-router-dom";
import type { GroupLayoutDef } from "./navModel";

const itemCls = ({ isActive }: { isActive: boolean }) =>
  `rounded-lg px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
    isActive
      ? "bg-accent-tint text-accent-hover dark:text-accent"
      : "text-ink-2 hover:bg-surface-2 hover:text-ink"
  }`;

export function GroupTabs({ layout }: { layout: GroupLayoutDef }) {
  return (
    <nav
      aria-label="分组页内导航"
      className="sticky top-12 z-10 flex shrink-0 items-center gap-1 border-b border-edge bg-canvas/95 px-4 py-2 backdrop-blur"
    >
      {layout.tabs.map((tab) => (
        <NavLink key={tab.to} to={tab.to} className={itemCls}>
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
