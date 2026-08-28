import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import type { SessionSummary } from "@/lib/types";
import { useChatStore } from "@/stores/chatStore";
import { toast } from "@/stores/toastStore";
import {
  ARCHIVED_SESSIONS_KEY,
  loadArchivedIds,
} from "@/components/chat/sessionArchive";
import { groupSessions } from "@/components/chat/sessionGroups";
import {
  filterSessions,
  sessionDisplayTitle,
} from "@/components/chat/sessionSearch";

const RENAME_MAX_LEN = 80; // 与后端 create/rename 的标题截断口径一致
const DELETE_CONFIRM_MS = 3_000; // 两段式删除：二次点击的确认窗口
const UNDO_BAR_MS = 8_000; // 归档撤销条的停留时长

/** 会话列表（二级栏）：新建 + 搜索 + 草稿行 + 按最近活跃排序的历史会话。
 * draftActive 时置顶渲染高亮草稿行（点击聚焦输入框），✚ 按钮同时置灰——
 * 「新会话」此刻就是草稿本身，避免重复入口（R12 P4）。
 *
 * Top10 自包含增强（props 接口不变，宿主零改动）：
 * - A 搜索：顶部输入框，客户端过滤展示标题；↑↓ 高亮 + Enter 打开；
 * - B 重命名：hover 出铅笔钮 → 就地 input，乐观更新 + 失败回滚，
 *   成功后经既有 refreshSessions 让 chatStore 的列表同步；
 * - C 归档：本地隐藏方案（localStorage ra.archived-sessions.v1），
 *   底部「已归档 (N)」折叠区可取消归档；撤销条替代带按钮的 toast；
 * - D 删除两段式确认：首点变红色「确认删除？」态，3s 内再点才执行。
 */
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
  // ---- A 搜索 -----------------------------------------------------------
  const [query, setQuery] = useState("");
  const [highlight, setHighlight] = useState(-1);
  const searchRef = useRef<HTMLInputElement>(null);
  const rowRefs = useRef(new Map<string, HTMLDivElement>());

  // ---- B 重命名（乐观覆盖层；成功后再经 refreshSessions 对齐 store）------
  const [renaming, setRenaming] = useState<{ id: string; value: string } | null>(
    null,
  );
  const [titleOverrides, setTitleOverrides] = useState<Record<string, string>>(
    {},
  );

  // ---- C 归档/置顶（R17：服务端持久化 platform.sqlite3，跨端可见）--------
  // 归档集合直接派生自服务端下发的 archived 标志；localStorage 旧方案
  // 仅在首次挂载时做一次性迁移（见下方 useEffect）。
  const [showArchived, setShowArchived] = useState(false);
  const [pendingArchive, setPendingArchive] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const migratedRef = useRef(false);

  // ---- D 两段式删除确认 ---------------------------------------------------
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const deleteTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  /** 回合运行中的会话 id（chatStore 只读订阅）：归档/重命名防呆只针对它。 */
  const busySessionId = useChatStore((s) =>
    s.chat.phase === "running" ? s.chat.sessionId : null,
  );

  useEffect(
    () => () => {
      if (undoTimer.current) clearTimeout(undoTimer.current);
      if (deleteTimer.current) clearTimeout(deleteTimer.current);
    },
    [],
  );

  // R17 一次性迁移：localStorage 旧归档 id 上报服务端后清除本地 key。
  // 标记键防重复执行；失败静默（下次挂载重试），绝不影响列表渲染。
  useEffect(() => {
    if (migratedRef.current || sessions.length === 0) return;
    migratedRef.current = true;
    try {
      const MARK = "ra.flags-migrated.v1";
      if (localStorage.getItem(MARK)) return;
      const legacyIds = loadArchivedIds();
      localStorage.setItem(MARK, "1");
      if (legacyIds.length === 0) return;
      const known = new Set(sessions.map((s) => s.id));
      const pending = legacyIds.filter((id) => known.has(id));
      if (pending.length === 0) {
        localStorage.removeItem(ARCHIVED_SESSIONS_KEY);
        return;
      }
      void Promise.allSettled(
        pending.map((id) =>
          api.post(`/api/chat/sessions/${encodeURIComponent(id)}/flags`, {
            archived: true,
          }),
        ),
      ).then(() => {
        localStorage.removeItem(ARCHIVED_SESSIONS_KEY);
        useChatStore.getState().refreshSessions().catch(() => {});
      });
    } catch {
      /* 隐私模式等：放弃迁移，不影响使用 */
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions]);

  // 重命名覆盖层并入摘要：渲染 / 过滤 / 撤销条共用同一标题口径
  const decorated = useMemo(
    () =>
      sessions.map((s) =>
        titleOverrides[s.id] !== undefined
          ? { ...s, title: titleOverrides[s.id]! }
          : s,
      ),
    [sessions, titleOverrides],
  );
  const archivedSet = useMemo(
    () => new Set(decorated.filter((s) => s.archived).map((s) => s.id)),
    [decorated],
  );
  const visible = useMemo(
    () => filterSessions(decorated.filter((s) => !archivedSet.has(s.id)), query),
    [decorated, archivedSet, query],
  );
  const archivedList = useMemo(
    () => decorated.filter((s) => archivedSet.has(s.id)),
    [decorated, archivedSet],
  );
  // R17 时间分组：置顶/今天/本周/更早（仅渲染分段；visible 保持扁平供键盘导航）
  const groups = useMemo(() => groupSessions(visible), [visible]);
  const archivedShown = showArchived ? filterSessions(archivedList, query) : [];
  const indexOfId = useMemo(
    () => new Map(visible.map((s, i) => [s.id, i])),
    [visible],
  );
  const hi =
    visible.length > 0 ? Math.min(highlight, visible.length - 1) : -1;

  // 键盘高亮跟随滚动（nearest：不打断用户当前的浏览位置）
  useEffect(() => {
    if (hi >= 0) {
      rowRefs.current.get(visible[hi]?.id ?? "")?.scrollIntoView({
        block: "nearest",
      });
    }
  }, [hi, visible]);

  // ---- 事件处理 -----------------------------------------------------------

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      setQuery("");
      setHighlight(-1);
      searchRef.current?.blur();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (visible.length > 0) setHighlight(Math.min(hi + 1, visible.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight(Math.max(hi - 1, 0));
    } else if (e.key === "Enter" && hi >= 0) {
      const target = visible[hi];
      if (!target) return;
      setHighlight(-1);
      onOpen(target.id);
      searchRef.current?.blur();
    }
  };

  const startRename = (s: SessionSummary) => {
    setConfirmDeleteId(null);
    setRenaming({ id: s.id, value: sessionDisplayTitle(decorated.find((x) => x.id === s.id) ?? s).slice(0, RENAME_MAX_LEN) });
  };

  const submitRename = async () => {
    const editing = renaming;
    if (!editing) return;
    setRenaming(null); // 先退出编辑态：blur/Enter 双触发在此自然幂等
    const next = editing.value.trim().slice(0, RENAME_MAX_LEN);
    const target = decorated.find((s) => s.id === editing.id);
    if (!target || !next || next === sessionDisplayTitle(target)) return; // 空名/未变：静默取消

    if (busySessionId === editing.id) {
      toast.info("生成中的会话暂不能重命名——请等回合结束后再试");
      return;
    }
    const prevTitle = sessionDisplayTitle(target);
    setTitleOverrides((m) => ({ ...m, [editing.id]: next })); // 乐观更新
    try {
      await api.patch(`/api/chat/sessions/${encodeURIComponent(editing.id)}`, {
        title: next,
      });
      toast.success("已重命名");
      // 经既有刷新机制同步 chatStore.sessions（本组件不改 store）
      useChatStore.getState().refreshSessions().catch(() => {});
    } catch (exc) {
      // 回滚显示：恢复到乐观前的标题（可能是更早的覆盖值）
      setTitleOverrides((m) => {
        const nextMap = { ...m };
        const original = sessionDisplayTitle(target);
        if (prevTitle === original) delete nextMap[editing.id];
        else nextMap[editing.id] = prevTitle;
        return nextMap;
      });
      toast.error(
        `重命名失败：${exc instanceof Error ? exc.message : "未知错误"}`,
      );
    }
  };

  const handleDeleteClick = (s: SessionSummary) => {
    if (confirmDeleteId === s.id) {
      if (deleteTimer.current) clearTimeout(deleteTimer.current);
      setConfirmDeleteId(null);
      // 成功与否的反馈由宿主的 onDelete 负责（ChatView 已有「会话已删除」提示）
      onDelete(s.id);
      return;
    }
    setConfirmDeleteId(s.id); // 首击：进入红色确认态，超时自动回弹
    if (deleteTimer.current) clearTimeout(deleteTimer.current);
    deleteTimer.current = setTimeout(
      () => setConfirmDeleteId(null),
      DELETE_CONFIRM_MS,
    );
  };

  /** R17：标志位写服务端，随后经 refreshSessions 对齐列表（失败提示并回滚靠刷新）。 */
  const postFlags = async (
    id: string,
    flags: { pinned?: boolean; archived?: boolean },
  ) => {
    try {
      await api.post(
        `/api/chat/sessions/${encodeURIComponent(id)}/flags`,
        flags,
      );
      useChatStore.getState().refreshSessions().catch(() => {});
      return true;
    } catch (exc) {
      toast.error(
        `操作失败：${exc instanceof Error ? exc.message : "未知错误"}`,
      );
      return false;
    }
  };

  const handleArchive = (s: SessionSummary) => {
    if (busySessionId === s.id) {
      toast.info("生成中的会话不能归档——请等回合结束后再试");
      return;
    }
    void postFlags(s.id, { archived: true });
    if (renaming?.id === s.id) setRenaming(null);
    setPendingArchive({ id: s.id, title: sessionDisplayTitle(s) });
    if (undoTimer.current) clearTimeout(undoTimer.current);
    undoTimer.current = setTimeout(() => setPendingArchive(null), UNDO_BAR_MS);
  };

  const handleUnarchive = (id: string) => {
    void postFlags(id, { archived: false });
    if (pendingArchive?.id === id) {
      if (undoTimer.current) clearTimeout(undoTimer.current);
      setPendingArchive(null);
    }
  };

  const handleTogglePin = (s: SessionSummary) => {
    void postFlags(s.id, { pinned: !s.pinned });
  };

  const refFor = (id: string) => (el: HTMLDivElement | null) => {
    if (el) rowRefs.current.set(id, el);
    else rowRefs.current.delete(id);
  };

  // ---- 渲染 ---------------------------------------------------------------

  const noMatch = query.trim() !== "" && visible.length === 0;

  return (
    <div className="flex h-full flex-col">
      <div className="space-y-2 px-3 pt-3">
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

        {/* 搜索框（A）：Esc 清空并失焦；有关键字时显示清空钮 */}
        <div className="relative">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.75" strokeLinecap="round"
            className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3"
            aria-hidden>
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            ref={searchRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setHighlight(e.target.value.trim() ? 0 : -1);
            }}
            onKeyDown={handleSearchKeyDown}
            placeholder="搜索会话…"
            aria-label="搜索会话"
            className="w-full rounded-xl border border-edge bg-surface py-1.5 pl-8 pr-7 text-[12.5px] text-ink outline-none transition-colors placeholder:text-ink-3 focus:border-accent/50"
          />
          {query !== "" && (
            <button
              type="button"
              title="清空搜索"
              aria-label="清空搜索"
              onClick={() => {
                setQuery("");
                setHighlight(-1);
                searchRef.current?.focus();
              }}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="1.75" strokeLinecap="round"
                className="h-3.5 w-3.5" aria-hidden>
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
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
        {!loading && !draftActive && sessions.length === 0 && (
          <div className="px-3 py-6 text-center text-[12px] text-ink-3">
            还没有历史会话
          </div>
        )}
        {loading && !draftActive && sessions.length === 0 && (
          <div className="px-3 py-6 text-center text-[12px] text-ink-3">
            加载中…
          </div>
        )}
        {/* 搜索无命中：明确空态而非空白（A） */}
        {!loading && sessions.length > 0 && noMatch && visible.length === 0 && (
          <div className="px-3 py-6 text-center text-[12px] text-ink-3">
            无匹配会话
          </div>
        )}
        {/* 无关键字但全部已归档 */}
        {!loading &&
          sessions.length > 0 &&
          query.trim() === "" &&
          visible.length === 0 &&
          archivedList.length > 0 && (
            <div className="px-3 py-6 text-center text-[12px] text-ink-3">
              全部会话已归档
            </div>
          )}

        {groups.map((g) => (
          <div key={g.key}>
            <div className="px-3 pb-0.5 pt-2 text-[10.5px] font-medium uppercase tracking-wide text-ink-3">
              {g.label}
            </div>
            {g.items.map((s) => (
              <SessionItem
                key={s.id}
                session={s}
                title={sessionDisplayTitle(s)}
                active={s.id === activeId}
                highlighted={indexOfId.get(s.id) === hi}
                running={busySessionId === s.id}
                editingValue={renaming?.id === s.id ? renaming.value : null}
                confirmingDelete={confirmDeleteId === s.id}
                archived={false}
                onRenameInput={(value) =>
                  setRenaming((r) => (r ? { ...r, value } : r))
                }
                onSubmitRename={() => void submitRename()}
                onCancelRename={() => setRenaming(null)}
                onStartRename={startRename}
                onOpen={onOpen}
                onToggleArchive={handleArchive}
                onTogglePin={handleTogglePin}
                onDeleteClick={handleDeleteClick}
                refFn={refFor(s.id)}
              />
            ))}
          </div>
        ))}

        {/* 归档撤销条（C）：toast 不支持携带按钮，用列表内临时条实现「已归档 + 撤销」 */}
        {pendingArchive && (
          <div className="mb-1 mt-1 flex items-center justify-between gap-2 rounded-xl border border-edge bg-surface px-2.5 py-1.5 shadow-sm">
            <span className="truncate text-[11.5px] text-ink-2">
              已归档「{pendingArchive.title}」
            </span>
            <button
              type="button"
              onClick={() => handleUnarchive(pendingArchive.id)}
              className="shrink-0 rounded-md px-1.5 py-0.5 text-[11.5px] font-medium text-accent-hover transition-colors hover:bg-accent-tint dark:text-accent"
            >
              撤销
            </button>
          </div>
        )}

        {/* 已归档折叠区（C） */}
        {archivedList.length > 0 && (
          <>
            <button
              type="button"
              onClick={() => setShowArchived((v) => !v)}
              aria-expanded={showArchived}
              className="mt-1 flex w-full items-center gap-1.5 rounded-lg px-2 py-1.5 text-[11.5px] text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
                className={`h-3 w-3 transition-transform ${showArchived ? "rotate-90" : ""}`}
                aria-hidden>
                <path d="m9 18 6-6-6-6" />
              </svg>
              已归档 ({archivedList.length})
            </button>
            {showArchived &&
              (archivedShown.length > 0 ? (
                archivedShown.map((s) => (
                  <SessionItem
                    key={s.id}
                    session={s}
                    title={sessionDisplayTitle(s)}
                    active={s.id === activeId}
                    highlighted={false}
                    dimmed
                    running={busySessionId === s.id}
                    editingValue={
                      renaming?.id === s.id ? renaming.value : null
                    }
                    confirmingDelete={confirmDeleteId === s.id}
                    archived
                    onRenameInput={(value) =>
                      setRenaming((r) => (r ? { ...r, value } : r))
                    }
                    onSubmitRename={() => void submitRename()}
                    onCancelRename={() => setRenaming(null)}
                    onStartRename={startRename}
                    onOpen={onOpen}
                    onToggleArchive={(target) => handleUnarchive(target.id)}
                    onTogglePin={handleTogglePin}
                    onDeleteClick={handleDeleteClick}
                    refFn={refFor(`archived-${s.id}`)}
                  />
                ))
              ) : (
                query.trim() !== "" && (
                  <div className="px-3 py-2 text-center text-[11px] text-ink-3">
                    无匹配的已归档会话
                  </div>
                )
              ))}
          </>
        )}
      </div>
    </div>
  );
}

/* ---------- 单条会话行 ---------- */

function IconButton({
  title,
  danger = false,
  onClick,
  children,
}: {
  title: string;
  danger?: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`rounded-md p-1 transition-colors ${
        danger
          ? "text-ink-3 hover:bg-danger/10 hover:text-danger"
          : "text-ink-3 hover:bg-surface-2 hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

/** 单条会话行：编辑态时标题区变为就地 input（Enter 提交 / Esc 取消 / 失焦提交）。 */
function SessionItem({
  session,
  title,
  active,
  highlighted,
  dimmed = false,
  running,
  editingValue,
  confirmingDelete,
  archived,
  onRenameInput,
  onSubmitRename,
  onCancelRename,
  onStartRename,
  onOpen,
  onToggleArchive,
  onTogglePin,
  onDeleteClick,
  refFn,
}: {
  session: SessionSummary;
  title: string;
  active: boolean;
  highlighted: boolean;
  /** 已归档条目的灰化态。 */
  dimmed?: boolean;
  running: boolean;
  /** 非 null 表示该行处于就地重命名编辑态（值为输入框当前内容）。 */
  editingValue: string | null;
  confirmingDelete: boolean;
  archived: boolean;
  onRenameInput: (value: string) => void;
  onSubmitRename: () => void;
  onCancelRename: () => void;
  onStartRename: (s: SessionSummary) => void;
  onOpen: (id: string) => void;
  /** 主列表传归档、归档区传取消归档（同一位置的互逆操作）。 */
  onToggleArchive: (s: SessionSummary) => void;
  /** R17：置顶切换（服务端持久化）。 */
  onTogglePin: (s: SessionSummary) => void;
  onDeleteClick: (s: SessionSummary) => void;
  refFn: (el: HTMLDivElement | null) => void;
}) {
  return (
    <div
      ref={refFn}
      className={`group relative mb-0.5 rounded-xl transition-colors ${
        active
          ? "bg-accent-tint"
          : highlighted
            ? "bg-surface-2 ring-1 ring-accent/40"
            : "hover:bg-surface-2"
      } ${dimmed ? "opacity-55" : ""}`}
    >
      {editingValue !== null ? (
        /* 编辑态：就地重命名输入框 */
        <div className="w-full px-3 py-2 pr-6">
          <input
            autoFocus
            value={editingValue}
            maxLength={RENAME_MAX_LEN}
            aria-label="重命名会话"
            onChange={(e) => onRenameInput(e.target.value)}
            onBlur={onSubmitRename}
            onKeyDown={(e) => {
              e.stopPropagation();
              if (e.key === "Enter") {
                e.preventDefault();
                onSubmitRename();
              } else if (e.key === "Escape") {
                e.preventDefault();
                onCancelRename();
              }
            }}
            className="w-full rounded-lg border border-accent/40 bg-canvas px-2 py-1 text-[13px] font-medium text-ink outline-none transition-colors focus:border-accent"
          />
          <div className="mt-1 flex items-center gap-2 text-[11px] text-ink-3">
            <span>Enter 提交 · Esc 取消</span>
            {running && <span className="text-warn">回合生成中</span>}
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => onOpen(session.id)}
          className="block w-full px-3 py-2.5 pr-8 text-left"
        >
          <div
            className={`truncate text-[13px] font-medium ${
              active
                ? "text-accent-hover dark:text-accent"
                : dimmed
                  ? "text-ink-3"
                  : "text-ink"
            }`}
            title={title}
          >
            {title}
            {session.pinned && (
              <svg viewBox="0 0 24 24" fill="currentColor" stroke="none"
                className="ml-1.5 inline-block h-3 w-3 align-middle text-accent"
                aria-label="已置顶" role="img">
                <path d="M16 3a1 1 0 0 1 .8.4l3 4A1 1 0 0 1 19 9h-2v6l2 5a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1l2-5V9H5a1 1 0 0 1-.8-1.6l3-4A1 1 0 0 1 8 3Z" transform="rotate(45 12 12)" />
              </svg>
            )}
            {running && (
              <span
                className="ml-1.5 inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-warn align-middle"
                title="回合生成中"
              />
            )}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[11px] text-ink-3">
            <span>{formatRelative(session.updated_at)}</span>
            <span>·</span>
            <span>{session.turns} 轮</span>
            {(session.derived_run_count ?? 0) > 0 && (
              <>
                <span>·</span>
                <span
                  className="inline-flex items-center gap-0.5 rounded-md bg-accent-tint px-1 py-px text-[10px] font-medium text-accent-hover dark:text-accent"
                  title={`本会话派生了 ${session.derived_run_count} 个后台任务（见任务中心）`}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                    className="h-2.5 w-2.5" aria-hidden>
                    <path d="M12 2v4m0 12v4M2 12h4m12 0h4" />
                    <circle cx="12" cy="12" r="3" />
                  </svg>
                  任务 {session.derived_run_count}
                </span>
              </>
            )}
          </div>
        </button>
      )}

      {/* hover 操作簇：编辑态隐藏，避免误触 */}
      {editingValue === null && (
        <div className="absolute right-1.5 top-1.5 z-10 hidden items-center gap-0.5 rounded-lg border border-edge bg-surface p-0.5 shadow-sm group-hover:flex">
          {confirmingDelete ? (
            <button
              type="button"
              title="再次点击确认删除（3 秒内有效）"
              onClick={(e) => {
                e.stopPropagation();
                onDeleteClick(session);
              }}
              className="rounded-md bg-danger px-1.5 py-1 text-[11px] font-semibold leading-none text-canvas transition-colors hover:bg-danger/85"
            >
              确认删除？
            </button>
          ) : (
            <>
              <IconButton
                title={session.pinned ? "取消置顶" : "置顶"}
                onClick={() => onTogglePin(session)}
              >
                <svg viewBox="0 0 24 24"
                  fill={session.pinned ? "currentColor" : "none"}
                  stroke="currentColor"
                  strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
                  className={`h-3.5 w-3.5 ${session.pinned ? "text-accent" : ""}`}
                  aria-hidden>
                  <path d="M12 17v5" />
                  <path d="M9 10.7a2 2 0 0 1-1-1.7V5h8v4a2 2 0 0 1-1 1.7L12 13Z" />
                  <path d="M7 3h10" />
                </svg>
              </IconButton>
              <IconButton
                title="重命名"
                onClick={() => onStartRename(session)}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
                  className="h-3.5 w-3.5" aria-hidden>
                  <path d="M12 20h9" />
                  <path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z" />
                </svg>
              </IconButton>
              <IconButton
                title={archived ? "取消归档" : "归档"}
                onClick={() => onToggleArchive(session)}
              >
                {archived ? (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
                    className="h-3.5 w-3.5" aria-hidden>
                    <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
                    <path d="M3 3v5h5" />
                  </svg>
                ) : (
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
                    className="h-3.5 w-3.5" aria-hidden>
                    <rect x="3" y="4" width="18" height="4" rx="1" />
                    <path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8" />
                    <path d="M10 12h4" />
                  </svg>
                )}
              </IconButton>
              <IconButton
                title="删除会话"
                danger
                onClick={() => onDeleteClick(session)}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
                  className="h-3.5 w-3.5" aria-hidden>
                  <path d="M3 6h18" />
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                  <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </IconButton>
            </>
          )}
        </div>
      )}
    </div>
  );
}
