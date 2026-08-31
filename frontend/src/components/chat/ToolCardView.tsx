import { useMemo, useState } from "react";
import { diffLines, diffStats, type DiffRow } from "@/lib/diff";
import type { ToolCard as ToolCardData } from "@/lib/types";
import { selectDebug, usePrefsStore } from "@/stores/prefsStore";

const TOOL_LABELS: Record<string, string> = {
  write_file: "写入文件",
  edit_file: "编辑文件",
  apply_patch: "批量编辑",
  read_file: "读取文件",
  bash: "终端命令",
  run_python: "运行 Python",
};

/** 方案 2b：从工具卡参数中提取「旧文 → 新文」的 diff 输入。
 * edit_file：old_string/new_string 单补丁；apply_patch：patches[] 多补丁。
 * 其余工具（写入/执行类）没有可比对的旧文，返回空。 */
function diffInputsFor(card: ToolCardData): { path: string; rows: DiffRow[] }[] {
  const a = card.args;
  if (
    card.tool === "edit_file" &&
    typeof a.old_string === "string" &&
    typeof a.new_string === "string"
  ) {
    const path = typeof a.file_path === "string" ? a.file_path : "";
    return [{ path, rows: diffLines(a.old_string, a.new_string) }];
  }
  if (card.tool === "apply_patch" && Array.isArray(a.patches)) {
    return (a.patches as unknown[])
      .filter(
        (p): p is Record<string, unknown> =>
          !!p &&
          typeof p === "object" &&
          typeof (p as Record<string, unknown>).old_string === "string" &&
          typeof (p as Record<string, unknown>).new_string === "string",
      )
      .map((p) => ({
        path: typeof p.file_path === "string" ? p.file_path : "",
        rows: diffLines(p.old_string as string, p.new_string as string),
      }));
  }
  return [];
}

/** 内联 diff 块：文件名 + 增删统计 + 行级着色预览（ 方案 2b）。 */
function DiffBlock({ path, rows }: { path: string; rows: DiffRow[] }) {
  const { added, removed } = diffStats(rows);
  return (
    <div>
      <div className="mb-1 flex items-baseline gap-2">
        <span className="min-w-0 truncate font-mono text-[11px] font-medium text-accent-hover dark:text-accent">
          {path || "(未命名)"}
        </span>
        <span className="shrink-0 font-mono text-[10.5px] text-ok">+{added}</span>
        <span className="shrink-0 font-mono text-[10.5px] text-danger">-{removed}</span>
      </div>
      <pre className="max-h-56 overflow-auto rounded-lg bg-surface-2 p-0 font-mono text-[11px] leading-5">
        {rows.map((r, i) => (
          <div
            key={i}
            className={`flex gap-0 ${
              r.type === "add"
                ? "bg-ok/10 text-ok"
                : r.type === "del"
                  ? "bg-danger/10 text-danger"
                  : "text-ink-3"
            }`}
          >
            <span className="w-5 shrink-0 select-none text-center opacity-70">
              {r.type === "add" ? "+" : r.type === "del" ? "-" : " "}
            </span>
            <span className="whitespace-pre-wrap break-all pr-2">{r.text || " "}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}

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

/** 工具调用卡：状态徽标 + 参数摘要；点击展开 diff 与结果预览。
 * R17 思考链分级：完整参数 JSON 属 L2——仅「调试」档展示（此前展开即全文
 * JSON.stringify，信噪比过低）；简洁/标准档展开区保留 diff + 结果预览。 */
export function ToolCardView({
  card,
  onOpenFile,
}: {
  card: ToolCardData;
  onOpenFile?: (path: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const debug = usePrefsStore(selectDebug);
  const summary = argsSummary(card);
  // P2-7：diff 的 LCS 是 O(n·m)（上限 2000×2000 ≈ 16MB DP 表）。此前在
  // render 内联调用——卡片展开期间，ChatView 的 1s nowTick 每次触发都会
  // 对同一 card 重算一遍，展开一张大 apply_patch 卡即主线程长阻塞。
  // useMemo 按引用缓存：card 内容不变就绝不重算。
  const diffInputs = useMemo(() => diffInputsFor(card), [card]);

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
          {diffInputs.map((d, i) => (
            <DiffBlock key={`${d.path}-${i}`} path={d.path} rows={d.rows} />
          ))}
          {debug && Object.keys(card.args).length > 0 && (
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
