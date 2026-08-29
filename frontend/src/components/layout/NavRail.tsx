/* 应用导航栏（阶段 4，设计文档 §1）：64px 图标窄栏。
 *
 * 取代原 240px 宽侧栏（Sidebar）：图标 + 短标签，聚合组入口与激活态判定
 * 完全复用 navModel（NAV_ITEMS / isNavActive），仅展示形态收敛。
 * 会话项是导航栏的「二级抽屉」入口：点击进入会话区并滑出会话列表抽屉
 * （SessionDrawer），不占常驻栏位。
 */
import { Link, useLocation } from "react-router-dom";
import { IconMoon, IconSun, LogoMark } from "@/components/icons";
import { useTheme } from "@/hooks/useTheme";
import { APP_VERSION } from "@/lib/version";
import { usePendingApprovalCount } from "@/stores/approvalSignal";
import { useUiStore } from "@/stores/uiStore";
import { go } from "@/hooks/useHotkeys";
import { isNavActive, NAV_ITEMS, type NavItemDef } from "./navModel";

/** 窄栏短标签：全称放 title/aria，栏内用 2 字短词（w-16 放不下长词）。 */
const SHORT_LABELS: Record<string, string> = {
  任务中心: "任务",
  研究工作台: "研究",
  资料库: "文库",
};

const shortLabel = (item: NavItemDef): string => SHORT_LABELS[item.label] ?? item.label;

/** 审批待办红点（会话项）：无待办时不渲染。 */
function ApprovalDot({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <span
      aria-hidden
      className="absolute right-2 top-1.5 flex h-[14px] min-w-[14px] items-center justify-center rounded-full bg-danger px-0.5 text-[9px] font-semibold leading-none text-white"
    >
      {count}
    </span>
  );
}

export function NavRail() {
  const { theme, toggle } = useTheme();
  const { pathname } = useLocation();
  const pendingApprovals = usePendingApprovalCount();
  const setSessionDrawerOpen = useUiStore((s) => s.setSessionDrawerOpen);
  const setPaletteOpen = useUiStore((s) => s.setPaletteOpen);

  const itemCls = (active: boolean) =>
    `relative flex w-full flex-col items-center gap-1 rounded-xl py-2.5 text-[10px] font-medium transition-colors ${
      active
        ? "bg-accent-tint text-accent-hover dark:text-accent"
        : "text-ink-2 hover:bg-surface-2 hover:text-ink"
    }`;

  return (
    <aside
      aria-label="主导航"
      className="flex w-16 shrink-0 flex-col items-center border-r border-edge bg-rail py-3"
    >
      {/* 品牌区 + 命令面板入口 */}
      <button
        type="button"
        onClick={() => setPaletteOpen(true)}
        title="命令面板（Ctrl+K）"
        aria-label="打开命令面板"
        className="mb-3 rounded-[9px] transition-opacity hover:opacity-80"
      >
        <LogoMark className="h-8 w-8 rounded-[9px] shadow-sm" />
      </button>

      <nav className="flex w-full flex-1 flex-col gap-0.5 px-1.5">
        {NAV_ITEMS.map((item) => {
          const active = isNavActive(pathname, item);
          const Icon = item.icon;
          if (item.to === "/chat") {
            // 会话：点击进入会话区并滑出二级抽屉（会话列表）
            return (
              <button
                key={item.to}
                type="button"
                onClick={() => {
                  go("/chat");
                  setSessionDrawerOpen(true);
                }}
                aria-current={active ? "page" : undefined}
                title={`${item.label}（点击展开会话列表）`}
                className={itemCls(active)}
              >
                <Icon className="h-5 w-5" />
                {shortLabel(item)}
                <ApprovalDot count={pendingApprovals} />
              </button>
            );
          }
          return (
            <Link
              key={item.to}
              to={item.to}
              aria-current={active ? "page" : undefined}
              title={item.label}
              className={itemCls(active)}
            >
              <Icon className="h-5 w-5" />
              {shortLabel(item)}
            </Link>
          );
        })}
      </nav>

      {/* 底栏：主题切换（版本号入 title，窄栏放不下页脚） */}
      <button
        type="button"
        onClick={toggle}
        title={`${theme === "dark" ? "切换到浅色主题" : "切换到深色主题"} · v${APP_VERSION}`}
        aria-label={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
        className="rounded-xl p-2.5 text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
      >
        {theme === "dark" ? <IconSun className="h-5 w-5" /> : <IconMoon className="h-5 w-5" />}
      </button>
    </aside>
  );
}
