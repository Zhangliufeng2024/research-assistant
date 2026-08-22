import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/* 前端模块接线守护：所有相对 import 必须能解析到真实文件。
 * 防止"视图引用了不存在的组件"这类只在运行时才暴露的断裂。 */
const ROOT = resolve(
  dirname(fileURLToPath(import.meta.url)),
  "../../research_assistant/web/static/js");

function walk(dir, acc = []) {
  for (const f of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, f.name);
    if (f.isDirectory()) walk(p, acc);
    else if (f.name.endsWith(".js")) acc.push(p);
  }
  return acc;
}

test("所有相对导入均可解析（防接线断裂）", () => {
  const broken = [];
  for (const file of walk(ROOT)) {
    const src = readFileSync(file, "utf-8");
    for (const m of src.matchAll(/from\s+["'](\.[^"']+)["']/g)) {
      const target = resolve(dirname(file), m[1]);
      if (!existsSync(target) && !existsSync(target + ".js")) {
        broken.push(`${file} → ${m[1]}`);
      }
    }
  }
  assert.deepEqual(broken, []);
});
