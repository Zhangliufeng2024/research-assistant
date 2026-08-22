/* md.js 迷你 markdown 渲染器测试 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderMarkdown } from "../../research_assistant/web/static/js/md.js";

test("标题层级", () => {
  const h = renderMarkdown("# A\n## B\n### C");
  assert.match(h, /<h1>A<\/h1>/);
  assert.match(h, /<h2>B<\/h2>/);
  assert.match(h, /<h3>C<\/h3>/);
});

test("列表与有序列表", () => {
  const h = renderMarkdown("- 甲\n- 乙\n\n1. 一\n2. 二");
  assert.match(h, /<ul>\s*<li>甲<\/li>\s*<li>乙<\/li>\s*<\/ul>/);
  assert.match(h, /<ol>\s*<li>一<\/li>\s*<li>二<\/li>\s*<\/ol>/);
});

test("代码块与行内码、粗体", () => {
  const h = renderMarkdown("```py\nx=1\n```\n`code` **bold**");
  assert.match(h, /<pre><code>x=1<\/code><\/pre>/);
  assert.match(h, /<code>code<\/code>/);
  assert.match(h, /<strong>bold<\/strong>/);
});

test("XSS 输入被转义", () => {
  const h = renderMarkdown('<script>alert(1)</script> & <img onerror=x>');
  assert.ok(!h.includes("<script>"));
  assert.ok(!h.includes("<img"));
  assert.match(h, /&lt;script&gt;/);
});

test("空输入返回空串", () => {
  assert.equal(renderMarkdown(""), "");
  assert.equal(renderMarkdown(null), "");
});
