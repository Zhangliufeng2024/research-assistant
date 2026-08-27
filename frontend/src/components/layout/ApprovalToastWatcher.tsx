/* 审批全局感知 watcher（R15）：挂在 Router 内，渲染 null。
 *
 * 订阅最近一次「新审批到达」信号（useLastApprovalSignal）：ref 记录已处理
 * 的信号 id，只对首次见到的 id 判定一次；用户当前不在对应来源页面
 * （chat→/chat，task→/tasks|/scheduler|/analysis）时用全局 toast 提醒。
 * pathname 变化会重跑 effect，但 seen 去重保证同一条信号至多提醒一次。
 */
import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { toast } from "@/stores/toastStore";
import { useLastApprovalSignal } from "@/stores/approvalSignal";
import { formatApprovalNotice, shouldNotifyApproval } from "./approvalNotify";

export function ApprovalToastWatcher() {
  const signal = useLastApprovalSignal();
  const { pathname } = useLocation();
  const seenIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!signal) return;
    if (seenIdsRef.current.has(signal.id)) return;
    seenIdsRef.current.add(signal.id);
    if (shouldNotifyApproval(pathname, signal.source)) {
      toast.info(formatApprovalNotice(signal));
    }
  }, [signal, pathname]);

  return null;
}
