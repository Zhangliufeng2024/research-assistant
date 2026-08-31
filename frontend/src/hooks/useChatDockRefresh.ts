/* 回合结束 → dock 免手动重载（从 ChatView 抽出，工程债拆分 2026-08-31）。 */
import { useEffect, useRef, useState } from "react";
import type { ChatState } from "@/lib/types";

export function useChatDockRefresh(chat: ChatState): number {
  const [dockRefreshKey, setDockRefreshKey] = useState(0);
  const prevPhaseRef = useRef(chat.phase);
  useEffect(() => {
    if (prevPhaseRef.current === "running" && chat.phase !== "running") {
      setDockRefreshKey((k) => k + 1);
    }
    prevPhaseRef.current = chat.phase;
  }, [chat.phase]);
  return dockRefreshKey;
}
