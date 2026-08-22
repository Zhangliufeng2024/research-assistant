/* 遮罩层：图片/PDF 预览 + Promise 化 confirm（替代原生 confirm） */
import { el, esc } from "../format.js";

function overlay(onClose) {
  const ov = el("div", { class: "modal-overlay" });
  ov.addEventListener("click", (e) => { if (e.target === ov) onClose(); });
  const onEsc = (e) => { if (e.key === "Escape") { e.stopPropagation(); onClose(); } };
  document.addEventListener("keydown", onEsc);
  const dispose = () => {
    ov.remove();
    document.removeEventListener("keydown", onEsc);
  };
  return { ov, dispose };
}

export function showImage(url, name = "") {
  const { ov, dispose } = overlay(dispose);
  const body = el("div", { class: "modal-body" },
    el("button", { class: "modal-close", "aria-label": "关闭", onclick: () => dispose() }, "✕"),
    el("img", { src: url, alt: name }),
    name ? el("div", { class: "modal-caption" }, name) : null);
  ov.append(body);
  document.getElementById("modal-root").append(ov);
}

export function showPdf(url, name = "") {
  const { ov, dispose } = overlay(dispose);
  const body = el("div", { class: "modal-body" },
    el("button", { class: "modal-close", "aria-label": "关闭", onclick: () => dispose() }, "✕"),
    el("iframe", { src: url, title: name || "PDF 预览" }));
  ov.append(body);
  document.getElementById("modal-root").append(ov);
}

/* Promise 化确认框；resolve(true/false) */
export function confirmDialog(message, { danger = true, okText = "确认", cancelText = "取消" } = {}) {
  return new Promise((resolve) => {
    const done = (v) => { dispose(); resolve(v); };
    const { ov, dispose } = overlay(() => done(false));
    const box = el("div", { class: "modal-body", style: "max-width:420px" },
      el("div", { class: "panel-pad", style: "font-size:13.5px; line-height:1.8" },
        el("div", { html: esc(message) }),
        el("div", { class: "approval-actions", style: "margin-top:16px" },
          el("button", { class: `btn ${danger ? "btn-danger" : "btn-amber"}`, onclick: () => done(true) }, okText),
          el("button", { class: "btn btn-ghost", onclick: () => done(false) }, cancelText))));
    ov.append(box);
    document.getElementById("modal-root").append(ov);
  });
}

/* 通用内容面板（调用方自填 DOM），返回 {close} */
export function panelModal(title, buildContent) {
  const { ov, dispose } = overlay(dispose);
  const body = el("div", { class: "modal-body", style: "width:min(720px,92vw);max-height:86vh" },
    el("button", { class: "modal-close", "aria-label": "关闭", onclick: () => dispose() }, "✕"));
  if (title) body.append(el("div", { class: "panel-head" }, title));
  const content = el("div", { class: "panel-body" });
  body.append(content);
  ov.append(body);
  document.getElementById("modal-root").append(ov);
  buildContent && buildContent(content, dispose);
  return { close: dispose };
}
