import { describe, expect, it } from "vitest";
import { shouldShowWaitHint, WAIT_HINT_THRESHOLD_S } from "@/lib/waitHint";

describe("shouldShowWaitHint", () => {
  it("running 且静默秒数达阈值时提示", () => {
    expect(shouldShowWaitHint("running", WAIT_HINT_THRESHOLD_S)).toBe(true);
    expect(shouldShowWaitHint("running", WAIT_HINT_THRESHOLD_S + 300)).toBe(true);
  });

  it("未达阈值或非 running 一律不提示", () => {
    expect(shouldShowWaitHint("running", WAIT_HINT_THRESHOLD_S - 1)).toBe(false);
    expect(shouldShowWaitHint("idle", 9999)).toBe(false);
    expect(shouldShowWaitHint("done", 9999)).toBe(false);
    expect(shouldShowWaitHint("error", 9999)).toBe(false);
  });
});
