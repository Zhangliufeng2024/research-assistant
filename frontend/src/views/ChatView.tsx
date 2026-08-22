import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "@/lib/api";
import { CHAT_PHASE_LABEL } from "@/lib/protocolChat";
import { sessionTitle } from "@/lib/format";
import type { SettingsData, WorkspaceInfo } from "@/lib/types";
import { useChatStore } from "@/stores/chatStore";
import { ApprovalCard } from "@/components/chat/ApprovalCard";
import { BudgetBar } from "@/components/chat/BudgetBar";
import { Composer } from "@/components/chat/Composer";
import { FilePreviewModal } from "@/components/chat/FilePreviewModal";
import { MessageList } from "@/components/chat/MessageList";
import { SessionList } from "@/components/chat/SessionList";
import { WorkspaceModal } from "@/components/chat/WorkspaceModal";

const PHASE_DOT: Record<string, string> = {
  idle: "bg-ink-3",
  running: "bg-warn animate-pulse",
  done: "bg-ok",
  error: "bg-danger",
};

/** 会话页：会话列表二级栏 + 聊天流 + 审批卡 + 输入区。 */
export function ChatView() {
  const {
    conn,
    chat,
    sessions,
    sessionsLoading,
    send,
    respondApproval,
    stop,
    newSession,
    openSession,
    refreshSessions,
    deleteSession,
  } = useChatStore();

  const [configured, setConfigured] = useState<boolean | null>(null);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const [wsInfo, setWsInfo] = useState<WorkspaceInfo | null>(null);
  const [wsOpen, setWsOpen] = useState(false);
  const [toast, setToast] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

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

  // 自动滚动：仅在用户本就贴近底部时跟随（避免打断回看）
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [chat.items, chat.approval]);

  const onScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 90;
  }, []);

  const handleSend = useCallback(
    async (text: string) => {
      const r = await send(text);
      if (r === "offline") setToast("连接不可用，请稍候或新建会话");
      else if (r === "empty") setToast("消息不能为空");
      if (r === "ok") void refreshSessions();
    },
    [send, refreshSessions],
  );

  const activeSummary = sessions.find((s) => s.id === chat.sessionId);
  const title = chat.sessionId
    ? sessionTitle(activeSummary?.title ?? null, activeSummary?.last_message ?? "")
    : chat.phase === "idle"
      ? "新会话"
      : sessionTitle(
          sessions.find((s) => s.last_message)?.title ?? null,
          String(chat.items.find((i) => i.kind === "user")?.text ?? ""),
        );

  const connBanner =
    conn === "error"
      ? "无法建立与服务端的连接——请确认应用服务正在运行。"
      : conn === "closed" && chat.phase === "running"
        ? "连接已断开，服务端已停止本次运行；重新发送可继续对话。"
        : null;

  return (
    <div className="flex h-full min-h-0">
      {/* 会话列表二级栏 */}
      <div className="hidden w-60 shrink-0 border-r border-edge bg-canvas md:block">
        <SessionList
          sessions={sessions}
          activeId={chat.sessionId}
          loading={sessionsLoading}
          onNew={() => newSession()}
          onOpen={(id) => void openSession(id).then(() => refreshSessions()).catch(() => {})}
          onDelete={async (id) => {
            try {
              await deleteSession(id);
              setToast("会话已删除");
            } catch {
              setToast("删除失败");
            }
          }}
        />
      </div>

      {/* 主聊天列 */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* 工具条 */}
        <div className="flex shrink-0 items-center gap-2.5 border-b border-edge px-5 py-2.5">
          <span className={`h-2 w-2 shrink-0 rounded-full ${PHASE_DOT[chat.phase]}`} />
          <span className="truncate text-[13px] font-medium">{title}</span>
          <span className="shrink-0 text-[11px] text-ink-3">
            {CHAT_PHASE_LABEL[chat.phase]}
          </span>
          <div className="ml-auto flex items-center gap-2.5">
            {chat.budget && (
              <div className="hidden sm:block">
                <BudgetBar budget={chat.budget} />
              </div>
            )}
            {chat.phase === "running" && (
              <button
                type="button"
                onClick={() => stop()}
                className="rounded-lg border border-edge bg-surface px-2.5 py-1 text-[12px] font-medium text-danger transition-colors hover:bg-surface-2"
              >
                停止
              </button>
            )}
          </div>
        </div>

        {/* 横幅区 */}
        {(configured === false || connBanner || chat.error) && (
          <div className="shrink-0 space-y-px">
            {configured === false && (
              <Link
                to="/settings"
                className="block bg-warn/10 px-5 py-2 text-center text-[12.5px] text-warn transition-colors hover:bg-warn/15"
              >
                尚未配置模型服务——点击前往「设置」填写 API Key →
              </Link>
            )}
            {chat.error && (
              <div className="bg-danger/10 px-5 py-2 text-center text-[12.5px] text-danger">
                出错：{chat.error}（重新发送即可重试）
              </div>
            )}
            {connBanner && (
              <div className="bg-danger/10 px-5 py-2 text-center text-[12.5px] text-danger">
                {connBanner}
              </div>
            )}
          </div>
        )}

        <MessageList
          chat={chat}
          scrollRef={scrollRef}
          onScroll={onScroll}
          onOpenFile={setPreviewPath}
          onPickSuggestion={(t) => void handleSend(t)}
        />

        {/* 审批卡（悬浮于输入区上方） */}
        <AnimatePresence>
          {chat.approval && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 12 }}
              className="mx-auto w-full max-w-3xl px-4 pb-2"
            >
              <ApprovalCard approval={chat.approval} onRespond={respondApproval} />
            </motion.div>
          )}
        </AnimatePresence>

        <Composer
          running={chat.phase === "running"}
          disabled={conn === "connecting"}
          onSend={(t) => void handleSend(t)}
        />

        {/* 工作目录入口（R8 反馈 #1：Claude Desktop 式，对话框下方随时更换） */}
        <button
          type="button"
          onClick={() => setWsOpen(true)}
          title={wsInfo?.root || ""}
          className="mx-auto mb-2.5 flex max-w-full shrink-0 items-center gap-1.5 px-2 text-[11.5px] text-ink-3 transition-colors hover:text-accent"
        >
          <span aria-hidden>📁</span>
          工作目录：
          <span className="max-w-[16rem] truncate font-medium">
            {wsInfo?.name ?? "…"}
          </span>
          · 点击更换
        </button>
      </div>

      {wsOpen && wsInfo && (
        <WorkspaceModal
          info={wsInfo}
          onClose={() => setWsOpen(false)}
          onSwitched={(next) => {
            setWsInfo(next);
            setWsOpen(false);
            setToast(`已切换到「${next.name}」`);
            refreshSessions().catch(() => {});
          }}
        />
      )}

      {previewPath && (
        <FilePreviewModal path={previewPath} onClose={() => setPreviewPath(null)} />
      )}

      {/* 轻提示 */}
      <AnimatePresence>
        {toast && (
          <motion.div
            key="toast"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            onAnimationComplete={() => {
              if (toast) setTimeout(() => setToast(""), 2400);
            }}
            className="fixed bottom-24 left-1/2 z-40 -translate-x-1/2 rounded-xl bg-ink px-4 py-2 text-[12.5px] text-canvas shadow-card dark:text-ink"
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
