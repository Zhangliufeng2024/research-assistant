/* 预算仪表：成本（含上限进度条）/ tokens / turns / 时长 */
import { el, fmtCost, fmtNum, fmtClock } from "../format.js";

export function renderBudget(task) {
  const b = task.budget;
  if (!b) {
    return el("div", { class: "empty", style: "padding:24px" }, "等待用量数据…");
  }
  const wrap = el("div", { class: "panel-pad" });

  // 成本 + 上限进度
  const lim = (b.limits || {}).max_cost_usd || null;
  const cost = b.cost_usd ?? 0;
  wrap.append(el("div", { class: "b-row" },
    el("span", { class: "b-label" }, "花费"),
    el("span", { class: "b-val hi" },
      fmtCost(cost), lim ? el("span", { class: "b-val lim" }, ` / 上限 ${fmtCost(lim)}`) : null)));
  if (lim && lim > 0) {
    const pct = Math.min(100, (cost / lim) * 100);
    wrap.append(el("div", { class: "cost-track" },
      el("div", { class: `cost-fill ${pct >= 80 ? "hot" : ""}`, style: `width:${pct}%` })));
  }

  wrap.append(
    el("div", { class: "b-row" },
      el("span", { class: "b-label" }, "Tokens"),
      el("span", { class: "b-val" }, fmtNum(b.total_tokens))),
    el("div", { class: "b-row" },
      el("span", { class: "b-label" }, "LLM 轮次"),
      el("span", { class: "b-val" }, fmtNum(b.turns))),
    el("div", { class: "b-row" },
      el("span", { class: "b-label" }, "已用时"),
      el("span", { class: "b-val" }, fmtClock(b.elapsed))),
  );
  return wrap;
}
