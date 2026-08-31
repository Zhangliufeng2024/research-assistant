/* 分屏对照会话选择（纯 UI 偏好入 localStorage，从 ChatView 抽出）。 */
import { useEffect, useState } from "react";
import {
  loadPeerSessionId,
  loadSplitOpen,
  savePeerSessionId,
  saveSplitOpen,
} from "@/components/chat/PeerSessionPanel";
import type { SessionSummary } from "@/lib/types";

export function useChatSplitPeer(
  sessions: SessionSummary[],
  currentSessionId: string | null,
) {
  const [splitOpen, setSplitOpen] = useState<boolean>(loadSplitOpen);
  const [peerSessionId, setPeerSessionId] = useState<string | null>(
    loadPeerSessionId,
  );
  const toggleSplit = () => {
    setSplitOpen((prev) => {
      const next = !prev;
      saveSplitOpen(next);
      return next;
    });
  };
  const pickPeer = (id: string) => {
    setPeerSessionId(id);
    savePeerSessionId(id);
  };
  useEffect(() => {
    if (!splitOpen || peerSessionId || sessions.length === 0) return;
    const candidate =
      sessions.find((s) => s.id !== currentSessionId && !s.archived) ??
      sessions.find((s) => s.id !== currentSessionId);
    if (candidate) pickPeer(candidate.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [splitOpen, peerSessionId, sessions]);
  return { splitOpen, peerSessionId, toggleSplit, pickPeer };
}
