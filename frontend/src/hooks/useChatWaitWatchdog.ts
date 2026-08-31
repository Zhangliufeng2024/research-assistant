/* 运行期静默看门狗（R9/R13-I）：长时无可见输出时给出等待提示。
 * 从 ChatView 抽出，工程债拆分 2026-08-31。 */
import { useEffect, useRef, useState } from "react";
import type { ChatState } from "@/lib/types";

export function useChatWaitWatchdog(chat: ChatState): number {
  const [nowTick, setNowTick] = useState(() => Date.now());
  const lastActivityAt = useRef(Date.now());
  useEffect(() => {
    if (chat.phase === "running") lastActivityAt.current = Date.now();
  }, [chat.items, chat.cards, chat.budget]);
  useEffect(() => {
    if (chat.phase !== "running") return;
    const t = setInterval(() => setNowTick(Date.now()), 1000);
    return () => clearInterval(t);
  }, [chat.phase]);
  return chat.phase === "running"
    ? Math.floor((nowTick - lastActivityAt.current) / 1000)
    : 0;
}
