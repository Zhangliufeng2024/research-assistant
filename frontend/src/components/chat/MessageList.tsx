import { Fragment, type RefObject } from "react";
import { motion } from "framer-motion";
import { LogoMark } from "@/components/icons";
import { Markdown } from "@/components/Markdown";
import { ToolCardView } from "@/components/chat/ToolCardView";
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

/** 聊天流：用户气泡 / 助手文本 / 工具卡，按 items 顺序渲染。 */
export function MessageList({
  chat,
  scrollRef,
  onScroll,
  onOpenFile,
  onPickSuggestion,
}: {
  chat: ChatState;
  scrollRef: RefObject<HTMLDivElement>;
  onScroll?: () => void;
  onOpenFile: (path: string) => void;
  onPickSuggestion: (text: string) => void;
}) {
  const streaming = chat.phase === "running" && !chat.approval;

  return (
    <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
      {chat.items.length === 0 ? (
        <EmptyHero onPick={onPickSuggestion} />
      ) : (
        <div className="mx-auto flex max-w-3xl flex-col gap-5 px-5 py-6">
          {chat.items.map((item, i) => {
            if (item.kind === "user") {
              return (
                <motion.div
                  key={`${item.t}-${i}`}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.18 }}
                  className="flex justify-end"
                >
                  <div className="relative max-w-[85%] rounded-2xl rounded-br-md bg-accent-tint px-4 py-2.5">
                    <div className="whitespace-pre-wrap break-words text-[14.5px] leading-6">
                      {item.text}
                    </div>
                    {item.steer && (
                      <div className="mt-1 text-right text-[10.5px] text-accent-hover dark:text-accent">
                        已作为引导注入
                      </div>
                    )}
                  </div>
                </motion.div>
              );
            }
            if (item.kind === "tool") {
              const card = chat.cards[item.ref];
              if (!card) return null;
              return (
                <motion.div
                  key={`${item.t}-${i}`}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.18 }}
                  className="flex gap-3"
                >
                  <div className="min-w-0 flex-1">
                    <ToolCardView card={card} onOpenFile={onOpenFile} />
                  </div>
                </motion.div>
              );
            }
            return (
              <motion.div
                key={`${item.t}-${i}`}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.18 }}
                className="flex gap-3"
              >
                <LogoMark className="mt-0.5 h-7 w-7 shrink-0 rounded-lg shadow-sm" />
                <div className="min-w-0 flex-1">
                  <Markdown>{item.text}</Markdown>
                  {streaming && i === chat.items.length - 1 && (
                    <span className="ml-0.5 inline-block h-4 w-[3px] translate-y-0.5 animate-pulse rounded-full bg-accent" />
                  )}
                </div>
              </motion.div>
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
