/* 迭代2：分屏对照——主区交互会话 + 右侧只读对照会话。
 *
 * 设计决策（对照 CodePilot split screen 的取舍）：
 * - 第二会话走 REST 快照只读渲染，不占 WS 通道——chat/task 双通道是单会话
 *   契约（chatStore 全局单例），双交互会话需要整套 store 多实例化，风险
 *   远超收益；对照场景（一边跑任务一边翻旧对话）只读完全够用。
 * - 20s 轻量轮询保持对照侧新鲜；手动刷新按钮立即可用。
 * - 折叠态与会话选择持久化 localStorage（纯 UI 偏好，不入库）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { formatRelative, sessionTitle } from "@/lib/format";
import type { SessionSummary } from "@/lib/types";

const SPLIT_OPEN_KEY = "ra.chat.split.v1";
const PEER_SESSION_KEY = "ra.chat.peer.v1";
const PEER_POLL_MS = 20_000;

export function loadSplitOpen(): boolean {
  try {
    return globalThis.localStorage?.getItem(SPLIT_OPEN_KEY) === "1";
  } catch {
    return false;
  }
}

export function saveSplitOpen(open: boolean): void {
  try {
    globalThis.localStorage?.setItem(SPLIT_OPEN_KEY, open ? "1" : "0");
  } catch {
    /* 隐私模式：仅内存态 */
  }
}

export function loadPeerSessionId(): string | null {
  try {
    return globalThis.localStorage?.getItem(PEER_SESSION_KEY) || null;
  } catch {
    return null;
  }
}

export function savePeerSessionId(id: string | null): void {
  try {
    if (id) globalThis.localStorage?.setItem(PEER_SESSION_KEY, id);
    else globalThis.localStorage?.removeItem(PEER_SESSION_KEY);
  } catch {
    /* 忽略 */
  }
}

interface PeerMessage {
  role: "user" | "assistant";
  content: string;
  partial?: boolean;
}

/** 只读对照面板：选择一个其他会话，快照渲染其历史。 */
export function PeerSessionPanel({
  sessionId,
  sessions,
  excludeId,
  onPick,
  onClose,
}: {
  sessionId: string | null;
  sessions: SessionSummary[];
  /** 主区正在交互的会话（选择器里排除，避免两侧同屏同会话）。 */
  excludeId: string | null;
  onPick: (id: string) => void;
  onClose: () => void;
}) {
  const [messages, setMessages] = useState<PeerMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const tickRef = useRef(0);

  const load = useCallback(async (sid: string, silent = false) => {
    if (!silent) setLoading(true);
    const tick = ++tickRef.current;
    try {
      const res = await api.get<{ messages: PeerMessage[] }>(
        `/api/chat/sessions/${encodeURIComponent(sid)}`,
      );
      if (tickRef.current !== tick) return; // 已切换到别的会话：丢弃过期响应
      setMessages(res.messages ?? []);
      setError(false);
      setUpdatedAt(Date.now());
    } catch {
      if (tickRef.current === tick) setError(true);
    } finally {
      if (tickRef.current === tick) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    void load(sessionId);
    const timer = window.setInterval(() => void load(sessionId, true), PEER_POLL_MS);
    return () => window.clearInterval(timer);
  }, [sessionId, load]);

  const candidates = sessions.filter((s) => s.id !== excludeId);
  const summary = sessions.find((s) => s.id === sessionId);

  return (
    <div className="flex h-full min-h-0 flex-col bg-canvas">
      {/* 头部：会话选择器 + 刷新 + 关闭 */}
      <div className="flex shrink-0 items-center gap-2 border-b border-edge px-3 py-2">
        <span className="shrink-0 text-[10px] uppercase tracking-widest text-accent">
          对照
        </span>
        <select
          value={sessionId ?? ""}
          onChange={(e) => onPick(e.target.value)}
          aria-label="选择对照会话"
          className="min-w-0 flex-1 truncate rounded-lg border border-edge bg-surface px-2 py-1 text-[11.5px] text-ink-2 outline-none focus:border-accent/60"
        >
          <option value="">选择会话…</option>
          {candidates.map((s) => (
            <option key={s.id} value={s.id}>
              {sessionTitle(s.title, s.last_message)}
            </option>
          ))}
        </select>
        <button
          type="button"
          title="刷新快照"
          aria-label="刷新对照会话"
          disabled={!sessionId || loading}
          onClick={() => sessionId && void load(sessionId)}
          className="shrink-0 rounded-md p-1 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-40"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
            strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden>
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
            <path d="M3 3v5h5" />
          </svg>
        </button>
        <button
          type="button"
          title="关闭分屏"
          aria-label="关闭分屏对照"
          onClick={onClose}
          className="shrink-0 rounded-md p-1 text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
            strokeLinecap="round" className="h-3.5 w-3.5" aria-hidden>
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* 只读消息流 */}
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {!sessionId && (
          <div className="px-2 py-8 text-center text-[12px] text-ink-3">
            从上方选择一个会话作为对照——适合「一边跑任务一边翻旧对话」。
          </div>
        )}
        {sessionId && loading && messages.length === 0 && (
          <div className="px-2 py-8 text-center text-[12px] text-ink-3">加载中…</div>
        )}
        {sessionId && error && messages.length === 0 && (
          <div className="px-2 py-8 text-center text-[12px] text-danger">
            快照加载失败——会话可能已被删除
          </div>
        )}
        {sessionId && !loading && messages.length === 0 && !error && (
          <div className="px-2 py-8 text-center text-[12px] text-ink-3">该会话还没有消息</div>
        )}
        <div className="space-y-3">
          {messages.map((m, i) => (
            <div key={i}>
              <div
                className={`mb-0.5 text-[10px] font-medium ${
                  m.role === "user" ? "text-accent-hover dark:text-accent" : "text-ink-3"
                }`}
              >
                {m.role === "user" ? "用户" : "助手"}
                {m.partial && (
                  <span className="ml-1 rounded bg-warn/10 px-1 py-px text-warn">残缺</span>
                )}
              </div>
              <div
                className={`whitespace-pre-wrap rounded-xl px-3 py-2 text-[12px] leading-relaxed ${
                  m.role === "user"
                    ? "bg-accent-tint/60 text-ink"
                    : "bg-surface text-ink-2"
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* 底部状态条 */}
      <div className="shrink-0 border-t border-edge px-3 py-1.5 text-[10px] text-ink-3">
        {summary ? (
          <>
            {formatRelative(summary.updated_at)} · {summary.turns} 轮 · 只读快照
            {updatedAt && ` · ${new Date(updatedAt).toLocaleTimeString()} 更新`}
          </>
        ) : (
          "只读快照 · 每 20 秒自动刷新"
        )}
      </div>
    </div>
  );
}
