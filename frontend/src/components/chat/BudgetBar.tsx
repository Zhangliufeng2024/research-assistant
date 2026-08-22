import { formatDuration, formatTokens } from "@/lib/format";
import type { BudgetSnapshot } from "@/lib/types";

function Chip({
  label,
  value,
  title,
}: {
  label: string;
  value: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 rounded-lg bg-surface-2 px-2 py-1 font-mono text-[11px] text-ink-2"
    >
      <span className="text-ink-3">{label}</span>
      {value}
    </span>
  );
}

/** 预算状态条：token / 费用 / 回合 / 用时；上限不可执行时给 ⚠ 提示。 */
export function BudgetBar({ budget }: { budget: BudgetSnapshot }) {
  const limits = (budget.limits || {}) as Record<string, number | null>;
  const capSet = !!limits.max_cost_usd;
  const enforceable = budget.cost_cap_enforceable !== false;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Chip label="tok" value={formatTokens(budget.total_tokens)} title="总 token 数" />
      <Chip
        label="$"
        value={String(budget.cost_usd ?? "0")}
        title={capSet && !enforceable ? "已设费用上限，但当前模型价格未知，无法强制执行" : "累计费用（USD）"}
      />
      {capSet && !enforceable && (
        <span
          title="已设费用上限，但当前模型价格未知，无法强制执行"
          className="text-[13px] leading-none text-warn"
        >
          ⚠
        </span>
      )}
      <Chip label="轮" value={String(budget.turns ?? 0)} title="agent 回合数" />
      <Chip label="⏱" value={formatDuration(budget.elapsed_seconds)} title="运行用时" />
    </div>
  );
}
