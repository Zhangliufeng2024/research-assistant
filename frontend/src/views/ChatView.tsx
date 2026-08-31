import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import { api } from "@/lib/api";
import { CHAT_PHASE_LABEL } from "@/lib/protocolChat";
import { candidatePreviewPaths } from "@/lib/artifacts";
import { sessionTitle } from "@/lib/format";
import { shouldShowWaitHint } from "@/lib/waitHint";
import { useChatStore } from "@/stores/chatStore";
import { NEW_DRAFT_KEY } from "@/stores/sessionStore";
import { usePrefsStore, type Verbosity } from "@/stores/prefsStore";
import { usePinnedScroll } from "@/hooks/usePinnedScroll";
import { useChatBootstrap } from "@/hooks/useChatBootstrap";
import { useChatDockRefresh } from "@/hooks/useChatDockRefresh";
import { useChatInspector } from "@/hooks/useChatInspector";
import { useChatMessageActions } from "@/hooks/useChatMessageActions";
import { useChatScrollAnchors } from "@/hooks/useChatScrollAnchors";
import { useChatSessionRouting } from "@/hooks/useChatSessionRouting";
import { useChatSplitPeer } from "@/hooks/useChatSplitPeer";
import { useChatWaitWatchdog } from "@/hooks/useChatWaitWatchdog";
import { ApprovalCard } from "@/components/chat/ApprovalCard";
import { PlanCard } from "@/components/chat/PlanCard";
import { ArtifactsPanel } from "@/components/chat/ArtifactsPanel";
import { BudgetBar } from "@/components/chat/BudgetBar";
import { Composer, type EnhanceOutcome } from "@/components/chat/Composer";
import { FilePreviewModal } from "@/components/chat/FilePreviewModal";
import { MessageList } from "@/components/chat/MessageList";
import { PeerSessionPanel } from "@/components/chat/PeerSessionPanel";
import { WorkspaceModal } from "@/components/chat/WorkspaceModal";
import { NotificationsButton } from "@/components/layout/WorkspaceSearch";

const PHASE_DOT: Record<string, string> = {
  idle: "bg-ink-3",
  running: "bg-warn animate-pulse",
  done: "bg-ok",
  error: "bg-danger",
};

/** 会话区：由 App 常驻挂载；active=当前路由处于会话区（控制可见性）。
 * 逻辑已按域拆到 hooks/（useChat*，工程债拆分 2026-08-31），本组件只做组合。 */
