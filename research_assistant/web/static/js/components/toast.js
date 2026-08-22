/* toast 通知（替代 alert） */
import { el } from "../format.js";

export function toast(msg, type = "info", ttl = 4000) {
  const root = document.getElementById("toasts");
  const close = () => {
    box.classList.add("leaving");
    setTimeout(() => box.remove(), 200);
  };
  const box = el("div", { class: `toast t-${type}`, role: "status" },
    el("span", { class: "t-msg" }, msg),
    el("button", { class: "t-close", "aria-label": "关闭", onclick: close }, "✕"));
  root.append(box);
  if (ttl) setTimeout(close, ttl);
  return close;
}
