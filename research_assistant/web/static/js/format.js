/* 格式化与 DOM 工具（纯函数，node:test 覆盖） */

export function esc(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export function basename(p) {
  if (!p) return "";
  return String(p).split("/").pop().split("\\").pop();
}

export function fmtTime(ts) {
  const d = ts ? new Date(ts) : new Date();
  return d.toLocaleTimeString("zh-CN", { hour12: false });
}

export function fmtClock(sec) {
  if (sec == null || Number.isNaN(+sec)) return "—";
  const s = Math.max(0, Math.floor(+sec));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  const mm = String(m).padStart(2, "0"), s2 = String(ss).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${s2}` : `${m}:${s2}`;
}

export function fmtCost(usd) {
  if (usd == null) return "—";
  return "$" + (+usd).toFixed(2);
}

export function fmtNum(n) {
  if (n == null) return "—";
  return (+n).toLocaleString("zh-CN");
}

export function fmtDate(isoOrTs) {
  if (!isoOrTs) return "";
  const d = typeof isoOrTs === "number" ? new Date(isoOrTs * 1000) : new Date(isoOrTs);
  if (Number.isNaN(d.getTime())) return String(isoOrTs);
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* el(tag, props, ...children) —— 轻量元素工厂 */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "html") node.innerHTML = v;
    else if (v === true) node.setAttribute(k, "");
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}
