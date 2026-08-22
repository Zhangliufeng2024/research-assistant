/* 阶段时间轴：plan → research ∥ figures → assemble → gates → revision → finalize */
import { el } from "../format.js";
import { TL_STAGES } from "../protocol.js";

export function renderTimeline(task) {
  const ol = el("ol", { class: "timeline", "aria-label": "阶段时间轴" });
  const states = task.timeline;

  TL_STAGES.forEach((st, i) => {
    const state = states[i] || "pending";
    const cls = `tl-stage ${state}`;
    const mark = state === "done" ? "✓" : "";
    ol.append(el("li", { class: cls },
      el("div", { class: "tl-dot" }, mark),
      el("div", { class: "tl-label" }, st.label),
      el("div", { class: "tl-sub" }, task.tlNote[st.key] || (state === "active" ? "···" : "")),
    ));
  });
  return ol;
}

/* 阶段中文名（活动流用） */
export function stageLabel(key) {
  const found = TL_STAGES.find((s) => s.key === key);
  return found ? found.label : key;
}
