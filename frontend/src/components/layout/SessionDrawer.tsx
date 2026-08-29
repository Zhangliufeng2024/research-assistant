/* 会话二级抽屉（阶段 4，设计文档 §1）：导航栏会话项滑出的会话列表。
 *
 * 复用既有 SessionList（搜索/重命名/归档/两段式删除全部保留），仅更换
 * 容器：从 ChatView 的常驻二级栏改为遮罩抽屉（左起 64px 紧贴导航栏）。
 * 开关状态在 uiStore.sessionDrawerOpen；Esc 由全局快捷键（useHotkeys 的
 * overlay.close 命令）统一关闭，这里不再单独挂监听（单一 Esc 分发路径）。
 */
import { SessionList } from "@/components/chat/SessionList";
import { toast } from "@/stores/toastStore";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";

export function SessionDrawer() {
  const open = useUiStore((s) => s.sessionDrawerOpen);
  const setOpen = useUiStore((s) => s.setSessionDrawerOpen);
  const bumpComposerFocus = useUiStore((s) => s.bumpComposerFocus);
  const {
    chat,
    sessions,
    sessionsLoading,
    newSession,
    openSession,
    refreshSessions,
    deleteSession,
  } = useChatStore();

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-30"
      data-testid="session-drawer"
      onMouseDown={() => setOpen(false)}
    >
      {/* 遮罩下的透明层承接点击关闭；面板本体阻止事件冒泡 */}
      <aside
        aria-label="会话列表"
        className="absolute bottom-0 left-16 top-0 w-72 border-r border-edge bg-canvas shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <SessionList
          sessions={sessions}
          activeId={chat.sessionId}
          loading={sessionsLoading}
          draftActive={chat.sessionId === null && chat.items.length === 0}
          onDraftClick={() => {
            bumpComposerFocus();
            setOpen(false);
          }}
          onNew={() => {
            newSession();
            setOpen(false);
          }}
          onOpen={(id) => {
            void openSession(id)
              .then(() => refreshSessions())
              .catch(() => {});
            setOpen(false);
          }}
          onDelete={async (id) => {
            try {
              await deleteSession(id);
              toast.success("会话已删除");
            } catch {
              toast.error("删除失败");
            }
          }}
        />
      </aside>
    </div>
  );
}
