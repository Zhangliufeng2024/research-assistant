/* /chat/:sessionId 深链同步（从 ChatView 抽出，工程债拆分 2026-08-31）。 */
import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";

export function useChatSessionRouting(
  sessionId: string | null,
  openSession: (id: string) => Promise<void>,
  refreshSessions: () => Promise<void>,
  onError: (message: string) => void,
) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const routeSessionId = /^\/chat\/([^/]+)/.exec(pathname)?.[1];

  useEffect(() => {
    if (routeSessionId && decodeURIComponent(routeSessionId) !== sessionId) {
      void openSession(decodeURIComponent(routeSessionId))
        .then(() => refreshSessions())
        .catch(() => onError("会话不存在或已被删除"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeSessionId]);

  useEffect(() => {
    if (!routeSessionId && sessionId) {
      navigate(`/chat/${encodeURIComponent(sessionId)}`, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);
}
