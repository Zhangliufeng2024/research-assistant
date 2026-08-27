/* 单条消息气泡组件（R14-M 操作三件套 + R14-R 渲染 memo 边界）。
 *
 * 为什么边界在这里：ChatView 订阅整个 chatStore，流式合帧后每 ~50ms 全树
 * 重渲染一次。把每类气泡抽成 React.memo 子组件后，props 全是「原始值或
 * 稳定引用」（text/idx/布尔 + ChatView useCallback 的回调），历史消息在
 * 每帧比较后直接跳过子树——正在生成的那一条之外，Markdown+KaTeX+高亮
 * 的重解析彻底消失。调用方纪律：传给这些组件的回调必须来自 useCallback，
 * 禁止内联闭包（否则 memo 每帧失效，见 ChatView onOpenFile 的教训）。
 *
 * 操作钮语义（与 stores/chatStore.ts 对齐）：
 * - 复制：copyText(原始 markdown) 由视图层处理 toast；
 * - 重新生成：assistant 气泡 → regenerateMessage(idx)，store 内部解析其前
 *   最近的 user 提问原样再发一轮（保守语义，不删历史）；
 * - 编辑重发：user 气泡 → 气泡内联变 textarea（预填原文、自动聚焦），
 *   Enter 发送 / Esc 取消（useEscapeStack 层级栈），提交走 editAndResend；
 *   原气泡文本不回改（持久化取舍见 lib/messageOps.ts 头注）。
 */
import { memo, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { LogoMark } from "@/components/icons";
import { Markdown } from "@/components/Markdown";
import { ToolCardView } from "@/components/chat/ToolCardView";
import {
  IconCopy,
  IconEditPencil,
  IconRegenerate,
  MessageActionBar,
} from "@/components/chat/MessageActions";
import { useEscapeStack } from "@/hooks/useEscapeStack";
import type { MessageOpResult } from "@/lib/messageOps";
import { toast } from "@/stores/toastStore";
import type { AttachmentRef, ToolCard } from "@/lib/types";

/** 附件大小的人类可读口径（KB/MB 一位小数；<1KB 显示字节数）。 */
function formatAttSize(size: number): string {
  if (size < 1024) return `${size}B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`;
  return `${(size / (1024 * 1024)).toFixed(1)}MB`;
}

/** 入场动画统一参数（与旧版 MessageList 一致）。 */
const ENTER_MOTION = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.18 },
} as const;

/** 回调契约：由 ChatView 以 useCallback 提供（稳定引用是 memo 生效前提）。 */
export interface BubbleOps {
  idx: number;
  /** false=流式进行中：整体隐藏操作钮（busy 拒绝不如不出现）。 */
  opsEnabled: boolean;
  /** 复制该消息原始 markdown；toast 反馈由实现方负责。 */
  onCopyMessage: (text: string) => void;
}

/* ------------------------------------------------------------------ */
/* 用户气泡：复制 + 编辑重发                                            */
/* ------------------------------------------------------------------ */

