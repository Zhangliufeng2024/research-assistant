/* 会话区首屏引导：标题、会话列表、设置与工作区信息（从 ChatView 抽出）。 */
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SettingsData, WorkspaceInfo } from "@/lib/types";

export function useChatBootstrap(refreshSessions: () => Promise<void>) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [wsInfo, setWsInfo] = useState<WorkspaceInfo | null>(null);
  useEffect(() => {
    document.title = "研究助手 · 会话";
    refreshSessions().catch(() => {});
    api
      .get<SettingsData>("/api/settings")
      .then((s) => setConfigured(!!s.configured))
      .catch(() => setConfigured(null));
    api
      .get<WorkspaceInfo>("/api/workspace")
      .then(setWsInfo)
      .catch(() => {});
  }, [refreshSessions]);
  return { configured, wsInfo, setWsInfo };
}
