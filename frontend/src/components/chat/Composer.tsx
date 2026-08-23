import { useEffect, useRef, useState } from "react";

/** 输入区：Enter 发送 / Shift+Enter 换行；运行中占位符切换为引导语义。
 * focusSignal 自增时把焦点拉回输入框（草稿入列点击聚焦，R12 P4）。 */
export function Composer({
  running,
  disabled,
  focusSignal = 0,
  onSend,
}: {
  running: boolean;
  disabled?: boolean;
  focusSignal?: number;
  onSend: (text: string) => void;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (focusSignal > 0) ref.current?.focus();
  }, [focusSignal]);

  function submit() {
    const v = value.trim();
    if (!v || disabled) return;
    onSend(v);
    setValue("");
    // 清空后恢复高度
    requestAnimationFrame(() => {
      if (ref.current) ref.current.style.height = "auto";
    });
  }

  return (
    <div className="px-4 pb-4">
      <div className="mx-auto max-w-3xl">
        <div className="flex items-end gap-2 rounded-2xl border border-edge bg-surface p-2 shadow-card transition-colors focus-within:border-accent/50">
          <textarea
            ref={ref}
            value={value}
            rows={1}
            placeholder={
              running ? "agent 运行中——输入以引导下一步…" : "输入消息，与助手讨论…"
            }
            className="max-h-44 min-h-[38px] flex-1 resize-none bg-transparent px-2.5 py-2 text-[14px] leading-6 outline-none placeholder:text-ink-3"
            onChange={(e) => {
              setValue(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 176)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
          />
          <button
            type="button"
            onClick={submit}
            disabled={!value.trim() || disabled}
            aria-label={running ? "发送引导指令" : "发送消息"}
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-all ${
              value.trim() && !disabled
                ? "bg-accent text-white hover:bg-accent-hover"
                : "bg-surface-2 text-ink-3"
            }`}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
              <path d="M12 19V5" />
              <path d="m5 12 7-7 7 7" />
            </svg>
          </button>
        </div>
        <div className="mt-1.5 text-center text-[11px] text-ink-3">
          Enter 发送 · Shift+Enter 换行{running ? " · 运行中的消息将作为引导注入下一步" : ""}
        </div>
      </div>
    </div>
  );
}
