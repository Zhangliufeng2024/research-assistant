import { describe, expect, it } from "vitest";
import pkg from "../../../package.json";
import { APP_VERSION } from "@/lib/version";

/** 侧栏页脚版本号必须与 package.json 同源——R12 前硬编码在 App.tsx，
 *  v3.3.0 起漂移三轮没人发现（R12 E2E 截图暴露）。 */
describe("APP_VERSION", () => {
  it("与 package.json 版本一致", () => {
    expect(APP_VERSION).toBe(pkg.version);
  });
});
