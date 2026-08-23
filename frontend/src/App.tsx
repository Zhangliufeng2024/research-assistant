import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import {
  IconChat,
  IconLibrary,
  IconMoon,
  IconSettings,
  IconSun,
  IconTasks,
  LogoMark,
} from "@/components/icons";
import { useTheme } from "@/hooks/useTheme";
import { APP_VERSION } from "@/lib/version";
import { ChatView } from "@/views/ChatView";
import { PapersView } from "@/views/PapersView";
import { SettingsView } from "@/views/SettingsView";
import { TasksView } from "@/views/TasksView";

const NAV = [
  { to: "/", label: "会话", icon: IconChat },
  { to: "/tasks", label: "任务", icon: IconTasks },
  { to: "/papers", label: "文库", icon: IconLibrary },
  { to: "/settings", label: "设置", icon: IconSettings },
] as const;

export default function App() {
  const { theme, toggle } = useTheme();

  return (
    <HashRouter>
      <div className="flex h-full">
        <aside className="flex w-60 shrink-0 flex-col border-r border-edge bg-rail">
          {/* 品牌区 */}
          <div className="flex items-center gap-2.5 px-5 pb-4 pt-5">
            <LogoMark className="h-8 w-8 rounded-[9px] shadow-sm" />
            <div className="min-w-0">
              <div className="text-[15px] font-semibold leading-tight">研究助手</div>
              <div className="text-[11px] leading-tight text-ink-3">
                Research Assistant
              </div>
            </div>
          </div>

          {/* 导航 */}
          <nav className="flex-1 space-y-0.5 overflow-y-auto px-3">
            {NAV.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] font-medium transition-colors ${
                    isActive
                      ? "bg-accent-tint text-accent-hover dark:text-accent"
                      : "text-ink-2 hover:bg-surface-2 hover:text-ink"
                  }`
                }
              >
                <Icon className="h-[18px] w-[18px]" />
                {label}
              </NavLink>
            ))}
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
              {theme === "dark" ? (
                <IconSun className="h-4 w-4" />
              ) : (
                <IconMoon className="h-4 w-4" />
              )}
            </button>
          </div>
        </aside>

        {/* 主内容区 */}
        <main className="min-w-0 flex-1 overflow-y-auto">
          <Routes>
            <Route path="/" element={<ChatView />} />
            <Route path="/tasks" element={<TasksView />} />
            <Route path="/papers" element={<PapersView />} />
            <Route path="/settings" element={<SettingsView />} />
          </Routes>
        </main>
      </div>
    </HashRouter>
  );
}
