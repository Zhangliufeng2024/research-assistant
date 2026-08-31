/* 会话滚动锚点持久化（从 ChatView 抽出，工程债拆分 2026-08-31）。
 * 仅非贴底（用户上翻过）时记录 scrollTop；切走/重进恢复。 */
import { useEffect, useRef } from "react";
import type { ChatState } from "@/lib/types";
import { useSessionStore } from "@/stores/sessionStore";

export function useChatScrollAnchors(
  active: boolean,
  chat: ChatState,
  containerRef: React.RefObject<HTMLElement | null>,
  pinned: boolean,
) {
  const sidForAnchor = chat.sessionId;
  const pinnedRef = useRef(pinned);
  pinnedRef.current = pinned;

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !sidForAnchor) return;
    let raf = 0;
    const onScroll = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        if (!pinnedRef.current && el.scrollTop > 0) {
          useSessionStore.getState().setAnchor(sidForAnchor, el.scrollTop);
        }
      });
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      if (raf) cancelAnimationFrame(raf);
    };
  }, [sidForAnchor, containerRef]);

  useEffect(() => {
    if (!active || !sidForAnchor) return;
    const el = containerRef.current;
    const anchor = sidForAnchor
      ? useSessionStore.getState().getAnchor(sidForAnchor)
      : 0;
    if (el && anchor > 0) el.scrollTop = anchor;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  const pendingAnchorSidRef = useRef<string | null>(null);
  useEffect(() => {
    if (
      sidForAnchor &&
      useSessionStore.getState().getAnchor(sidForAnchor) > 0
    ) {
      pendingAnchorSidRef.current = sidForAnchor;
    }
  }, [sidForAnchor]);
  useEffect(() => {
    const pending = pendingAnchorSidRef.current;
    if (!pending || pending !== chat.sessionId || chat.items.length === 0) return;
    const el = containerRef.current;
    if (el) el.scrollTop = useSessionStore.getState().getAnchor(pending);
    pendingAnchorSidRef.current = null;
  }, [chat.items, chat.sessionId, containerRef]);
}
