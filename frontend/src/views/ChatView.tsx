import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "@/lib/api";
import { CHAT_PHASE_LABEL } from "@/lib/protocolChat";
import { candidatePreviewPaths, loadDockCollapsed, saveDockCollapsed } from "@/lib/artifacts";
import { copyText } from "@/lib/clipboard";
import { sessionTitle } from "@/lib/format";
import type { MessageOpResult } from "@/lib/messageOps";
import { shouldShowWaitHint } from "@/lib/waitHint";
import type { SettingsData, WorkspaceInfo } from "@/lib/types";
import { useChatStore } from "@/stores/chatStore";
import { usePrefsStore, type Verbosity } from "@/stores/prefsStore";
import { toast } from "@/stores/toastStore";
import { usePinnedScroll } from "@/hooks/usePinnedScroll";
import { ApprovalCard } from "@/components/chat/ApprovalCard";
import { PlanCard } from "@/components/chat/PlanCard";
import { ArtifactsPanel } from "@/components/chat/ArtifactsPanel";
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

/** 会话页：会话列表二级栏 + 聊天流 + 审批卡 + 输入区 + 右侧产出 dock（R12 P3）。 */
export function ChatView() {
  const {
    conn,
    chat,
    sessions,
    sessionsLoading,
    pendingAttachments,
    attaching,
    send,
    attachFiles,
    removePendingAttachment,
    respondApproval,
    respondPlan,
    stop,
    newSession,
    openSession,
    refreshSessions,
    deleteSession,
    promoteSession,
    regenerateMessage,
    editAndResend,
    reconnectNow,
  } = useChatStore();

  // R17 思考链显示分级：verbosity 档位（简洁/标准/调试），挂载时同步服务端
  const verbosity = usePrefsStore((s) => s.verbosity);
  const setVerbosity = usePrefsStore((s) => s.setVerbosity);
  useEffect(() => {
    void usePrefsStore.getState().hydrate();
  }, []);
  const VERBOSITY_NEXT: Record<Verbosity, Verbosity> = {
    minimal: "standard",
    standard: "debug",
    debug: "minimal",
  };
  const VERBOSITY_LABEL: Record<Verbosity, string> = {
    minimal: "简洁",
    standard: "标准",
    debug: "调试",
  };

  const [configured, setConfigured] = useState<boolean | null>(null);
  const [previewPaths, setPreviewPaths] = useState<string[] | null>(null);
  const [wsInfo, setWsInfo] = useState<WorkspaceInfo | null>(null);
  const [wsOpen, setWsOpen] = useState(false);
  // 与全局 toast（stores/toastStore）并存的历史遗留轻提示：仅承载发送失败等旧文案
  const [legacyToast, setLegacyToast] = useState("");

  // R17 会话路由化：/chat/:sessionId 深链 → 打开对应会话；列表打开会话时
  // 同步写回 URL（浏览器前进后退/复制链接/通知跳转由此成立）。
  const { sessionId: routeSessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  useEffect(() => {
    if (routeSessionId && routeSessionId !== chat.sessionId) {
      void openSession(routeSessionId)
        .then(() => refreshSessions())
        .catch(() => setLegacyToast("会话不存在或已被删除"));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeSessionId]);
  useEffect(() => {
    if (!routeSessionId && chat.sessionId) {
      // 列表内打开/新建后补写 URL（replace：不产生多余历史项）
      navigate(`/chat/${encodeURIComponent(chat.sessionId)}`, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chat.sessionId]);

  // ---- 产出 dock（C5）：折叠态记忆（与任务页共享）；xl(1280px) 以下默认收起 ----
  const [dockCollapsed, setDockCollapsed] = useState<boolean>(loadDockCollapsed);
  const toggleDock = useCallback(() => {
    setDockCollapsed((prev) => {
      const next = !prev;
      saveDockCollapsed(next);
      return next;
    });
  }, []);

  // ---- 草稿入列（R12 P4）：未发送的新会话在左侧列表置顶高亮，点击聚焦输入框 --
  const [draftFocusTick, setDraftFocusTick] = useState(0);

  // dock 根目录：connected 帧权威，恢复期兜底会话摘要（旧会话两者皆空 → null）
  const activeSummary = sessions.find((s) => s.id === chat.sessionId);
  const dockRoot = chat.outputsDir ?? activeSummary?.outputs_dir ?? null;

  // 回合结束（离开 running）→ 自增刷新信号，dock 免手动重载
  const [dockRefreshKey, setDockRefreshKey] = useState(0);
  const prevPhaseRef = useRef(chat.phase);
  useEffect(() => {
    if (prevPhaseRef.current === "running" && chat.phase !== "running") {
      setDockRefreshKey((k) => k + 1);
    }
    prevPhaseRef.current = chat.phase;
  }, [chat.phase]);

  // 等待看门狗（R9）：运行中若长时间没有任何可见输出（文本增量/工具卡），
  // 给出渐进提示——端点不可达时服务端要经历 超时×重试 才报错，不能让用户
  // 对着永久「思考中」干等。R13-I：长工具期没有文本增量，只有 cards/budget
  // 在更新——引用变化同样视为活动，否则误报「已等待 n 秒未见模型输出」。
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
  const silentSeconds = chat.phase === "running" ? Math.floor((nowTick - lastActivityAt.current) / 1000) : 0;

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

  // 智能滚动（R14-N）：贴底跟随 + 解除跟随期间的「回到底部」pill。
  // contentToken 用 chat.items 引用（store 合帧后逐帧换新）驱动跟随/计数；
  // 未读只数消息（user/text），工具卡不计入「N 条新消息」。
  const messageCount = useMemo(
    () => chat.items.reduce((n, i) => (i.kind === "tool" ? n : n + 1), 0),
    [chat.items],
  );
  const { containerRef, pinned, missedCount, scrollToBottom } = usePinnedScroll({
    contentToken: chat.items,
    messageCount,
    sessionKey: chat.sessionId,
  });
  // 流式进行中隐藏消息操作钮：regenerate/edit 此刻必被 busy 拒绝，藏起来更干净
  const opsEnabled = chat.phase !== "running";

  /* ---- 消息操作三件套（R14-M）：结果码 → 全局 toast ---- */
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

  // 稳定引用是气泡 memo 边界生效的前提（R14-R）：此前内联箭头每帧换新，
  // 会把所有工具卡行的 memo 打穿
  const handleOpenFile = useCallback(
    (p: string) => setPreviewPaths(candidatePreviewPaths(p, dockRoot)),
    [dockRoot],
  );

  // R13-B：状态串必须透传给 Composer——它据此决定是否恢复草稿
  const handleSend = useCallback(
    async (text: string) => {
      const r = await send(text);
      if (r === "offline") setLegacyToast("连接不可用，请稍候或新建会话");
      else if (r === "empty") setLegacyToast("消息不能为空");
      if (r === "ok") void refreshSessions();
      return r;
    },
    [send, refreshSessions],
  );

  const title = chat.sessionId
    ? sessionTitle(activeSummary?.title ?? null, activeSummary?.last_message ?? "")
    : chat.phase === "idle"
      ? "新会话"
      // R13-J：新会话兜底只用首条用户消息切片——旧的 sessions.find 兜底
      // 会把列表里别的会话的话题借来当标题，纯属张冠李戴
      : sessionTitle(
          null,
          String(chat.items.find((i) => i.kind === "user")?.text ?? ""),
        );

  // R16：reconnecting 是非致命态（服务端回合仍在跑）→ 警示横幅；自动重连
  // 放弃后 conn==="closed" → 危险横幅 + 手动重连按钮。旧「断连即终止」文案废除。
  const reconnectBanner =
    conn === "reconnecting"
      ? { tone: "warn" as const, text: "连接中断，正在自动重连……回合仍在后台运行，完成后自动保存。" }
      : conn === "closed" && chat.phase === "running"
        ? {
            tone: "danger" as const,
            text: "连接已中断且未能自动恢复——回合仍在服务端继续并会保存到历史；重新打开本会话或点击重连查看进展。",
          }
        : null;

  return (
    <div className="flex h-full min-h-0">
      {/* 会话列表二级栏 */}
      <div className="hidden w-60 shrink-0 border-r border-edge bg-canvas md:block">
        <SessionList
          sessions={sessions}
          activeId={chat.sessionId}
          loading={sessionsLoading}
          draftActive={chat.sessionId === null && chat.items.length === 0}
          onDraftClick={() => setDraftFocusTick((t) => t + 1)}
          onNew={() => newSession()}
          onOpen={(id) => void openSession(id).then(() => refreshSessions()).catch(() => {})}
          onDelete={async (id) => {
            try {
              await deleteSession(id);
              setLegacyToast("会话已删除");
            } catch {
              setLegacyToast("删除失败");
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
            <button
              type="button"
              title={`过程显示档位：${VERBOSITY_LABEL[verbosity]}（点击切换）——简洁=过程全折叠；标准=运行中自动展开；调试=全展开含堆栈/全参数`}
              onClick={() => setVerbosity(VERBOSITY_NEXT[verbosity])}
              className="rounded-lg border border-edge bg-surface px-2 py-1 text-[11px] font-medium text-ink-3 transition-colors hover:border-accent/40 hover:text-accent-hover dark:hover:text-accent"
            >
              {VERBOSITY_LABEL[verbosity]}
            </button>
            {chat.sessionId && chat.phase !== "running" && (
              <button
                type="button"
                title="把当前对话上下文打包为后台任务（任务中心可追踪，任务会回链本会话）"
                onClick={() => {
                  const sid = chat.sessionId;
                  if (!sid) return;
                  void promoteSession(sid)
                    .then((jobId) =>
                      setLegacyToast(
                        jobId
                          ? "已转为后台任务——进展见「任务中心」，任务与本会话已互链"
                          : "转为任务失败",
                      ),
                    )
                    .catch(() => setLegacyToast("转为任务失败"));
                }}
                className="rounded-lg border border-edge bg-surface px-2.5 py-1 text-[12px] font-medium text-ink-2 transition-colors hover:border-accent/40 hover:text-accent-hover dark:hover:text-accent"
              >
                转为任务
              </button>
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
        {(configured === false || reconnectBanner || chat.error || shouldShowWaitHint(chat.phase, silentSeconds)) && (
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
                {verbosity === "debug" && chat.errorTrace && (
                  <details className="mx-auto mt-1.5 max-w-3xl text-left">
                    <summary className="cursor-pointer text-[11px] text-danger/80">
                      堆栈详情（调试档）
                    </summary>
                    <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-canvas/60 p-2 font-mono text-[10.5px] leading-4 text-danger/90">
                      {chat.errorTrace}
                    </pre>
                  </details>
                )}
              </div>
            )}
            {reconnectBanner && (
              <div
                className={`flex items-center justify-center gap-3 px-5 py-2 text-center text-[12.5px] ${
                  reconnectBanner.tone === "warn"
                    ? "bg-warn/10 text-warn"
                    : "bg-danger/10 text-danger"
                }`}
              >
                <span>{reconnectBanner.text}</span>
                {reconnectBanner.tone === "danger" && (
                  <button
                    type="button"
                    onClick={reconnectNow}
                    className="shrink-0 rounded-lg border border-danger/40 bg-surface px-2 py-0.5 text-[11.5px] font-medium text-danger transition-colors hover:bg-surface-2"
                  >
                    重连
                  </button>
                )}
              </div>
            )}
            {shouldShowWaitHint(chat.phase, silentSeconds) && (
              <div className="bg-warn/10 px-5 py-2 text-center text-[12.5px] text-warn">
                已等待 {silentSeconds} 秒未见模型输出——首次响应慢或网络较慢时会这样；
                若持续停滞，多为网络无法直连模型端点，可到「设置 → 测试连接」验证，
                或点右上角「停止」。网络确属偏慢时，可在全局配置文件
                （%APPDATA%\ResearchAssistant\.env）中加 RA_LLM_FIRST_BYTE_TIMEOUT=30
                缩短首字节等待（单位秒）。
              </div>
            )}
          </div>
        )}

        {/* 消息流 + 回到底部 pill（R14-N）：pill 绝对定位于消息区右下角，
            与 Toaster 的视口右下角固定区天然错开（中间还隔着输入区） */}
        <div className="relative min-h-0 flex-1">
          <MessageList
            chat={chat}
            containerRef={containerRef}
            opsEnabled={opsEnabled}
            onOpenFile={handleOpenFile}
            onPickSuggestion={(t) => void handleSend(t)}
            onCopyMessage={handleCopyMessage}
            onRegenerate={handleRegenerate}
            onEditSubmit={handleEditSubmit}
          />
          <AnimatePresence>
            {!pinned && (
              <motion.button
                key="back-to-bottom"
                type="button"
                onClick={scrollToBottom}
                initial={{ opacity: 0, y: 12, scale: 0.96 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: 8, transition: { duration: 0.15, ease: "easeIn" } }}
                transition={{ duration: 0.18, ease: "easeOut" }}
                className="absolute bottom-4 right-5 z-20 flex items-center gap-2 rounded-full border border-edge bg-surface py-1.5 pl-3.5 pr-2.5 text-[12.5px] font-medium shadow-card transition-colors hover:bg-surface-2"
              >
                回到底部
                {missedCount > 0 && (
                  <span className="rounded-full bg-accent-tint px-2 py-0.5 text-[11px] font-medium text-accent-hover dark:text-accent">
                    {missedCount} 条新消息
                  </span>
                )}
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5 text-ink-3" aria-hidden>
                  <path d="M12 5v14" />
                  <path d="m19 12-7 7-7-7" />
                </svg>
              </motion.button>
            )}
          </AnimatePresence>
        </div>

        {/* 审批卡 / Plan 确认卡（悬浮于输入区上方；二者互斥——
            Plan 门 planner 阶段无工具，不会与工具审批并发） */}
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
          {!chat.approval && chat.plan && (
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 12 }}
              className="mx-auto w-full max-w-3xl px-4 pb-2"
            >
              <PlanCard plan={chat.plan} onRespond={respondPlan} />
            </motion.div>
          )}
        </AnimatePresence>

        <Composer
          running={chat.phase === "running"}
          disabled={conn === "connecting" || conn === "reconnecting"}
          focusSignal={draftFocusTick}
          pendingAttachments={pendingAttachments}
          attaching={attaching}
          onSend={handleSend}
          onAttach={(files) =>
            attachFiles(files).then((r) => {
              if (r === "offline") setLegacyToast("附件上传失败——请检查连接后重试");
              else if (r === "limit") setLegacyToast("单条消息最多 8 个附件");
              return r;
            })
          }
          onRemoveAttachment={removePendingAttachment}
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

      {/* 右侧产出 dock（R12 P3）：常驻可折叠；折叠为细条，展开为文件树+预览 */}
      <div className="hidden shrink-0 border-l border-edge bg-canvas md:block">
        {dockCollapsed ? (
          <button
            type="button"
            onClick={toggleDock}
            title="展开产出文件"
            aria-label="展开产出文件面板"
            className="flex h-full w-8 flex-col items-center gap-2 pt-3 text-ink-3 transition-colors hover:text-accent"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
              strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4" aria-hidden>
              <path d="m9 18 6-6-6-6" />
            </svg>
            <span
              className="text-[11px] font-medium"
              style={{ writingMode: "vertical-rl" }}
            >
              产出文件
            </span>
          </button>
        ) : (
          <div className="flex h-full w-72 flex-col">
            <ArtifactsPanel
              rootRelPath={dockRoot}
              refreshKey={dockRefreshKey}
              onCollapse={toggleDock}
            />
          </div>
        )}
      </div>

      {wsOpen && wsInfo && (
        <WorkspaceModal
          info={wsInfo}
          onClose={() => setWsOpen(false)}
          onSwitched={(next) => {
            setWsInfo(next);
            setWsOpen(false);
            // §6.4 空会话治理：会话目录属于工作区，切走后旧 sessionId 失效——
            // 若残留，下一条消息带旧 id 连入会触发服务端「幂等重建」，在新
            // 工作区造出无标题空目录。复位为全新会话（与删除活跃会话同语义）。
            newSession();
            setLegacyToast(`已切换到「${next.name}」`);
            refreshSessions().catch(() => {});
          }}
        />
      )}

      {previewPaths && previewPaths.length > 0 && (
        <FilePreviewModal paths={previewPaths} onClose={() => setPreviewPaths(null)} />
      )}

      {/* 轻提示（旧式底部居中，仅承载发送失败等遗留文案，待全局化后移除） */}
      <AnimatePresence>
        {legacyToast && (
          <motion.div
            key="toast"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            onAnimationComplete={() => {
              if (legacyToast) setTimeout(() => setLegacyToast(""), 2400);
            }}
            className="fixed bottom-24 left-1/2 z-40 -translate-x-1/2 rounded-xl bg-ink px-4 py-2 text-[12.5px] text-canvas shadow-card dark:text-ink"
          >
            {legacyToast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