export function ChatView({ active = true }: { active?: boolean }) {
  const {
    conn,
    chat,
    sessions,
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

  const [previewPaths, setPreviewPaths] = useState<string[] | null>(null);
  const [wsOpen, setWsOpen] = useState(false);
  // 与全局 toast（stores/toastStore）并存的历史遗留轻提示：仅承载发送失败等旧文案
  const [legacyToast, setLegacyToast] = useState("");

  const { configured, wsInfo, setWsInfo } = useChatBootstrap(refreshSessions);
  useChatSessionRouting(
    chat.sessionId,
    openSession,
    refreshSessions,
    (message) => setLegacyToast(message),
  );

  // ---- 检查器（阶段 4）：宽屏 ≥1280px 内联 dock（Ctrl+I 开关）；<1280px 抽屉
  const {
    isWide,
    inspectorOpen,
    inspectorDrawerOpen,
    setInspectorDrawerOpen,
    toggleInspector,
    composerFocusTick,
  } = useChatInspector();

  // dock 根目录：connected 帧权威，恢复期兜底会话摘要（旧会话两者皆空 → null）
  const activeSummary = sessions.find((s) => s.id === chat.sessionId);
  const dockRoot = chat.outputsDir ?? activeSummary?.outputs_dir ?? null;
  const dockRefreshKey = useChatDockRefresh(chat);
  const silentSeconds = useChatWaitWatchdog(chat);

  // 智能滚动（R14-N）：贴底跟随 + 解除跟随期间的「回到底部」pill。
  const messageCount = useMemo(
    () => chat.items.reduce((n, i) => (i.kind === "tool" ? n : n + 1), 0),
    [chat.items],
  );
  const { containerRef, pinned, missedCount, scrollToBottom } = usePinnedScroll({
    contentToken: chat.items,
    messageCount,
    sessionKey: chat.sessionId,
  });
  useChatScrollAnchors(active, chat, containerRef, pinned);

  // ---- 消息操作三件套（R14-M）+ 运行期禁用判定 ----
  const {
    opsEnabled,
    handleRegenerate,
    handleEditSubmit,
    handleCopyMessage,
  } = useChatMessageActions(
    chat,
    refreshSessions,
    regenerateMessage,
    editAndResend,
  );

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

  /** R18 提示词增强：一次独立的短请求，不进会话历史、不占回合。
   * 失败一律保留原文并回传原因——绝不静默吞掉，也绝不改动用户写好的话。 */
  const handleEnhance = useCallback(
    async (text: string): Promise<EnhanceOutcome> => {
      try {
        const r = await api.post<{ ok: boolean; enhanced?: string; error?: string }>(
          "/api/prompt/enhance",
          { text },
          60_000,
        );
        if (r.ok && r.enhanced) return { ok: true, text: r.enhanced };
        return { ok: false, error: r.error || "模型未返回有效内容，请重试" };
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return { ok: false, error: `提示词增强失败：${msg}` };
      }
    },
    [],
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

  // 迭代2：分屏对照——主区交互 + 右侧只读对照会话（纯 UI 偏好入 localStorage）
  const { splitOpen, peerSessionId, toggleSplit, pickPeer } = useChatSplitPeer(
    sessions,
    chat.sessionId,
  );

  return (
    <div className="flex h-full min-h-0 flex-1">
      {/* 主聊天列（会话列表已外置为导航栏二级抽屉 SessionDrawer） */}
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
            {/* 窄屏检查器入口（U-11：<1280px dock 变抽屉，入口常在） */}
            {!isWide && (
              <button
                type="button"
                title="产物文件面板（窄屏为抽屉形态）"
                aria-pressed={inspectorDrawerOpen}
                onClick={() => setInspectorDrawerOpen(!inspectorDrawerOpen)}
                className={`rounded-lg border px-2 py-1 text-[11px] font-medium transition-colors ${
                  inspectorDrawerOpen
                    ? "border-accent/50 bg-accent-tint text-accent-hover dark:text-accent"
                    : "border-edge bg-surface text-ink-3 hover:border-accent/40 hover:text-accent-hover dark:hover:text-accent"
                }`}
              >
                产物
              </button>
            )}
            <NotificationsButton />
            <button
              type="button"
              title={splitOpen ? "关闭分屏对照" : "分屏对照——右侧只读展示另一会话"}
              aria-pressed={splitOpen}
              onClick={toggleSplit}
              className={`hidden rounded-lg border px-2 py-1 text-[11px] font-medium transition-colors lg:block ${
                splitOpen
                  ? "border-accent/50 bg-accent-tint text-accent-hover dark:text-accent"
                  : "border-edge bg-surface text-ink-3 hover:border-accent/40 hover:text-accent-hover dark:hover:text-accent"
              }`}
            >
              分屏
            </button>
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
          focusSignal={composerFocusTick}
          draftKey={chat.sessionId ?? NEW_DRAFT_KEY}
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
          onEnhance={handleEnhance}
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

      {/* 迭代2：分屏对照栏——只读第二会话（REST 快照 + 20s 轮询） */}
      {splitOpen && (
        <div className="hidden w-[360px] shrink-0 border-l border-edge xl:block">
          <PeerSessionPanel
            sessionId={peerSessionId}
            sessions={sessions}
            excludeId={chat.sessionId}
            onPick={pickPeer}
            onClose={toggleSplit}
          />
        </div>
      )}

      {/* 检查器（阶段 4）：宽屏内联 dock（Ctrl+I 开关）；窄屏抽屉（U-11） */}
      {isWide && (
        <div className="shrink-0 border-l border-edge bg-canvas">
          {inspectorOpen ? (
            <div className="flex h-full w-72 flex-col">
              <ArtifactsPanel
                rootRelPath={dockRoot}
                refreshKey={dockRefreshKey}
                onCollapse={toggleInspector}
              />
            </div>
          ) : (
            <button
              type="button"
              onClick={toggleInspector}
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
          )}
        </div>
      )}

      {/* 窄屏检查器抽屉：<1280px 滑出，内容复用同一 ArtifactsPanel */}
      {!isWide && inspectorDrawerOpen && (
        <div
          data-testid="inspector-drawer"
          className="fixed inset-0 z-30 bg-black/20"
          onMouseDown={() => setInspectorDrawerOpen(false)}
        >
          <aside
            aria-label="检查器"
            className="absolute bottom-0 right-0 top-0 w-80 border-l border-edge bg-canvas shadow-xl"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="flex h-full w-full flex-col">
              <ArtifactsPanel
                rootRelPath={dockRoot}
                refreshKey={dockRefreshKey}
                onCollapse={() => setInspectorDrawerOpen(false)}
              />
            </div>
          </aside>
        </div>
      )}

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
