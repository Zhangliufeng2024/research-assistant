/* 全局审批 pending 信号（R14-A）：跨会话/任务通道的聚合感知。
 *
 * 数据流：approval_request 帧 → chatStore.chat.approval 或
 * taskStore.task.approval（各通道单槽位，回执/超时/result/error 后归约清空）。
 * 审批卡片只在对应视图可见——本模块在模块加载时订阅两个 store，维护：
 * - count：当前未决审批总数（0-2）；
 * - last：最近一次「新审批到达」信号（含到达时刻与来源），供非对应页面
 *   弹 toast 提醒「某会话/任务有操作待审批」。已解决与否不影响 last 保留。
 *
 * 注意：本文件被导入时即开始订阅（副作用在模块顶层）；视图侧只需 import
 * hooks 使用。count 用差量比较写回，避免无谓的订阅者通知。
 */
import { create } from "zustand";
import type { ApprovalInfo, ApprovalSignal, ApprovalSource } from "@/lib/types";
import { useChatStore } from "./chatStore";
import { useTaskStore } from "./taskStore";

interface ApprovalSignalState {
  /** 当前未决审批总数（chat + task 两通道各至多 1）。 */
  count: number;
  /** 最近一次新审批到达的信号；应用启动后尚无审批时为 null。 */
  last: ApprovalSignal | null;
}

export const useApprovalSignalStore = create<ApprovalSignalState>()(() => ({
  count: 0,
  last: null,
}));

/** 记录一次新到达（同 id 重复推送不重复记录——服务端可能重发同一请求）。 */
function recordArrival(
  source: ApprovalSource,
  prev: ApprovalInfo | null,
  next: ApprovalInfo,
): void {
  if (prev && prev.id === next.id) return;
  const signal: ApprovalSignal = {
    id: next.id,
    at: Date.now(),
    source,
    tool: next.tool,
    summary: next.summary,
  };
  useApprovalSignalStore.setState({ last: signal });
}

function track(
  source: ApprovalSource,
  prevApproval: ApprovalInfo | null,
  nextApproval: ApprovalInfo | null,
): void {
  if (nextApproval) recordArrival(source, prevApproval, nextApproval);
  const count =
    (useChatStore.getState().chat.approval ? 1 : 0) +
    (useTaskStore.getState().task.approval ? 1 : 0);
  if (useApprovalSignalStore.getState().count !== count) {
    useApprovalSignalStore.setState({ count });
  }
}

useChatStore.subscribe((s, prev) => {
  track("chat", prev.chat.approval, s.chat.approval);
});
useTaskStore.subscribe((s, prev) => {
  track("task", prev.task.approval, s.task.approval);
});

/** 未决审批总数（React 订阅；无审批时为 0）。 */
export function usePendingApprovalCount(): number {
  return useApprovalSignalStore((s) => s.count);
}

/** 最近一次新审批到达信号（React 订阅）；用于他页 toast 提醒。 */
export function useLastApprovalSignal(): ApprovalSignal | null {
  return useApprovalSignalStore((s) => s.last);
}

/* 非组件上下文（store action / 测试 / 工具函数）用的命令式读取。 */
export function getPendingApprovalCount(): number {
  return useApprovalSignalStore.getState().count;
}

export function getLastApprovalSignal(): ApprovalSignal | null {
  return useApprovalSignalStore.getState().last;
}
