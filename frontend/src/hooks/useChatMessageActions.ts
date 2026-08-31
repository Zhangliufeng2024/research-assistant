/* 消息操作三件套（重新生成/编辑重发/复制）+ 运行期禁用判定。
 * 从 ChatView 抽出，工程债拆分 2026-08-31。 */
import { useCallback } from "react";
import { copyText } from "@/lib/clipboard";
import type { MessageOpResult } from "@/lib/messageOps";
import type { ChatState } from "@/lib/types";
import { toast } from "@/stores/toastStore";

export function useChatMessageActions(
  chat: ChatState,
  refreshSessions: () => Promise<void>,
  regenerateMessage: (sessionId: string | null, messageId: number) => Promise<MessageOpResult>,
  editAndResend: (
    sessionId: string | null,
    messageId: number,
    newText: string,
  ) => Promise<MessageOpResult>,
) {
  const opsEnabled = chat.phase !== "running";

  const reportOpResult = useCallback((r: MessageOpResult) => {
    if (r === "busy") toast.info("助手正在回复中——本回合结束后再试");
    else if (r === "offline") toast.error("连接不可用，请稍候或新建会话");
    else if (r === "empty") toast.info("没有找到可操作的消息");
  }, []);

  const handleRegenerate = useCallback(
    (idx: number) => {
      void regenerateMessage(chat.sessionId, idx).then((r) => {
        reportOpResult(r);
        if (r === "ok") void refreshSessions();
      });
    },
    [regenerateMessage, chat.sessionId, refreshSessions, reportOpResult],
  );

  const handleEditSubmit = useCallback(
    async (idx: number, newText: string): Promise<MessageOpResult> => {
      const r = await editAndResend(chat.sessionId, idx, newText);
      reportOpResult(r);
      if (r === "ok") void refreshSessions();
      return r;
    },
    [editAndResend, chat.sessionId, refreshSessions, reportOpResult],
  );

  const handleCopyMessage = useCallback((text: string) => {
    void copyText(text).then((okFlag) => {
      if (okFlag) toast.success("已复制");
      else toast.error("复制失败——剪贴板不可用，请手动选择文本复制");
    });
  }, []);

  return { opsEnabled, handleRegenerate, handleEditSubmit, handleCopyMessage };
}
