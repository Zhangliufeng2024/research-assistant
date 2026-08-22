import { useEffect, useState } from "react";
import { APPROVAL_TIMEOUT_S } from "@/lib/protocolChat";
import type { ApprovalInfo } from "@/lib/types";

/** 工具审批卡：工具名 + 摘要 + 批准/拒绝 + 120s 倒计时进度条。 */
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

  const remainMs = Math.max(0, approval.deadline - now);
  const remainS = Math.ceil(remainMs / 1000);
  const ratio = remainMs / (APPROVAL_TIMEOUT_S * 1000);
  const urgent = remainS <= 20;

  return (
    <div
      role="alertdialog"
      aria-label="工具调用审批"
      className={`overflow-hidden rounded-2xl border bg-surface shadow-card ${
        urgent ? "border-danger/60" : "border-warn/60"
      }`}
    >
      <div className="px-4 pt-3.5">
        <div className="flex items-center gap-2">
          <span className="text-base leading-none text-warn">⚠</span>
          <span className="text-[13px] font-semibold">工具调用待审批</span>
          <span className="ml-auto font-mono text-[12px] tabular-nums text-ink-2">
            {remainS}s
          </span>
        </div>
        <div className="mt-2.5 rounded-xl bg-surface-2 px-3 py-2.5">
          <div className="font-mono text-[12px] font-medium text-accent-hover dark:text-accent">
            {approval.tool}
          </div>
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
            urgent ? "bg-danger" : "bg-warn"
          }`}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>

      <div className="flex gap-2 px-4 py-3">
        <button
          type="button"
          onClick={() => onRespond(true)}
          className="flex-1 rounded-xl bg-accent px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover"
        >
          批准
        </button>
        <button
          type="button"
          onClick={() => onRespond(false)}
          className="flex-1 rounded-xl border border-edge bg-surface px-4 py-2 text-[13px] font-medium text-ink transition-colors hover:bg-surface-2"
        >
          拒绝
        </button>
      </div>
    </div>
  );
}
