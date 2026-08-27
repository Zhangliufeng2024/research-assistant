/* 顶栏全局搜索（Ctrl+K）（R15：自 App.tsx 抽出 + 键盘层）。
 *
 * 交互：Ctrl/Cmd+K 开、Esc 关、180ms 防抖搜 /api/project/search；
 * 键盘层新增——↑↓ 循环移动高亮（scrollIntoView nearest）、Enter 打开
 * 高亮项；空结果 / 输入中 Enter 不误触。高亮项同时支持悬停同步与
 * bg-surface-2 视觉态。
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { IconBell } from "@/components/icons";
import { api } from "@/lib/api";
import { usePendingApprovalCount } from "@/stores/approvalSignal";
import {
  moveHighlight,
  pickEnterIndex,
  SEARCH_KIND_LABELS,
  searchHitPath,
  type SearchHit,
} from "./workspaceSearchModel";

/** 顶栏右侧通知中心入口（R15 自侧栏撤出后的替代路径）。 */
function NotificationsButton() {
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
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [highlight, setHighlight] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open || query.trim().length < 2) {
      setHits([]);
      return;
    }
    const timer = window.setTimeout(
      () =>
        void api
          .get<SearchHit[]>(`/api/project/search?q=${encodeURIComponent(query.trim())}&limit=20`)
          .then(setHits)
          .catch(() => setHits([])),
      180,
    );
    return () => window.clearTimeout(timer);
  }, [open, query]);

  // 候选集或关键词变化后高亮回到首条，避免残留越界索引
  useEffect(() => {
    setHighlight(0);
  }, [query, hits]);

  // 高亮项滚入可视区（block:nearest 不打扰当前滚动位置）
  useEffect(() => {
    listRef.current
      ?.querySelector<HTMLElement>(`[data-hit-index="${highlight}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [highlight]);

  const choose = (hit: SearchHit) => {
    navigate(searchHitPath(hit));
    setOpen(false);
    setQuery("");
  };

  const hasQuery = query.trim().length >= 2;

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const delta = event.key === "ArrowDown" ? 1 : -1;
      setHighlight((cur) => moveHighlight(cur, delta, hits.length));
      return;
    }
    if (event.key === "Enter") {
      // 空结果 / 输入中：只吞掉默认行为，不关闭不导航
      const idx = pickEnterIndex(highlight, hits.length);
      if (idx === null) {
        event.preventDefault();
        return;
      }
      const hit = hits[idx];
      if (hit) choose(hit);
    }
  };

  return (
    <>
      <div className="sticky top-0 z-20 flex h-12 items-center justify-between border-b border-edge bg-canvas/95 px-5 backdrop-blur">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex w-full max-w-md items-center gap-2 rounded-lg border border-edge bg-surface px-3 py-1.5 text-left text-xs text-ink-3 hover:border-accent/40"
        >
          <span className="text-sm">⌕</span>
          <span>搜索项目中的线程、资料、主张和产物…</span>
          <kbd className="ml-auto rounded border border-edge px-1.5 py-0.5 font-mono text-[10px]">Ctrl K</kbd>
        </button>
        <div className="ml-4 flex shrink-0 items-center gap-2">
          <NotificationsButton />
          <span className="hidden text-[11px] text-ink-3 md:block">统一科研工作空间</span>
        </div>
      </div>

      {open && (
        <div className="fixed inset-0 z-40 bg-black/20 p-4" onMouseDown={() => setOpen(false)}>
          <div
            className="mx-auto mt-[8vh] w-full max-w-2xl overflow-hidden rounded-2xl border border-edge bg-surface shadow-2xl"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={onKeyDown}
              placeholder="搜索项目对象…（↑↓ 选择，Enter 打开）"
              className="w-full border-b border-edge bg-transparent px-4 py-3 text-sm outline-none"
            />
            <div ref={listRef} className="max-h-96 overflow-y-auto p-2">
              {!hasQuery ? (
                <div className="p-5 text-center text-xs text-ink-3">
                  输入至少两个字符开始搜索 · Esc 关闭
                </div>
              ) : hits.length === 0 ? (
                <div className="p-5 text-center text-xs text-ink-3">没有匹配的项目对象</div>
              ) : (
                hits.map((hit, i) => (
                  <button
                    type="button"
                    key={`${hit.kind}-${hit.id}`}
                    data-hit-index={i}
                    onClick={() => choose(hit)}
                    onMouseEnter={() => setHighlight(i)}
                    className={`flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors ${
                      i === highlight ? "bg-surface-2" : ""
                    }`}
                  >
                    <span className="mt-0.5 rounded bg-accent-tint px-1.5 py-0.5 text-[10px] text-accent">
                      {SEARCH_KIND_LABELS[hit.kind] || hit.kind}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-medium">{hit.title || hit.id}</span>
                      <span className="mt-0.5 block truncate text-[11px] text-ink-3">
                        {hit.detail || hit.id}
                      </span>
                    </span>
                  </button>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
