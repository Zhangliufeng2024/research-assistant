import { sessionTitle, formatRelative } from "@/lib/format";
import type { SessionSummary } from "@/lib/types";

/** 会话列表（二级栏）：新建 + 草稿行 + 按最近活跃排序的历史会话。
 * draftActive 时置顶渲染高亮草稿行（点击聚焦输入框），✚ 按钮同时置灰——
 * 「新会话」此刻就是草稿本身，避免重复入口（R12 P4）。 */
export function SessionList({
  sessions,
  activeId,
  loading,
  draftActive = false,
  onDraftClick,
  onNew,
  onOpen,
  onDelete,
}: {
  sessions: SessionSummary[];
  activeId: string | null;
  loading: boolean;
  /** 当前处于未发送的新会话状态。 */
  draftActive?: boolean;
  /** 点击草稿行：宿主聚焦输入框。 */
  onDraftClick?: () => void;
  onNew: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="px-3 pt-3">
        <button
          type="button"
          onClick={onNew}
          disabled={draftActive}
          title={draftActive ? "新会话草稿已在列表中" : undefined}
          className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-edge bg-surface px-3 py-2 text-[13px] font-medium shadow-sm transition-colors enabled:hover:border-accent/40 enabled:hover:text-accent-hover dark:enabled:hover:text-accent disabled:cursor-not-allowed disabled:opacity-45"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
            strokeLinecap="round" className="h-4 w-4" aria-hidden>
            <path d="M12 5v14M5 12h14" />
          </svg>
          新会话
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {draftActive && (
          <button
            type="button"
            onClick={onDraftClick}
            className="mb-1 block w-full rounded-xl bg-accent-tint px-3 py-2.5 text-left ring-1 ring-accent/30 transition-colors hover:bg-accent-tint/80"
            aria-label="回到未发送的新会话草稿"
          >
            <div className="truncate text-[13px] font-medium text-accent-hover dark:text-accent">
              新会话
              <span className="ml-1.5 rounded-md bg-surface px-1 py-px align-middle text-[10px] font-normal text-warn">
                未发送
              </span>
            </div>
            <div className="mt-0.5 text-[11px] text-ink-3">点击输入第一条消息</div>
          </button>
        )}
        {loading && !draftActive && sessions.length === 0 && (
          <div className="px-3 py-6 text-center text-[12px] text-ink-3">加载中…</div>
        )}
        {!loading && !draftActive && sessions.length === 0 && (
          <div className="px-3 py-6 text-center text-[12px] text-ink-3">
            还没有历史会话
          </div>
        )}
        {!loading && sessions.length === 0 && (
          <div className="px-3 py-6 text-center text-[12px] text-ink-3">
            还没有历史会话
          </div>
        )}
        {sessions.map((s) => {
          const active = s.id === activeId;
          return (
            <div
              key={s.id}
              className={`group relative mb-0.5 rounded-xl transition-colors ${
                active ? "bg-accent-tint" : "hover:bg-surface-2"
              }`}
            >
              <button
                type="button"
                onClick={() => onOpen(s.id)}
                className="block w-full px-3 py-2.5 pr-8 text-left"
              >
                <div
                  className={`truncate text-[13px] font-medium ${
                    active ? "text-accent-hover dark:text-accent" : "text-ink"
                  }`}
                >
                  {sessionTitle(s.title, s.last_message)}
                </div>
                <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-ink-3">
                  <span>{formatRelative(s.updated_at)}</span>
                  <span>·</span>
                  <span>{s.turns} 轮</span>
                </div>
              </button>
              <button
                type="button"
                title="删除会话"
                onClick={(e) => {
                  e.stopPropagation();
                  if (window.confirm(`删除会话「${sessionTitle(s.title, s.last_message)}」？此操作不可恢复。`)) {
                    onDelete(s.id);
                  }
                }}
                className="absolute right-2 top-2.5 hidden rounded-md p-1 text-ink-3 transition-colors hover:bg-surface hover:text-danger group-hover:block"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                  strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden>
                  <path d="M3 6h18" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                  <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
