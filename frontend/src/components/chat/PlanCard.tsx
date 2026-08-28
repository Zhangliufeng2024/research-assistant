import { useEffect, useState } from "react";
import { remainingSeconds } from "@/lib/format";
import type { PlanProposal } from "@/lib/types";

/** Plan 确认卡（方案 1）：/plan 回合的待决计划。
 * 计划全文已在消息流中流式出现过，卡内再完整呈现一次供通读确认；
 * 批准 → 服务端按计划执行原请求；拒绝/超时 → 本轮到此收场。
 * 10 分钟倒计时只是本地置灰口径——真正的超时裁决由服务端做出（deny）。 */
export function PlanCard({
  plan,
  onRespond,
}: {
  plan: PlanProposal;
  onRespond: (ok: boolean) => void;
}) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, []);

  const expired = Date.now() >= plan.deadline;
  const remainS = remainingSeconds(plan.deadline, now);
  const urgent = !expired && remainS <= 60;

  return (
    <div
      role="alertdialog"
      aria-label="执行计划确认"
      className={`overflow-hidden rounded-2xl border bg-surface shadow-card ${
        expired ? "border-edge opacity-70" : urgent ? "border-warn/60" : "border-accent/50"
      }`}
    >
      <div className="px-4 pt-3.5">
        <div className="flex items-center gap-2">
          <span className={`text-base leading-none ${expired ? "text-ink-3" : "text-accent"}`}>🗂</span>
          <span className={`text-[13px] font-semibold ${expired ? "text-ink-3" : ""}`}>
            {expired ? "已超时（本轮不执行）" : "执行计划待确认"}
          </span>
          <span className="ml-auto font-mono text-[12px] tabular-nums text-ink-2">
            {expired ? "—" : `${remainS}s`}
          </span>
        </div>
        <pre className="mt-2.5 max-h-56 overflow-auto whitespace-pre-wrap rounded-xl bg-surface-2 px-3 py-2.5 font-mono text-[11.5px] leading-5 text-ink-2">
          {plan.plan || "（空计划）"}
        </pre>
      </div>
      <div className="flex gap-2 px-4 py-3">
        <button
          type="button"
          onClick={() => onRespond(true)}
          disabled={expired}
          title={expired ? "已超时，服务端已按拒绝收场" : "批准后按此计划执行"}
          className="flex-1 rounded-xl bg-accent px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent"
        >
          同意，按计划执行
        </button>
        <button
          type="button"
          onClick={() => onRespond(false)}
          disabled={expired}
          title={expired ? "已超时，服务端已按拒绝收场" : "拒绝后本轮不执行，可修改请求重发"}
          className="flex-1 rounded-xl border border-edge bg-surface px-4 py-2 text-[13px] font-medium text-ink transition-colors hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-40"
        >
          拒绝
        </button>
      </div>
    </div>
  );
}
