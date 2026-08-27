import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface ChangeRecord {
  id: string;
  path: string;
  tool: string;
  created_at: number;
  status: string;
  size_before: number;
  size_after: number;
  binary?: boolean;
  diff?: string;
}

export function ChangesView() {
  const [changes, setChanges] = useState<ChangeRecord[]>([]);
  const [selected, setSelected] = useState<ChangeRecord | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => api.get<ChangeRecord[]>("/api/workspace/changes").then(setChanges);

  useEffect(() => {
    document.title = "研究助手 · 变更审阅";
    refresh().catch(() => {});
  }, []);

  async function open(change: ChangeRecord) {
    const detail = await api.get<ChangeRecord>(
      `/api/workspace/changes/${encodeURIComponent(change.id)}`,
    );
    setSelected(detail);
  }

  async function restore() {
    if (!selected) return;
    setBusy(true);
    try {
      await api.post(`/api/workspace/changes/${encodeURIComponent(selected.id)}/restore`, {
        side: "before",
      });
      setSelected(null);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-80 shrink-0 overflow-y-auto border-r border-edge bg-canvas p-3">
        <div className="mb-3 flex items-center justify-between px-1">
          <div>
            <h1 className="text-[15px] font-semibold">产物变更</h1>
            <p className="mt-0.5 text-[11px] text-ink-3">Agent 文件工具的可恢复历史</p>
          </div>
          <button className="text-[12px] text-accent" onClick={() => void refresh()}>刷新</button>
        </div>
        <div className="space-y-2">
          {changes.map((change) => (
            <button
              key={change.id}
              type="button"
              onClick={() => void open(change)}
              className={`w-full rounded-xl border p-3 text-left transition-colors ${
                selected?.id === change.id ? "border-accent/60 bg-accent-tint" : "border-edge bg-surface hover:border-accent/30"
              }`}
            >
              <div className="truncate text-[12.5px] font-medium">{change.path}</div>
              <div className="mt-1 flex gap-2 text-[10.5px] text-ink-3">
                <span>{change.tool}</span>
                <span>{new Date(change.created_at * 1000).toLocaleString()}</span>
              </div>
            </button>
          ))}
          {changes.length === 0 && (
            <div className="rounded-xl border border-dashed border-edge p-6 text-center text-[12px] text-ink-3">
              暂无由 Agent 文件工具产生的变更
            </div>
          )}
        </div>
      </aside>
      <main className="min-w-0 flex-1 overflow-auto p-5">
        {selected ? (
          <div className="mx-auto max-w-5xl">
            <div className="mb-4 flex items-center gap-3">
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-[15px] font-semibold">{selected.path}</h2>
                <p className="text-[11px] text-ink-3">{selected.tool} · {selected.id}</p>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void restore()}
                className="rounded-lg border border-edge px-3 py-1.5 text-[12px] font-medium text-danger hover:bg-surface-2 disabled:opacity-50"
              >
                {busy ? "恢复中…" : "撤销此变更"}
              </button>
            </div>
            {selected.binary ? (
              <div className="rounded-xl border border-edge bg-surface p-6 text-sm text-ink-2">
                二进制文件无法显示文本差异，但仍可恢复到变更前版本。
              </div>
            ) : (
              <pre className="overflow-auto rounded-xl border border-edge bg-surface p-4 font-mono text-[12px] leading-5">
                {selected.diff || "文件内容没有文本差异。"}
              </pre>
            )}
          </div>
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-ink-3">
            从左侧选择一次变更，查看 diff 或执行恢复。
          </div>
        )}
      </main>
    </div>
  );
}
