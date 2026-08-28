/* R17 思考链显示（L1 级）：思考/planner 直播的折叠容器。
 *
 * 显示策略（docs/plans/2026-08-28-refactor-plan-detailed.md §1.2）：
 * - 默认折叠为一行摘要（图标 + 标题 + 字数/状态），点击展开；
 * - standard 档：运行中自动展开当前进行中的思考块，完成自动折回；
 * - debug 档：默认展开；
 * - 长内容折叠态只露首行，全文在展开区滚动查看。
 */
import { useEffect, useRef, useState } from "react";
import { usePrefsStore } from "@/stores/prefsStore";

export function ThinkingBlock({
  text,
  running,
  variant = "thought",
}: {
  text: string;
  /** 所属回合仍在运行（标题后转圈，standard 档自动展开）。 */
  running: boolean;
  /** thought=模型思考；plan=planner 规划直播。 */
  variant?: "thought" | "plan";
}) {
  const verbosity = usePrefsStore((s) => s.verbosity);
  const [open, setOpen] = useState(verbosity === "debug");
  const userToggled = useRef(false);

  // standard 档：运行中自动展开、完成自动折回（用户手动操作后不打扰）
  useEffect(() => {
    if (userToggled.current) return;
    if (verbosity === "debug") setOpen(true);
    else if (verbosity === "standard") setOpen(running);
    else setOpen(false);
  }, [verbosity, running]);

  const title = variant === "plan" ? "规划过程" : "思考";
  const chars = text.length;
  const firstLine = text.split("\n").find((l) => l.trim()) ?? "";

  return (
    <div className="my-1.5 max-w-[85%] rounded-xl border border-edge/70 bg-surface-2/50">
      <button
        type="button"
        onClick={() => {
          userToggled.current = true;
          setOpen((v) => !v);
        }}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11.5px] text-ink-3 transition-colors hover:text-ink-2"
      >
        {running ? (
          <span
            className="h-2.5 w-2.5 shrink-0 animate-spin rounded-full border border-accent/40 border-t-accent"
            aria-label="进行中"
          />
        ) : (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
            className="h-3 w-3 shrink-0" aria-hidden>
            {variant === "plan" ? (
              <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2M9 5a2 2 0 0 0 2 2h2a2 2 0 0 0 2-2M9 5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2" />
            ) : (
              <path d="M9.5 2a5.5 5.5 0 0 0-3.2 10c.6.5 1 1.3 1.2 2.1l.3 1.4a1 1 0 0 0 1 .8h6.4a1 1 0 0 0 1-.8l.3-1.4c.2-.8.6-1.6 1.2-2.1A5.5 5.5 0 0 0 14.5 2Z M9 19h6 M10 22h4" />
            )}
          </svg>
        )}
        <span className="font-medium">{title}</span>
        <span className="text-ink-3/70">{chars} 字</span>
        {!open && firstLine && (
          <span className="min-w-0 flex-1 truncate text-ink-3/60">
            {firstLine}
          </span>
        )}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
          className={`ml-auto h-3 w-3 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
          aria-hidden>
          <path d="m9 18 6-6-6-6" />
        </svg>
      </button>
      {open && (
        <div className="max-h-64 overflow-y-auto whitespace-pre-wrap border-t border-edge/50 px-3 py-2 font-mono text-[11.5px] leading-relaxed text-ink-2">
          {text}
          {running && <span className="animate-pulse">▍</span>}
        </div>
      )}
    </div>
  );
}
