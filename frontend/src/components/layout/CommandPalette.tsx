/* 命令面板（阶段 4，设计文档 §4）：Ctrl/Cmd+K 打开。
 *
 * 数据源三合一（文档口径）：命令注册表（useHotkeys.buildCommands）+
 * 会话列表（chatStore）+ 项目对象/产物检索（沿用 WorkspaceSearch 的
 * /api/project/search 与 /api/search 管线，180ms 防抖）。
 * 模糊匹配走 paletteModel（fuse.js）；↑↓ 选择、Enter 执行、Esc 关闭。
 * 开关状态在 uiStore.paletteOpen —— 全局 Ctrl+K 由 useHotkeys 统一分发。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { sessionDisplayTitle } from "@/components/chat/sessionSearch";
import {
  mergeArtifactHits,
  searchHitPath,
  type ArtifactRow,
  type SearchHit,
} from "./workspaceSearchModel";
import { filterItems } from "./paletteModel";
import { visibleCommands, go } from "@/hooks/useHotkeys";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";

interface PaletteEntry {
  id: string;
  title: string;
  detail?: string;
  hotkey?: string;
  kind: "command" | "session" | "hit";
  run(): void;
}

const KIND_LABELS: Record<PaletteEntry["kind"], string> = {
  command: "命令",
  session: "会话",
  hit: "项目",
};

export function CommandPalette() {
  const open = useUiStore((s) => s.paletteOpen);
  const setOpen = useUiStore((s) => s.setPaletteOpen);
  const sessions = useChatStore((s) => s.sessions);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [highlight, setHighlight] = useState(0);
  const listRef = useRef<HTMLDivElement | null>(null);

  // 关闭即清空查询态，下次打开是干净的默认视图
  useEffect(() => {
    if (!open) {
      setQuery("");
      setHits([]);
      setHighlight(0);
    }
  }, [open]);

  // 项目对象检索：≥2 字符防抖 180ms（口径与原 WorkspaceSearch 一致）
  useEffect(() => {
    if (!open || query.trim().length < 2) {
      setHits([]);
      return;
    }
    const timer = window.setTimeout(() => {
      const q = encodeURIComponent(query.trim());
      void Promise.all([
        api.get<SearchHit[]>(`/api/project/search?q=${q}&limit=20`).catch(() => []),
        api
          .get<{ artifacts?: ArtifactRow[] }>(`/api/search?scope=artifacts&q=${q}&limit=8`)
          .then((r) => r.artifacts ?? [])
          .catch(() => [] as ArtifactRow[]),
      ]).then(([base, artifacts]) => setHits(mergeArtifactHits(base, artifacts)));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [open, query]);

  // 条目装配：命令 + 会话 + 检索命中，统一走 filterItems 模糊过滤
  const entries = useMemo<PaletteEntry[]>(() => {
    const cmds: PaletteEntry[] = visibleCommands().map((c) => ({
      id: c.id,
      title: c.title,
      hotkey: c.hotkey,
      kind: "command",
      run: c.run,
    }));
    const sess: PaletteEntry[] = sessions
      .filter((s) => !s.archived)
      .map((s) => ({
        id: `session:${s.id}`,
        title: sessionDisplayTitle(s),
        detail: "跳转到该会话",
        kind: "session",
        run: () => go(`/chat/${encodeURIComponent(s.id)}`),
      }));
    const searchHits: PaletteEntry[] = hits.map((h) => ({
      id: `hit:${h.kind}-${h.id}`,
      title: h.title || h.id,
      detail: h.detail || h.id,
      kind: "hit",
      run: () => go(searchHitPath(h)),
    }));
    return filterItems([...cmds, ...sess, ...searchHits], query);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, hits, sessions]);

  // 候选集变化后高亮回位，避免越界
  useEffect(() => {
    setHighlight(0);
  }, [query, entries.length]);

  // 高亮项滚入可视区（jsdom 等环境无 scrollIntoView，需守卫）
  useEffect(() => {
    const el = listRef.current
      ?.querySelector<HTMLElement>(`[data-entry-index="${highlight}"]`);
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ block: "nearest" });
    }
  }, [highlight]);

  if (!open) return null;

  const choose = (entry: PaletteEntry) => {
    entry.run();
    setOpen(false);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation(); // 只关面板，不落进全局 Esc 分发
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const delta = event.key === "ArrowDown" ? 1 : -1;
      setHighlight((cur) => {
        if (entries.length === 0) return 0;
        return (cur + delta + entries.length) % entries.length;
      });
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const entry = entries[highlight];
      if (entry) choose(entry);
    }
  };

  return (
    <div
      className="fixed inset-0 z-40 bg-black/20 p-4"
      data-testid="command-palette"
      onMouseDown={() => setOpen(false)}
    >
      <div
        role="dialog"
        aria-label="命令面板"
        className="mx-auto mt-[8vh] w-full max-w-2xl overflow-hidden rounded-2xl border border-edge bg-surface shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <input
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="搜索命令、会话与项目对象…（↑↓ 选择，Enter 执行，Esc 关闭）"
          className="w-full border-b border-edge bg-transparent px-4 py-3 text-sm outline-none"
        />
        <div ref={listRef} className="max-h-96 overflow-y-auto p-2">
          {entries.length === 0 ? (
            <div className="p-5 text-center text-xs text-ink-3">没有匹配的命令或对象</div>
          ) : (
            entries.map((entry, i) => (
              <button
                type="button"
                key={entry.id}
                data-entry-index={i}
                onClick={() => choose(entry)}
                onMouseEnter={() => setHighlight(i)}
                className={`flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors ${
                  i === highlight ? "bg-surface-2" : ""
                }`}
              >
                <span className="mt-0.5 rounded bg-accent-tint px-1.5 py-0.5 text-[10px] text-accent">
                  {KIND_LABELS[entry.kind]}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-xs font-medium">{entry.title}</span>
                  {entry.detail && (
                    <span className="mt-0.5 block truncate text-[11px] text-ink-3">
                      {entry.detail}
                    </span>
                  )}
                </span>
                {entry.hotkey && (
                  <kbd className="shrink-0 rounded border border-edge px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
                    {entry.hotkey}
                  </kbd>
                )}
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
