/* 应用壳层（R15 改造）：
 * - 侧栏 13→6（Sidebar + navModel），聚合组成员页共享 GroupShell 二级 tab；
 * - 全部 view 改 React.lazy 代码分割，Suspense 落 PageSkeleton；
 * - 审批全局感知（侧栏角标 + ApprovalToastWatcher 他页提醒）；
 * - 首次运行向导、全局 Toaster 挂载、顶栏通知中心入口（在 WorkspaceSearch 内）。
 * 路由表保持全量：Ctrl+K 深链（/threads/:id 等）不受侧栏收敛影响。
 */
import { lazy, Suspense } from "react";
import { HashRouter, Route, Routes } from "react-router-dom";
import { PageSkeleton } from "@/components/common/PageSkeleton";
import { Toaster } from "@/components/common/Toaster";
import { ApprovalToastWatcher } from "@/components/layout/ApprovalToastWatcher";
import { FirstRunWizard } from "@/components/layout/FirstRunWizard";
import { GroupShell } from "@/components/layout/GroupShell";
import { Sidebar } from "@/components/layout/Sidebar";
import { WorkspaceSearch } from "@/components/layout/WorkspaceSearch";

/* ---- 路由代码分割（R15）：各 view 独立 chunk，首屏只拉壳层 ---- */
const ProjectHomeView = lazy(() =>
  import("@/views/ProjectHomeView").then((m) => ({ default: m.ProjectHomeView })),
);
const ChatView = lazy(() => import("@/views/ChatView").then((m) => ({ default: m.ChatView })));
const TasksView = lazy(() => import("@/views/TasksView").then((m) => ({ default: m.TasksView })));
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

export default function App() {
  return (
    <HashRouter>
      <div className="flex h-full">
        <Sidebar />

        {/* 主内容区 */}
        <main className="min-w-0 flex-1 overflow-y-auto">
          <WorkspaceSearch />
          <GroupShell>
            <Suspense fallback={<PageSkeleton />}>
              <Routes>
                <Route path="/" element={<ProjectHomeView />} />
                <Route path="/chat" element={<ChatView />} />
                <Route path="/tasks" element={<TasksView />} />
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
          </GroupShell>
        </main>
      </div>

      {/* 壳层单例：审批他页提醒 / 首次运行向导 / 全局轻提示 */}
      <ApprovalToastWatcher />
      <FirstRunWizard />
      <Toaster />
    </HashRouter>
  );
}
