/* format.js 纯函数测试 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { esc, basename, fmtClock, fmtCost } from "../../research_assistant/web/static/js/format.js";

test("esc 转义 HTML 特殊字符", () => {
  assert.equal(esc(`<img src=x onerror="a&b'">`),
    "&lt;img src=x onerror=&quot;a&amp;b&#39;&quot;&gt;");
  assert.equal(esc(null), "");
  assert.equal(esc(undefined), "");
});

test("basename 处理两种分隔符", () => {
  assert.equal(basename("figures/fig_01.png"), "fig_01.png");
  assert.equal(basename("C:\\out\\draft.docx"), "draft.docx");
  assert.equal(basename(""), "");
});

test("fmtClock 时分秒", () => {
  assert.equal(fmtClock(65), "1:05");
  assert.equal(fmtClock(3661), "1:01:01");
  assert.equal(fmtClock(null), "—");
});

test("fmtCost 美元两位小数", () => {
  assert.equal(fmtCost(1.5), "$1.50");
  assert.equal(fmtCost(0), "$0.00");
});
