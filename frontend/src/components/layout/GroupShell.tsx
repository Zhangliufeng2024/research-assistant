/* 聚合组布局壳（R15）：给三个聚合组的成员页挂共享二级 tab 条。
 *
 * 关键设计：不改任何只读 view 文件——App.tsx 把 <Routes> 的输出作为
 * children 传入本组件，这里按当前路径判断：
 * - 非聚合页：原样透传（fragment，不产生额外 DOM，view 高度语义与旧版
 *   完全一致）；
 * - 聚合页：包一层「h-full 纵向 flex」，tab 条在上、视图区占满剩余高度，
 *   使 TasksView / ThreadsView 等 h-full 工作区视图不会因多出一条 tab 而
 *   溢出滚动；流式布局页（运行队列等 mx-auto 页）照常由 main 滚动，
 *   tab 条 sticky 钉在顶栏下方始终可见。
 */
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { findGroupLayout } from "./navModel";
import { GroupTabs } from "./GroupTabs";

export function GroupShell({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const layout = findGroupLayout(pathname);

  if (!layout) return <>{children}</>;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <GroupTabs layout={layout} />
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}
