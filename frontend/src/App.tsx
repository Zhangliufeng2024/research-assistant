/* 应用壳层（R15 改造 → 阶段 4 三栏布局）：
 * - 64px 导航栏（NavRail）+ 常驻会话区（ChatView）+ 按需检查器；
 * - 会话区常驻（U-4 核心）：导航切换只切换伴生面板（display 可见性），
 *   聊天组件树不卸载——输入草稿/滚动锚点由 sessionStore 按会话持久化；
 * - 全局快捷键单一注册表（useHotkeys）+ 命令面板（Ctrl+K）+ 会话二级
 *   抽屉（SessionDrawer）；
 * - 审批全局感知、首次运行向导、全局 Toaster 挂载照旧；
 * - 其余 view 保持 React.lazy 代码分割与全量路由表（深链不受影响）。
 */
import { lazy, Suspense, useEffect, type ReactNode } from "react";
import { HashRouter, Route, Routes, useLocation } from "react-router-dom";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { PageSkeleton } from "@/components/common/PageSkeleton";
import { Toaster } from "@/components/common/Toaster";
import { ApprovalToastWatcher } from "@/components/layout/ApprovalToastWatcher";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { FirstRunWizard } from "@/components/layout/FirstRunWizard";
import { GroupShell } from "@/components/layout/GroupShell";
import { NavRail } from "@/components/layout/NavRail";
import { SessionDrawer } from "@/components/layout/SessionDrawer";
import { WorkspaceSearch } from "@/components/layout/WorkspaceSearch";
import { useHotkeys } from "@/hooks/useHotkeys";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useUiStore } from "@/stores/uiStore";

/* ---- 路由代码分割（R15）：各 view 独立 chunk，首屏只拉壳层 ---- */
const ProjectHomeView = lazy(() =>
  import("@/views/ProjectHomeView").then((m) => ({ default: m.ProjectHomeView })),
);
/* 会话区虽常驻，仍走懒加载：首屏加载一次后即驻留，不再随导航卸载 */
const ChatView = lazy(() => import("@/views/ChatView").then((m) => ({ default: m.ChatView })));
const TasksView = lazy(() => import("@/views/TasksView").then((m) => ({ default: m.TasksView })));
const TaskBoardView = lazy(() =>
  import("@/views/TaskBoardView").then((m) => ({ default: m.TaskBoardView })),
);
const TaskHistoryView = lazy(() =>
  import("@/views/TaskHistoryView").then((m) => ({ default: m.TaskHistoryView })),
);
const SchedulerView = lazy(() =>
  import("@/views/SchedulerView").then((m) => ({ default: m.SchedulerView })),
);
const PapersView = lazy(() =>
  import("@/views/PapersView").then((m) => ({ default: m.PapersView })),
);
const SourcesView = lazy(() =>
  import("@/views/SourcesView").then((m) => ({ default: m.SourcesView })),
);
const ResearchView = lazy(() =>
  import("@/views/ResearchView").then((m) => ({ default: m.ResearchView })),
);
const AnalysisRunsView = lazy(() =>
  import("@/views/AnalysisRunsView").then((m) => ({ default: m.AnalysisRunsView })),
);
const ThreadsView = lazy(() =>
  import("@/views/ThreadsView").then((m) => ({ default: m.ThreadsView })),
);
const ChangesView = lazy(() =>
  import("@/views/ChangesView").then((m) => ({ default: m.ChangesView })),
);
const ArtifactReviewView = lazy(() =>
  import("@/views/ArtifactReviewView").then((m) => ({ default: m.ArtifactReviewView })),
);
const NotificationsView = lazy(() =>
  import("@/views/NotificationsView").then((m) => ({ default: m.NotificationsView })),
);
const SettingsView = lazy(() =>
  import("@/views/SettingsView").then((m) => ({ default: m.SettingsView })),
);

/** 是否处于会话区路由（/chat 或 /chat/:sessionId）。 */
function isChatPath(pathname: string): boolean {
  return pathname === "/chat" || pathname.startsWith("/chat/");
}

