import { useEffect, useMemo, useRef, useState } from "react";
import { commandSuggestions, type CommandDef } from "@/lib/commands";
import type { AttachmentRef } from "@/lib/types";
import { EVENT_COMPOSER_SEND } from "@/hooks/useHotkeys";
import { useSessionStore } from "@/stores/sessionStore";

/** 发送结果串（与 chatStore.send 对齐）；undefined 视同成功。 */
type SendResult = "ok" | "empty" | "offline" | void;

/** 附加结果串（与 chatStore.attachFiles 对齐）。 */
type AttachResult = "ok" | "empty" | "offline" | "limit" | void;

/** 输入区：Enter 发送 / Shift+Enter 换行；运行中占位符切换为引导语义。
 * focusSignal 自增时把焦点拉回输入框（草稿入列点击聚焦，R12 P4）。
 * R13-B：onSend 返回非 ok 状态串时恢复草稿——发送失败还清空输入框，
 * 用户只能眼睁睁看着写好的话消失。
 * R16 附件：📎 选择 / 拖拽文件到输入区 / 粘贴截图均可加入待发附件，
 * 上传即时走 REST（chips 展示），随下一条消息一并发送。 */
export function Composer({
  running,
  disabled,
  focusSignal = 0,
  pendingAttachments,
  attaching,
  draftKey,
  onSend,
  onAttach,
  onRemoveAttachment,
}: {
  running: boolean;
  disabled?: boolean;
  focusSignal?: number;
  pendingAttachments: AttachmentRef[];
  /** 附件上传进行中：发送钮一并禁用（避免消息先于附件引用发出） */
  attaching: boolean;
  /** 会话键（阶段 4 / U-4）：提供时启用每会话草稿持久化——切会话从
   * sessionStore 恢复草稿、输入即写回、发送成功清空。未传则维持原
   * 本地草稿行为（其它宿主不受影响）。 */
  draftKey?: string | null;
  onSend: (text: string) => SendResult | Promise<SendResult>;
  onAttach: (files: File[]) => AttachResult | Promise<AttachResult>;
  onRemoveAttachment: (path: string) => void;
}) {
  const [value, setValue] = useState("");
  const [dragOver, setDragOver] = useState(false);
  // 方案 4：命令下拉。输入是「正在敲的命令 token」（/^\/\w*$/）时列出候选；
  // menuOpen=false 表示用户已 Esc 关闭或刚选中，继续打字才重新弹出。
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuIdx, setMenuIdx] = useState(0);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  // 拖拽计数：子元素 dragenter/dragleave 成对触发，用计数抵消抖动
  const dragDepth = useRef(0);
  const draftEnabled = draftKey !== undefined;

  // ---- 每会话草稿（阶段 4）：draftKey 变化 = 切换会话 → 恢复该会话草稿。
  // 会话区常驻后 Composer 不再重挂，恢复完全依赖这里。
  useEffect(() => {
    if (!draftEnabled) return;
    const draft = useSessionStore.getState().getDraft(draftKey ?? null);
    setValue(draft);
    if (ref.current) ref.current.style.height = "auto";
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftKey, draftEnabled]);

  // 全局发送事件（Ctrl/Cmd+Enter，useHotkeys 分发）：等价点击发送钮
  const submitRef = useRef<() => void>(() => {});
  useEffect(() => {
    const onSendEvent = () => submitRef.current();
    window.addEventListener(EVENT_COMPOSER_SEND, onSendEvent);
    return () => window.removeEventListener(EVENT_COMPOSER_SEND, onSendEvent);
  }, []);

  const suggestions = useMemo(
    () => (menuOpen ? commandSuggestions(value) : []),
    [menuOpen, value],
  );
  const menuActive = suggestions.length > 0;
  const activeIdx = menuIdx < suggestions.length ? menuIdx : 0;

  function applySuggestion(c: CommandDef) {
    setValue(`/${c.name} `);
    setMenuOpen(false);
    requestAnimationFrame(() => ref.current?.focus());
  }

  useEffect(() => {
    if (focusSignal > 0) ref.current?.focus();
  }, [focusSignal]);

  function submit() {
    const v = value.trim();
    if (!v || disabled || attaching) return;
    // 先乐观清空（打字流畅度优先），失败再原样恢复草稿
    // （光标位置不强求——失败是异常路径，话还在比什么都重要）
    Promise.resolve(onSend(v)).then((r) => {
      if (r !== undefined && r !== "ok") {
        setValue(v);
        if (draftEnabled) useSessionStore.getState().setDraft(draftKey ?? null, v);
      } else if (draftEnabled) {
        useSessionStore.getState().clearDraft(draftKey ?? null);
      }
    });
    setValue("");
    if (draftEnabled) useSessionStore.getState().setDraft(draftKey ?? null, "");
    setMenuOpen(false);
    // 清空后恢复高度
    requestAnimationFrame(() => {
      if (ref.current) ref.current.style.height = "auto";
    });
  }
  // 全局发送事件取最新闭包（ref 透传，监听只挂一次）
  submitRef.current = submit;

  function addFiles(list: FileList | File[] | null) {
    if (!list) return;
    const files = Array.from(list);
    if (files.length === 0) return;
    void Promise.resolve(onAttach(files));
  }

  return (
    <div className="px-4 pb-4">
      <div className="mx-auto max-w-3xl">
        <div
          className={`relative flex items-end gap-2 rounded-2xl border bg-surface p-2 shadow-card transition-colors focus-within:border-accent/50 ${
            dragOver ? "border-accent bg-accent-tint" : "border-edge"
          }`}
          onDragEnter={(e) => {
            e.preventDefault();
            dragDepth.current += 1;
            setDragOver(true);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={(e) => {
            e.preventDefault();
            dragDepth.current -= 1;
            if (dragDepth.current <= 0) {
              dragDepth.current = 0;
              setDragOver(false);
            }
          }}
          onDrop={(e) => {
            e.preventDefault();
            dragDepth.current = 0;
            setDragOver(false);
            addFiles(e.dataTransfer?.files ?? null);
          }}
        >
          {/* 命令下拉（方案 4）：悬浮于输入框上方；↑↓ 选择、Enter/Tab 补全、
              Esc 关闭、点击直接补全。onMouseDown 抢在 textarea 失焦前执行。 */}
          {menuActive && (
            <div
              role="listbox"
              aria-label="可用命令"
              className="absolute bottom-full left-0 right-0 z-30 mb-2 overflow-hidden rounded-xl border border-edge bg-surface shadow-card"
            >
              {suggestions.map((c, i) => (
                <button
                  key={c.name}
                  type="button"
                  role="option"
                  aria-selected={i === activeIdx}
                  onMouseDown={(e) => {
                    e.preventDefault();
                    applySuggestion(c);
                  }}
                  onMouseEnter={() => setMenuIdx(i)}
                  className={`flex w-full items-baseline gap-2.5 px-3.5 py-2 text-left transition-colors ${
                    i === activeIdx ? "bg-surface-2" : ""
                  }`}
                >
                  <span className="shrink-0 font-mono text-[12.5px] font-medium text-accent-hover dark:text-accent">
                    /{c.name}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[12px] text-ink-2">
                    {c.description}
                  </span>
                  <span className="shrink-0 font-mono text-[10.5px] text-ink-3">
                    {c.usage}
                  </span>
                </button>
              ))}
            </div>
          )}
          {/* 待发附件 chips：上传完成即显示，✕ 移除 */}
          {(pendingAttachments.length > 0 || attaching) && (
            <div className="flex w-full flex-wrap gap-1.5 px-1 pb-1.5">
              {attaching && (
                <span className="flex items-center gap-1 rounded-lg border border-edge bg-surface-2 px-2 py-0.5 text-[11px] text-ink-3">
                  <span className="h-3 w-3 animate-spin rounded-full border-2 border-ink-3 border-t-transparent" />
                  上传中…
                </span>
              )}
              {pendingAttachments.map((a) => (
                <span
                  key={a.path}
                  className="flex items-center gap-1 rounded-lg border border-edge bg-surface-2 px-2 py-0.5 text-[11px] text-ink-2"
                >
                  <span aria-hidden>📎</span>
                  <span className="max-w-[10rem] truncate">{a.name}</span>
                  <button
                    type="button"
                    aria-label={`移除附件 ${a.name}`}
                    onClick={() => onRemoveAttachment(a.path)}
                    className="text-ink-3 transition-colors hover:text-danger"
                  >
                    ✕
                  </button>
                </span>
              ))}
            </div>
          )}
          <input
            ref={fileRef}
            type="file"
            multiple
            className="hidden"
            tabIndex={-1}
            onChange={(e) => {
              addFiles(e.target.files);
              e.target.value = ""; // 允许重复选择同一文件
            }}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={disabled || attaching}
            aria-label="添加附件"
            title="添加附件（也可拖拽或粘贴）"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface-2 text-ink-3 transition-all hover:text-accent disabled:opacity-40"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
              <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
          </button>
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
              if (draftEnabled) useSessionStore.getState().setDraft(draftKey ?? null, e.target.value);
              setMenuOpen(true);
              setMenuIdx(0);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 176)}px`;
            }}
            onKeyDown={(e) => {
              if (menuActive) {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setMenuIdx((i) => (i + 1) % suggestions.length);
                  return;
                }
                if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setMenuIdx((i) => (i - 1 + suggestions.length) % suggestions.length);
                  return;
                }
                if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing)) {
                  e.preventDefault();
                  applySuggestion(suggestions[activeIdx]!);
                  return;
                }
                if (e.key === "Escape") {
                  e.preventDefault();
                  setMenuOpen(false);
                  return;
                }
              }
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            onPaste={(e) => {
              // 剪贴板带文件（如截图）→ 转附件；纯文本走默认粘贴
              const files = Array.from(e.clipboardData?.files ?? []);
              if (files.length > 0) {
                e.preventDefault();
                addFiles(files);
              }
            }}
          />
          <button
            type="button"
            onClick={submit}
            disabled={!value.trim() || disabled || attaching}
            aria-label={running ? "发送引导指令" : "发送消息"}
            className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-all ${
              value.trim() && !disabled && !attaching
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
          Enter 发送 · Shift+Enter 换行{running ? " · 运行中的消息将作为引导注入下一步" : " · 输入 / 唤起命令 · 可拖拽/粘贴附件"}
        </div>
      </div>
    </div>
  );
}
