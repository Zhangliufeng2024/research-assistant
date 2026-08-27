/* 应用壳层侧栏（R15 导航收敛 13→6）。
 *
 * 激活态不走 NavLink 的 isActive（聚合组需要跨路径前缀匹配），改用
 * useLocation + navModel.isNavActive 手写计算；入口仍是 Link，指向组内
 * 主路由。会话项挂全局审批角标（usePendingApprovalCount，danger 色）。
 */
import { Link, useLocation } from "react-router-dom";
import { IconMoon, IconSun, LogoMark } from "@/components/icons";
import { useTheme } from "@/hooks/useTheme";
import { APP_VERSION } from "@/lib/version";
import { usePendingApprovalCount } from "@/stores/approvalSignal";
import { isChatEntry, isNavActive, NAV_ITEMS } from "./navModel";

function ApprovalBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span
      title={`${count} 项操作待审批`}
      className="ml-auto flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-danger px-1 text-[10.5px] font-semibold leading-none text-white"
    >
      {count}
    </span>
  );
}

export function Sidebar() {
  const { theme, toggle } = useTheme();
  const { pathname } = useLocation();
  const pendingApprovals = usePendingApprovalCount();

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-edge bg-rail">
      {/* 品牌区 */}
      <div className="flex items-center gap-2.5 px-5 pb-4 pt-5">
        <LogoMark className="h-8 w-8 rounded-[9px] shadow-sm" />
        <div className="min-w-0">
          <div className="text-[15px] font-semibold leading-tight">研究助手</div>
          <div className="text-[11px] leading-tight text-ink-3">Research Assistant</div>
        </div>
      </div>

      {/* 导航：六项入口（聚合组成员页由页内二级 tab 承载） */}
      <nav className="flex-1 space-y-0.5 overflow-y-auto px-3">
        {NAV_ITEMS.map((item) => {
          const active = isNavActive(pathname, item);
          const Icon = item.icon;
          return (
            <Link
              key={item.to}
              to={item.to}
              aria-current={active ? "page" : undefined}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors ${
                active
                  ? "bg-accent-tint text-accent-hover dark:text-accent"
                  : "text-ink-2 hover:bg-surface-2 hover:text-ink"
              }`}
            >
              <Icon className="h-[18px] w-[18px]" />
              {item.label}
              {isChatEntry(item) && <ApprovalBadge count={pendingApprovals} />}
            </Link>
          );
        })}
      </nav>

      {/* 底栏：版本 + 主题切换 */}
      <div className="flex items-center justify-between px-4 py-3">
        <span className="text-[11px] text-ink-3">v{APP_VERSION}</span>
        <button
          type="button"
          onClick={toggle}
          title={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
          className="rounded-lg p-2 text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          {theme === "dark" ? <IconSun className="h-4 w-4" /> : <IconMoon className="h-4 w-4" />}
        </button>
      </div>
    </aside>
  );
}
