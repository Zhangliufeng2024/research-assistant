import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { FilePreviewModal } from "@/components/chat/FilePreviewModal";
import type { PaperSummary } from "@/stores/taskStore";

/* ---------- 论文成果 ---------- */

const STATUS_BADGE: Record<string, { label: string; cls: string }> = {
  success: { label: "已定稿", cls: "bg-ok/10 text-ok" },
  partial: { label: "有草稿", cls: "bg-warn/10 text-warn" },
  empty: { label: "空目录", cls: "bg-surface-2 text-ink-3" },
};

function PapersTab() {
  const [papers, setPapers] = useState<PaperSummary[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .get<PaperSummary[]>("/api/papers")
      .then(setPapers)
      .catch(() => setPapers([]))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  async function del(name: string) {
    if (!window.confirm(`删除论文目录「${name}」？此操作不可恢复。`)) return;
    try {
      await api.del(`/api/papers/${encodeURIComponent(name)}`);
      load();
    } catch (e) {
      window.alert(`删除失败：${(e as Error).message}`);
    }
  }

  if (loading) return <div className="py-16 text-center text-sm text-ink-3">加载中…</div>;
  if (papers.length === 0) {
    return (
      <div className="py-16 text-center text-sm text-ink-3">
        还没有论文产出——到「任务」页发起一次文档生成。
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
      {papers.map((p) => {
        const badge = STATUS_BADGE[p.status] || STATUS_BADGE.empty;
        const title = p.title || p.topic || p.name;
        return (
          <div
            key={p.name}
            className="group rounded-2xl border border-edge bg-surface p-5 shadow-card transition-shadow hover:shadow-lg"
          >
            <div className="flex items-start gap-3">
              <span className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent-tint text-[15px]">
                📄
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="line-clamp-2 text-[14px] font-semibold leading-snug">{title}</h3>
                <div className="mt-1 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[11.5px] text-ink-3">
                  <span>{p.date || formatRelative(p.name.slice(0, 15))}</span>
                  {p.word_count != null && <span>· {p.word_count.toLocaleString()} 字</span>}
                  <span>· {p.figures_count} 图</span>
                  <span>· {p.citations_count} 引用</span>
                </div>
              </div>
              <span className={`shrink-0 rounded-lg px-2 py-1 text-[11px] font-medium ${badge.cls}`}>
                {badge.label}
              </span>
            </div>
            <div className="mt-3.5 flex items-center gap-2 border-t border-edge/60 pt-3">
              <a
                href={`/api/papers/${encodeURIComponent(p.name)}/export`}
                className="rounded-lg border border-edge px-2.5 py-1 text-[12px] transition-colors hover:bg-surface-2"
              >
                导出 ZIP
              </a>
              <button
                type="button"
                onClick={() => void del(p.name)}
                className="ml-auto rounded-lg px-2 py-1 text-[12px] text-ink-3 transition-colors hover:text-danger"
              >
                删除
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ---------- 工作区文件 ---------- */

interface TreeItem {
  name: string;
  path: string;
  type: "dir" | "file";
  size: number | null;
  mtime: number;
}

function fmtSize(n: number | null): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function FilesTab({ onOpenFile }: { onOpenFile: (path: string) => void }) {
  const [path, setPath] = useState("");
  const [items, setItems] = useState<TreeItem[]>([]);
  const [error, setError] = useState("");

  const load = useCallback((p: string) => {
    setError("");
    api
      .get<{ path: string; items: TreeItem[] }>(
        `/api/workspace/tree?path=${encodeURIComponent(p)}`,
      )
      .then((d) => {
        setPath(d.path);
        setItems(d.items);
      })
      .catch((e: Error) => setError(e.message || "加载失败"));
  }, []);

  useEffect(() => load(""), [load]);

  const crumbs = path ? path.split("/") : [];

  return (
    <div className="overflow-hidden rounded-2xl border border-edge bg-surface shadow-card">
      {/* 路径条 */}
      <div className="flex items-center gap-1 border-b border-edge px-4 py-2.5 text-[12.5px]">
        <button
          type="button"
          onClick={() => load("")}
          className={`rounded-md px-1.5 py-0.5 transition-colors hover:bg-surface-2 ${path ? "text-ink-2" : "font-medium text-accent"}`}
        >
          工作区根目录
        </button>
        {crumbs.map((c, i) => (
          <span key={i} className="flex items-center gap-1">
            <span className="text-ink-3">/</span>
            <button
              type="button"
              onClick={() => load(crumbs.slice(0, i + 1).join("/"))}
              className={`rounded-md px-1.5 py-0.5 transition-colors hover:bg-surface-2 ${
                i === crumbs.length - 1 ? "font-medium text-accent" : "text-ink-2"
              }`}
            >
              {c}
            </button>
          </span>
        ))}
      </div>

      {error && <div className="px-4 py-6 text-center text-sm text-danger">{error}</div>}
      {!error && items.length === 0 && (
        <div className="px-4 py-10 text-center text-sm text-ink-3">空目录</div>
      )}

      <ul>
        {items.map((it) => (
          <li key={it.path}>
            <button
              type="button"
              onClick={() =>
                it.type === "dir" ? load(it.path) : onOpenFile(it.path)
              }
              className="flex w-full items-center gap-3 border-b border-edge/40 px-4 py-2.5 text-left transition-colors last:border-0 hover:bg-surface-2"
            >
              <span className="w-4 shrink-0 text-center text-[13px]">
                {it.type === "dir" ? "📁" : "📄"}
              </span>
              <span className="min-w-0 flex-1 truncate text-[13.5px]">{it.name}</span>
              {it.type === "file" && (
                <>
                  <span className="shrink-0 font-mono text-[11px] text-ink-3">{fmtSize(it.size)}</span>
                  <span className="hidden shrink-0 text-[11px] text-ink-3 sm:block">
                    {formatRelative(it.mtime * 1000)}
                  </span>
                </>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 文库页：论文成果 + 工作区文件浏览。 */
export function PapersView() {
  const [tab, setTab] = useState<"papers" | "files">("papers");
  const [previewPath, setPreviewPath] = useState<string | null>(null);

  useEffect(() => {
    document.title = "研究助手 · 文库";
  }, []);

  return (
    <div className="mx-auto max-w-4xl space-y-4 px-6 py-6">
      <div className="flex gap-1 rounded-xl bg-surface-2 p-1" role="tablist">
        {(
          [
            ["papers", `论文成果`],
            ["files", `工作区文件`],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`flex-1 rounded-lg px-4 py-1.5 text-[13px] font-medium transition-all ${
              tab === key ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "papers" ? <PapersTab /> : <FilesTab onOpenFile={setPreviewPath} />}

      {previewPath && (
        <FilePreviewModal paths={[previewPath]} onClose={() => setPreviewPath(null)} />
      )}
    </div>
  );
}
