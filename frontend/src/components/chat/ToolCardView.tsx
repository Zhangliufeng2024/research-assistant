import { useState } from "react";
import type { ToolCard as ToolCardData } from "@/lib/types";

const TOOL_LABELS: Record<string, string> = {
  write_file: "写入文件",
  edit_file: "编辑文件",
  read_file: "读取文件",
  bash: "终端命令",
  run_python: "运行 Python",
};

function argsSummary(card: ToolCardData): string {
  const a = card.args;
  if (typeof a.file_path === "string" && a.file_path) return a.file_path;
  if (typeof a.command === "string" && a.command) return a.command;
  if (typeof a.code === "string" && a.code) return a.code.split("\n")[0];
  const keys = Object.keys(a);
  if (keys.length === 0) return "";
  return keys.map((k) => String(a[k])).join(" ").slice(0, 80);
}

function ToolGlyph({ tool }: { tool: string }) {
  const cls = "h-[15px] w-[15px]";
  if (tool.includes("file")) {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
        strokeLinecap="round" strokeLinejoin="round" className={cls} aria-hidden>
        <path d="M14.5 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7.5z" />
        <path d="M14 3v5h5" />
      </svg>
    );
  }
  if (tool === "bash") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
        strokeLinecap="round" strokeLinejoin="round" className={cls} aria-hidden>
        <polyline points="5 8 9 12 5 16" />
        <line x1="12" y1="17" x2="19" y2="17" />
      </svg>
    );
  }
  if (tool === "run_python") {
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
        strokeLinecap="round" strokeLinejoin="round" className={cls} aria-hidden>
        <polyline points="8 7 4 12 8 17" />
        <polyline points="16 7 20 12 16 17" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
      strokeLinecap="round" strokeLinejoin="round" className={cls} aria-hidden>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6 2.1 2.1m0-12.8-2.1 2.1M7.7 16.3l-2.1 2.1" />
    </svg>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "running") {
    return (
      <span className="inline-flex items-center gap-1.5 text-[11px] font-medium text-warn">
        <span className="h-3 w-3 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" />
        运行中
      </span>
    );
  }
  if (status === "error") {
    return (
      <span className="text-[11px] font-medium text-danger">✕ 出错</span>
    );
  }
  return <span className="text-[11px] font-medium text-ok">✓ 完成</span>;
}

/** 工具调用卡：状态徽标 + 参数摘要；点击展开完整参数与结果预览。 */
export function ToolCardView({
  card,
  onOpenFile,
}: {
  card: ToolCardData;
  onOpenFile?: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const summary = argsSummary(card);

  return (
    <div className="overflow-hidden rounded-xl border border-edge bg-surface">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left transition-colors hover:bg-surface-2"
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-2 text-ink-2">
          <ToolGlyph tool={card.tool} />
        </span>
        <span className="shrink-0 text-[13px] font-medium">
          {TOOL_LABELS[card.tool] || card.tool}
        </span>
        {summary && (
          <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] text-ink-3">
            {summary}
          </span>
        )}
        {!summary && <span className="flex-1" />}
        <StatusBadge status={card.status} />
      </button>

      {open && (
        <div className="space-y-2 border-t border-edge px-3.5 py-3">
          {Object.keys(card.args).length > 0 && (
            <div>
              <div className="mb-1 text-[11px] font-medium text-ink-3">参数</div>
              <pre className="overflow-x-auto rounded-lg bg-surface-2 p-2.5 font-mono text-[11.5px] leading-5">
                {JSON.stringify(card.args, null, 2)}
              </pre>
            </div>
          )}
          {card.preview && (
            <div>
              <div className="mb-1 text-[11px] font-medium text-ink-3">结果</div>
              <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-2.5 font-mono text-[11.5px] leading-5">
                {card.preview}
              </pre>
            </div>
          )}
        </div>
      )}

      {card.files.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-t border-edge px-3.5 py-2.5">
          {card.files.map((f) => (
            <button
              key={f.path}
              type="button"
              onClick={() => onOpenFile?.(f.path)}
              title={`预览 ${f.path}`}
              className="inline-flex max-w-full items-center gap-1 rounded-lg bg-accent-tint px-2 py-1 font-mono text-[11px] text-accent-hover transition-colors hover:brightness-95 dark:text-accent"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                strokeLinecap="round" strokeLinejoin="round" className="h-3 w-3 shrink-0" aria-hidden>
                <path d="M14.5 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7.5z" />
                <path d="M14 3v5h5" />
              </svg>
              <span className="truncate">{f.path}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
