/* 顶栏（R15 引入，阶段 4 改造）。
 *
 * 原「全局搜索（Ctrl+K）」对话框迁入命令面板（CommandPalette）：数据源
 * （/api/project/search + 产物检索）与 180ms 防抖逻辑原样搬移，命令注册表
 * 统一接管 Ctrl+K 分发（设计文档 §3/§4：命令面板与快捷键共享同一注册表）。
 * 本组件只保留顶栏壳：搜索入口按钮（打开命令面板）+ 通知中心 + 状态语。
 */
import { useNavigate } from "react-router-dom";
import { IconBell } from "@/components/icons";
import { usePendingApprovalCount } from "@/stores/approvalSignal";
import { useUiStore } from "@/stores/uiStore";

/** 顶栏右侧通知中心入口（R15 自侧栏撤出后的替代路径）。 */
export function NotificationsButton() {
  const navigate = useNavigate();
  const pending = usePendingApprovalCount();
  return (
    <button
      type="button"
      onClick={() => navigate("/notifications")}
      title="通知中心"
      aria-label={`通知中心${pending > 0 ? `（${pending} 项操作待审批）` : ""}`}
      className="relative rounded-lg p-2 text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
    >
      <IconBell className="h-[18px] w-[18px]" />
      {pending > 0 && (
        <span
          aria-hidden
          className="absolute right-1 top-1 flex h-[15px] min-w-[15px] items-center justify-center rounded-full bg-danger px-0.5 text-[9.5px] font-semibold leading-none text-white"
        >
          {pending}
        </span>
      )}
    </button>
  );
}

export function WorkspaceSearch() {
  const setPaletteOpen = useUiStore((s) => s.setPaletteOpen);

  return (
    <div className="sticky top-0 z-20 flex h-12 items-center justify-between border-b border-edge bg-canvas/95 px-5 backdrop-blur">
      <button
        type="button"
        onClick={() => setPaletteOpen(true)}
        className="flex w-full max-w-md items-center gap-2 rounded-lg border border-edge bg-surface px-3 py-1.5 text-left text-xs text-ink-3 hover:border-accent/40"
      >
        <span className="text-sm">⌕</span>
        <span>搜索命令、会话与项目对象…</span>
        <kbd className="ml-auto rounded border border-edge px-1.5 py-0.5 font-mono text-[10px]">Ctrl K</kbd>
      </button>
      <div className="ml-4 flex shrink-0 items-center gap-2">
        <NotificationsButton />
        <span className="hidden text-[11px] text-ink-3 md:block">统一科研工作空间</span>
      </div>
    </div>
  );
}
