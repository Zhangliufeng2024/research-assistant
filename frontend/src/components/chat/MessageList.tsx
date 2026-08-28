import { Fragment, useMemo, useState, type RefObject } from "react";
import { LogoMark } from "@/components/icons";
import { AssistantBubble, ToolCardRow, UserBubble } from "@/components/chat/MessageBubbles";
import { ThinkingBlock } from "@/components/chat/ThinkingBlock";
import { usePrefsStore } from "@/stores/prefsStore";
import type { MessageOpResult } from "@/lib/messageOps";
import type { ChatItem, ChatState } from "@/lib/types";

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

/* ---------- 迭代2：过程聚合（查看过程 N 项） ---------- */

interface Segment {
  /** 用户消息条目（每段起点；首个回复前无用户消息时为 undefined）。 */
  user: { item: ChatItem & { kind: "user" }; idx: number } | null;
  /** 段内正文气泡（无 channel 的 text）。 */
  texts: Array<{ item: ChatItem & { kind: "text" }; idx: number }>;
  /** 段内过程证据（工具卡 + thought/plan channel 文本）。 */
  process: Array<{ item: ChatItem; idx: number }>;
}

/** 按「用户消息 →（过程+正文）」切段；items 保序，段边界即用户消息。 */
export function segmentItems(items: ChatItem[]): Segment[] {
  const segments: Segment[] = [];
  let current: Segment = { user: null, texts: [], process: [] };
  for (let i = 0; i < items.length; i++) {
    const item = items[i]!;
    if (item.kind === "user") {
      if (current.user || current.texts.length || current.process.length) {
        segments.push(current);
      }
      current = { user: { item, idx: i }, texts: [], process: [] };
      continue;
    }
    if (item.kind === "tool") {
      current.process.push({ item, idx: i });
    } else if (item.kind === "text" && (item.channel === "thought" || item.channel === "plan")) {
      current.process.push({ item, idx: i });
    } else if (item.kind === "text") {
      current.texts.push({ item, idx: i });
    }
  }
  if (current.user || current.texts.length || current.process.length) {
    segments.push(current);
  }
  return segments;
}

/** 段内过程渲染器：工具卡 + 思考/规划块（与内联渲染同一套组件）。 */
function ProcessItems({
  chat,
  entries,
  onOpenFile,
}: {
  chat: ChatState;
  entries: Segment["process"];
  onOpenFile: (path: string) => void;
}) {
  const lastIdx = chat.items.length - 1;
  return (
    <div className="space-y-2">
      {entries.map(({ item, idx }) => {
        if (item.kind === "tool") {
          const card = chat.cards[item.ref];
          if (!card) return null;
          return <ToolCardRow key={`p-${idx}`} card={card} onOpenFile={onOpenFile} />;
        }
        if (item.kind === "text" && (item.channel === "thought" || item.channel === "plan")) {
          return (
            <ThinkingBlock
              key={`p-${idx}`}
              text={item.text}
              running={chat.phase === "running" && idx === lastIdx}
              variant={item.channel}
            />
          );
        }
        return null;
      })}
    </div>
  );
}

/** 「查看过程 N 项」折叠入口：简洁档把过程证据收进段尾折叠区。 */
function ProcessGroup({
  count,
  children,
  running,
}: {
  count: number;
  children: React.ReactNode;
  running: boolean;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-lg border border-edge bg-surface px-2.5 py-1 text-[11px] text-ink-3 transition-colors hover:border-accent/40 hover:text-ink-2"
      >
        {running && (
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-warn" aria-hidden />
        )}
        {open ? "收起过程" : `查看过程 ${count} 项`}
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
          strokeLinecap="round" strokeLinejoin="round"
          className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`} aria-hidden>
          <path d="m9 18 6-6-6-6" />
        </svg>
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

/** 聊天流：用户气泡 / 助手文本 / 工具卡，按 items 顺序渲染。
 *
 * R14-N：滚动容器 ref 由 usePinnedScroll 提供（贴底跟随 + 回底 pill），
 * 本组件只负责把 ref 挂到真实 overflow 元素上。
 * R14-R：每类气泡是 React.memo 组件（memo 边界见 MessageBubbles.tsx 头注），
 * map 回调里禁止给它们传内联闭包——回调一律来自 ChatView 的 useCallback。
 * 迭代2 过程聚合：简洁档（minimal）下每段（用户消息→下一用户消息）的过程
 * 证据（工具卡+思考块）收进段尾「查看过程 N 项」折叠区——正文干净、过程
 * 可溯；标准/调试档保持逐项内联（观察执行过程）。
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
  const verbosity = usePrefsStore((s) => s.verbosity);
  const streaming = chat.phase === "running" && !chat.approval;
  const lastIdx = chat.items.length - 1;
  const groupProcess = verbosity === "minimal";

  // 简洁档切段（memo：items 未变不重算）
  const segments = useMemo(
    () => (groupProcess ? segmentItems(chat.items) : null),
    [groupProcess, chat.items],
  );

  if (groupProcess && segments) {
    return (
      <div ref={containerRef} className="h-full overflow-y-auto">
        {chat.items.length === 0 ? (
          <EmptyHero onPick={onPickSuggestion} />
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-5 px-5 py-6">
            {segments.map((seg, si) => (
              <div key={`seg-${si}`} className="flex flex-col gap-3">
                {seg.user && (
                  <UserBubble
                    key={`u-${seg.user.idx}`}
                    text={seg.user.item.text}
                    steer={seg.user.item.steer}
                    attachments={seg.user.item.attachments}
                    idx={seg.user.idx}
                    opsEnabled={opsEnabled}
                    onCopyMessage={onCopyMessage}
                    onOpenFile={onOpenFile}
                    onEditSubmit={onEditSubmit}
                  />
                )}
                {seg.texts.map(({ item, idx }) => (
                  <AssistantBubble
                    key={`t-${idx}`}
                    text={item.text}
                    showCursor={streaming && idx === lastIdx}
                    partial={item.partial}
                    idx={idx}
                    opsEnabled={opsEnabled}
                    onCopyMessage={onCopyMessage}
                    onRegenerate={onRegenerate}
                  />
                ))}
                {seg.process.length > 0 && (
                  <ProcessGroup
                    count={seg.process.length}
                    running={chat.phase === "running" && si === segments.length - 1}
                  >
                    <ProcessItems
                      chat={chat}
                      entries={seg.process}
                      onOpenFile={onOpenFile}
                    />
                  </ProcessGroup>
                )}
              </div>
            ))}

            {streaming && chat.items[chat.items.length - 1]?.kind !== "text" && (
              <StreamingDots />
            )}
          </div>
        )}
      </div>
    );
  }

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
            <StreamingDots />
          )}
        </div>
      )}
    </div>
  );
}

function StreamingDots() {
  return (
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
  );
}
