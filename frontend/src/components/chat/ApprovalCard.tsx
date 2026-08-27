import { useEffect, useState } from "react";
import {
  approvalExpired,
  remainingRatio,
  remainingSeconds,
} from "@/lib/format";
import { APPROVAL_TIMEOUT_S } from "@/lib/protocolChat";
import type { ApprovalInfo } from "@/lib/types";

/** 工具审批卡：工具名 + 摘要 + 批准/拒绝 + 120s 倒计时进度条。
 * R13-C：后端超时自动 deny 且不发清除帧——归零后本地置为过期态，
 * 按钮禁用、文案「已超时（默认拒绝）」，不再呈现可点击的假象。 */
export function ApprovalCard({
  approval,
  onRespond,
}: {
  approval: ApprovalInfo;
  onRespond: (ok: boolean) => void;
}) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, []);

  const expired = approvalExpired(approval.deadline, now);
  const remainS = remainingSeconds(approval.deadline, now);
  const ratio = remainingRatio(approval.deadline, now, APPROVAL_TIMEOUT_S);
  const urgent = !expired && remainS <= 20;

  return (
    <div
      role="alertdialog"
      aria-label="工具调用审批"
      className={`overflow-hidden rounded-2xl border bg-surface shadow-card ${
        expired
          ? "border-edge opacity-70"
          : urgent
            ? "border-danger/60"
            : "border-warn/60"
      }`}
    >
      <div className="px-4 pt-3.5">
        <div className="flex items-center gap-2">
          <span className={`text-base leading-none ${expired ? "text-ink-3" : "text-warn"}`}>⚠</span>
          <span className={`text-[13px] font-semibold ${expired ? "text-ink-3" : ""}`}>
            {expired ? "已超时（默认拒绝）" : "工具调用待审批"}
          </span>
          <span className="ml-auto font-mono text-[12px] tabular-nums text-ink-2">
            {expired ? "—" : `${remainS}s`}
          </span>
        </div>
        <div className="mt-2.5 rounded-xl bg-surface-2 px-3 py-2.5">
          <div className="font-mono text-[12px] font-medium text-accent-hover dark:text-accent">
            {approval.tool}
          </div>
          {(approval.agentId || approval.role) && (
            <div className="mt-1 text-[10px] text-ink-3">
              Agent {approval.agentId || "—"} · {approval.role || "未指定角色"}
            </div>
          )}
          {approval.summary && (
            <div className="mt-1 break-all font-mono text-[11.5px] leading-5 text-ink-2">
              {approval.summary}
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 h-1 w-full bg-surface-2">
        <div
          className={`h-full transition-[width] duration-500 ease-linear ${
            expired ? "bg-transparent" : urgent ? "bg-danger" : "bg-warn"
          }`}
          style={{ width: `${expired ? 0 : ratio * 100}%` }}
        />
      </div>

      <div className="flex gap-2 px-4 py-3">
        <button
          type="button"
          onClick={() => onRespond(true)}
          disabled={expired}
          title={expired ? "已超时，服务端已默认拒绝" : undefined}
          className="flex-1 rounded-xl bg-accent px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent"
        >
          批准
        </button>
        <button
          type="button"
          onClick={() => onRespond(false)}
          disabled={expired}
          title={expired ? "已超时，服务端已默认拒绝" : undefined}
          className="flex-1 rounded-xl border border-edge bg-surface px-4 py-2 text-[13px] font-medium text-ink transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40"
        >
          拒绝
        </button>
      </div>
    </div>
  );
}