/** 常驻会话区（U-4）：active=false 时仅隐藏不卸载，草稿/滚动/连接状态全保留。 */
function ResidentSessionArea({ active }: { active: boolean }) {
  return (
    <section
      aria-label="会话区"
      className={active ? "flex min-w-0 flex-1" : "hidden"}
    >
      <ErrorBoundary label="会话区">
        <Suspense fallback={<PageSkeleton />}>
          <ChatView active={active} />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}

/** 主内容区：路由面板（会话路由时整体让位给常驻会话区）。错误边界需要
 * useLocation 提供 resetKey，而 useLocation 必须在 Router 内部调用。 */
function MainContent({ hidden }: { hidden: boolean }) {
  const { pathname } = useLocation();

  return (
    <main className={hidden ? "hidden" : "min-w-0 flex-1 overflow-y-auto"}>
      <WorkspaceSearch />
      <GroupShell>
        {/* 边界放在 Suspense **外侧**：既接住 view 的渲染异常，也接住
            lazy chunk 加载失败（发版后旧页面请求已删除的 hash chunk）。
            侧栏在边界之外，因此单页崩溃仍可导航逃生。
            resetKey=pathname：导航到别的路由即自动清除错误态。 */}
        <ErrorBoundary label="页面" resetKey={pathname}>
          <Suspense fallback={<PageSkeleton />}>
            <Routes>
              <Route path="/" element={<ProjectHomeView />} />
              {/* 会话路由（/chat、/chat/:sessionId）由常驻会话区承载，
                  不在此渲染：ChatView 深链逻辑自行解析 pathname。 */}
              <Route path="/tasks" element={<TasksView />} />
              <Route path="/tasks/board" element={<TaskBoardView />} />
              <Route path="/tasks/history" element={<TaskHistoryView />} />
              <Route path="/scheduler" element={<SchedulerView />} />
              <Route path="/papers" element={<PapersView />} />
              <Route path="/sources" element={<SourcesView />} />
              <Route path="/research" element={<ResearchView />} />
              <Route path="/analysis" element={<AnalysisRunsView />} />
              <Route path="/threads" element={<ThreadsView />} />
              <Route path="/threads/:threadId" element={<ThreadsView />} />
              <Route path="/changes" element={<ChangesView />} />
              <Route path="/artifacts" element={<ArtifactReviewView />} />
              <Route path="/notifications" element={<NotificationsView />} />
              <Route path="/settings" element={<SettingsView />} />
            </Routes>
          </Suspense>
        </ErrorBoundary>
      </GroupShell>
    </main>
  );
}

/** 视口断点同步：useMediaQuery（宽屏判定）写入 uiStore，供全局命令
 * （Ctrl+I 检查器开关）在「内联 dock / 抽屉」两种形态间正确分流。 */
function WideLayoutSync() {
  const isWide = useMediaQuery("(min-width: 1280px)");
  useEffect(() => {
    useUiStore.getState().setWideLayout(isWide);
  }, [isWide]);
  return null;
}

function AppShell() {
  const { pathname } = useLocation();
  const railCollapsed = useUiStore((s) => s.railCollapsed);
  const onChat = isChatPath(pathname);
  useHotkeys(); // 全局快捷键：单一注册表，命令面板与键位共用

  return (
    <div className="flex h-full">
      {/* 导航栏（Ctrl+B 可折叠） */}
      {!railCollapsed && <NavRail />}

      {/* 常驻会话区：切走导航仅隐藏，聊天组件树不卸载 */}
      <ResidentSessionArea active={onChat} />

      {/* 其余路由面板：会话路由时让位（display:none） */}
      <MainContent hidden={onChat} />

      {/* 壳层浮层：命令面板 / 会话二级抽屉 / 视口断点同步 */}
      <CommandPalette />
      <SessionDrawer />
      <WideLayoutSync />
    </div>
  );
}

/** 侧栏外层兜底：连壳层自己崩了也不至于整页全白。 */
function ShellBoundary({ children }: { children: ReactNode }) {
  return <ErrorBoundary label="应用">{children}</ErrorBoundary>;
}

export default function App() {
  return (
    <HashRouter>
      <ShellBoundary>
        <AppShell />

        {/* 壳层单例：审批他页提醒 / 首次运行向导 / 全局轻提示 */}
        <ApprovalToastWatcher />
        <FirstRunWizard />
        <Toaster />
      </ShellBoundary>
    </HashRouter>
  );
}
