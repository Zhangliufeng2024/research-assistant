import { Fragment, type RefObject } from "react";
import { LogoMark } from "@/components/icons";
import { AssistantBubble, ToolCardRow, UserBubble } from "@/components/chat/MessageBubbles";
import { ThinkingBlock } from "@/components/chat/ThinkingBlock";
import type { MessageOpResult } from "@/lib/messageOps";
import type { ChatState } from "@/lib/types";

const SUGGESTIONS = [
  "读一下 data/ 目录里的数据，做描述性统计并画图",
  "帮我梳理「研究主题」的文献综述大纲",
  "检查 references.bib 里缺失 DOI 的条目",
];

function EmptyHero({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6 py-12 text-center">
      <LogoMark className="mb-5 h-14 w-14 rounded-2xl shadow-card" />
      <h2 className="text-[19px] font-semibold tracking-tight">今天研究什么？</h2>
      <p className="mt-2 max-w-md text-[13.5px] leading-6 text-ink-2">
        与助手自由讨论，或让它直接读写工作区里的文件、跑分析、画图。
      </p>
      <div className="mt-7 flex w-full max-w-lg flex-col gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onPick(s)}
            className="rounded-xl border border-edge bg-surface px-4 py-2.5 text-left text-[13px] text-ink-2 shadow-sm transition-colors hover:border-accent/40 hover:text-ink"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

/** 聊天流：用户气泡 / 助手文本 / 工具卡，按 items 顺序渲染。
 *
 * R14-N：滚动容器 ref 由 usePinnedScroll 提供（贴底跟随 + 回底 pill），
 * 本组件只负责把 ref 挂到真实 overflow 元素上。
 * R14-R：每类气泡是 React.memo 组件（memo 边界见 MessageBubbles.tsx 头注），
 * map 回调里禁止给它们传内联闭包——回调一律来自 ChatView 的 useCallback。
 */
export function MessageList({
  chat,
  containerRef,
  opsEnabled,
  onOpenFile,
  onPickSuggestion,
  onCopyMessage,
  onRegenerate,
  onEditSubmit,
}: {
  chat: ChatState;
  containerRef: RefObject<HTMLDivElement>;
  /** false=流式进行中，隐藏消息操作钮（regenerate/edit 此刻会被 busy 拒绝）。 */
  opsEnabled: boolean;
  onOpenFile: (path: string) => void;
  onPickSuggestion: (text: string) => void;
  onCopyMessage: (text: string) => void;
  onRegenerate: (idx: number) => void;
  onEditSubmit: (idx: number, newText: string) => Promise<MessageOpResult>;
}) {
  const streaming = chat.phase === "running" && !chat.approval;
  const lastIdx = chat.items.length - 1;

  return (
    <div ref={containerRef} className="h-full overflow-y-auto">
      {chat.items.length === 0 ? (
        <EmptyHero onPick={onPickSuggestion} />
      ) : (
        <div className="mx-auto flex max-w-3xl flex-col gap-5 px-5 py-6">
          {chat.items.map((item, i) => {
            if (item.kind === "user") {
              return (
                <UserBubble
                  key={`${item.t}-${i}`}
                  text={item.text}
                  steer={item.steer}
                  attachments={item.attachments}
                  idx={i}
                  opsEnabled={opsEnabled}
                  onCopyMessage={onCopyMessage}
                  onOpenFile={onOpenFile}
                  onEditSubmit={onEditSubmit}
                />
              );
            }
            if (item.kind === "tool") {
              const card = chat.cards[item.ref];
              if (!card) return null;
              return (
                <ToolCardRow
                  key={`${item.t}-${i}`}
                  card={card}
                  onOpenFile={onOpenFile}
                />
              );
            }
            // R17 思考链分级：thought/plan channel 走 L1 折叠容器，不进正文气泡
            if (item.kind === "text" && (item.channel === "thought" || item.channel === "plan")) {
              return (
                <ThinkingBlock
                  key={`${item.t}-${i}`}
                  text={item.text}
                  running={chat.phase === "running" && i === lastIdx}
                  variant={item.channel}
                />
              );
            }
            return (
              <AssistantBubble
                key={`${item.t}-${i}`}
                text={item.text}
                showCursor={streaming && i === lastIdx}
                partial={item.partial}
                idx={i}
                opsEnabled={opsEnabled}
                onCopyMessage={onCopyMessage}
                onRegenerate={onRegenerate}
              />
            );
          })}

          {streaming && chat.items[chat.items.length - 1]?.kind !== "text" && (
            <div className="flex gap-3">
              <LogoMark className="mt-0.5 h-7 w-7 shrink-0 rounded-lg shadow-sm" />
              <div className="flex items-center gap-1.5 pt-2">
                {[0, 1, 2].map((d) => (
                  <Fragment key={d}>
                    <span
                      className="h-1.5 w-1.5 animate-bounce rounded-full bg-ink-3"
                      style={{ animationDelay: `${d * 0.15}s` }}
                    />
                  </Fragment>
                ))}
                <span className="ml-1 text-[12px] text-ink-3">思考中</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