export const UserBubble = memo(function UserBubble({
  text,
  steer,
  attachments,
  idx,
  opsEnabled,
  onCopyMessage,
  onOpenFile,
  onEditSubmit,
}: BubbleOps & {
  text: string;
  steer?: boolean;
  /** 随消息上传的附件（R16）：名称 + 可选大小，点击经 dock 预览打开 */
  attachments?: AttachmentRef[];
  onEditSubmit: (idx: number, newText: string) => Promise<MessageOpResult>;
  onOpenFile?: (path: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  // Esc 取消编辑：走全局层级栈，与模态体系互不打架（仅栈顶响应）
  useEscapeStack(editing, () => setEditing(false));

  useEffect(() => {
    if (editing) taRef.current?.focus();
  }, [editing]);

  function startEdit() {
    setDraft(text);
    setEditing(true);
  }

  function submitEdit() {
    const v = draft.trim();
    if (!v) {
      toast.info("消息不能为空");
      return;
    }
    void onEditSubmit(idx, v).then((r) => {
      // 仅成功才收起编辑器——busy/offline 时保住草稿，用户不必重打一遍
      if (r === "ok") setEditing(false);
    });
  }

  if (editing) {
    return (
      <motion.div {...ENTER_MOTION} className="flex justify-end">
        <div className="w-[85%] rounded-2xl border border-accent/50 bg-surface p-2 shadow-card">
          <textarea
            ref={taRef}
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submitEdit();
              }
            }}
            className="max-h-44 w-full resize-none bg-transparent px-2 py-1 text-[14.5px] leading-6 outline-none"
          />
          <div className="flex items-center gap-2 pt-1">
            <span className="mr-auto text-[11px] text-ink-3">
              Enter 发送 · Esc 取消 · 新文本将作为新一轮发出
            </span>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-lg border border-edge bg-surface px-2.5 py-1 text-[12px] font-medium text-ink-2 transition-colors hover:bg-surface-2"
            >
              取消
            </button>
            <button
              type="button"
              onClick={submitEdit}
              disabled={!draft.trim()}
              className="rounded-lg bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-40"
            >
              发送
            </button>
          </div>
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div {...ENTER_MOTION} className="group relative flex justify-end">
      <div className="relative max-w-[85%] rounded-2xl rounded-br-md bg-accent-tint px-4 py-2.5">
        <div className="whitespace-pre-wrap break-words text-[14.5px] leading-6">
          {text}
        </div>
        {attachments && attachments.length > 0 && (
          <div className="mt-1.5 flex flex-wrap justify-end gap-1.5">
            {attachments.map((a) => (
              <button
                key={a.path}
                type="button"
                title={onOpenFile ? `打开 ${a.name}` : a.path}
                onClick={() => onOpenFile?.(a.path)}
                className="flex items-center gap-1 rounded-lg border border-edge bg-surface/80 px-2 py-0.5 text-[11px] text-ink-2 transition-colors hover:border-accent/40 hover:text-ink"
              >
                <span aria-hidden>📎</span>
                <span className="max-w-[10rem] truncate font-medium">{a.name}</span>
                {typeof a.size === "number" && a.size > 0 && (
                  <span className="text-ink-3">{formatAttSize(a.size)}</span>
                )}
              </button>
            ))}
          </div>
        )}
        {steer && (
          <div className="mt-1 text-right text-[10.5px] text-accent-hover dark:text-accent">
            已作为引导注入
          </div>
        )}
      </div>
      {opsEnabled && (
        <MessageActionBar
          placement="left-center"
          actions={[
            {
              key: "copy",
              title: "复制",
              icon: <IconCopy />,
              onClick: () => onCopyMessage(text),
            },
            {
              key: "edit",
              title: "编辑重发",
              icon: <IconEditPencil />,
              onClick: startEdit,
            },
          ]}
        />
      )}
    </motion.div>
  );
});

/* ------------------------------------------------------------------ */
/* 助手气泡：Markdown 正文 + 复制 + 重新生成                            */
/* ------------------------------------------------------------------ */

export const AssistantBubble = memo(function AssistantBubble({
  text,
  showCursor,
  partial,
  idx,
  opsEnabled,
  onCopyMessage,
  onRegenerate,
}: BubbleOps & {
  text: string;
  showCursor: boolean;
  /** 残缺回答（R16）：回合被打断/失败时服务端落盘的标记，提示可续问 */
  partial?: boolean;
  onRegenerate: (idx: number) => void;
}) {
  return (
    <motion.div {...ENTER_MOTION} className="group relative flex gap-3">
      <LogoMark className="mt-0.5 h-7 w-7 shrink-0 rounded-lg shadow-sm" />
      <div className="min-w-0 flex-1">
        <Markdown>{text}</Markdown>
        {showCursor && (
          <span className="ml-0.5 inline-block h-4 w-[3px] translate-y-0.5 animate-pulse rounded-full bg-accent" />
        )}
        {partial && (
          <div className="mt-1.5 inline-flex items-center gap-1 rounded-lg bg-warn/10 px-2 py-0.5 text-[11px] text-warn">
            回答在此被打断——继续追问即可接上
          </div>
        )}
      </div>
      {opsEnabled && (
        <MessageActionBar
          placement="above-right"
          actions={[
            {
              key: "copy",
              title: "复制",
              icon: <IconCopy />,
              onClick: () => onCopyMessage(text),
            },
            {
              key: "regen",
              title: "重新生成",
              icon: <IconRegenerate />,
              onClick: () => onRegenerate(idx),
            },
          ]}
        />
      )}
    </motion.div>
  );
});

/* ------------------------------------------------------------------ */
/* 工具卡行（无操作钮；memo 使卡片实体不变时跳过重渲染）                  */
/* ------------------------------------------------------------------ */

export const ToolCardRow = memo(function ToolCardRow({
  card,
  onOpenFile,
}: {
  card: ToolCard;
  onOpenFile: (path: string) => void;
}) {
  return (
    <motion.div {...ENTER_MOTION} className="flex gap-3">
      <div className="min-w-0 flex-1">
        <ToolCardView card={card} onOpenFile={onOpenFile} />
      </div>
    </motion.div>
  );
});
