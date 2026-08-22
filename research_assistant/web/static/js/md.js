/* 迷你 markdown 渲染器（零依赖，~70 行）。
 * 支持：# 标题、- 列表、1. 列表、``` 代码块、`行内码`、**粗体**、
 * --- 分隔线、> 引用。输出经 esc() 转义后再加标签，安全。
 */
import { esc } from "./format.js";

function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

export function renderMarkdown(src) {
  if (!src) return "";
  const lines = String(src).replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let inCode = false, inUl = false, inOl = false, codeBuf = [];

  const closeLists = () => {
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }
  };

  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");

    if (/^```/.test(line.trim())) {
      closeLists();
      if (inCode) { out.push(`<pre><code>${esc(codeBuf.join("\n"))}</code></pre>`); codeBuf = []; inCode = false; }
      else inCode = true;
      continue;
    }
    if (inCode) { codeBuf.push(raw); continue; }

    const h = line.match(/^(#{1,3})\s+(.*)/);
    if (h) {
      closeLists();
      const lv = h[1].length;
      out.push(`<h${lv}>${inline(h[2])}</h${lv}>`);
      continue;
    }
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) { closeLists(); out.push("<hr>"); continue; }

    const ul = line.match(/^\s*[-*•]\s+(.*)/);
    if (ul) {
      if (inOl) { out.push("</ol>"); inOl = false; }
      if (!inUl) { out.push("<ul>"); inUl = true; }
      out.push(`<li>${inline(ul[1])}</li>`);
      continue;
    }
    const ol = line.match(/^\s*\d+[.、)]\s+(.*)/);
    if (ol) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (!inOl) { out.push("<ol>"); inOl = true; }
      out.push(`<li>${inline(ol[1])}</li>`);
      continue;
    }
    const bq = line.match(/^>\s?(.*)/);
    if (bq) { closeLists(); out.push(`<blockquote>${inline(bq[1])}</blockquote>`); continue; }

    if (!line.trim()) { closeLists(); continue; }
    closeLists();
    out.push(`<p>${inline(line)}</p>`);
  }
  if (inCode && codeBuf.length) out.push(`<pre><code>${esc(codeBuf.join("\n"))}</code></pre>`);
  closeLists();
  return out.join("\n");
}
