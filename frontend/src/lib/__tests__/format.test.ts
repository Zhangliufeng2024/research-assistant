/* format.ts 展示格式化回归。
 *
 * §6.3 背景：后端按 protocol.md 契约返回 epoch 秒（time.time()/st_mtime），
 * formatRelative 却把 number 一律当 epoch 毫秒——diff 变成 ~56 年，
 * 落进「≥7 天」分支，new Date(17.9e8) 渲染为「1月22日」（1970 年）。
 * 这里把秒/毫秒两种输入的期望输出全部锁死。
 */
import { describe, expect, it } from "vitest";
import {
  approvalExpired,
  formatRelative,
  remainingRatio,
  remainingSeconds,
} from "@/lib/format";

const NOW_S = Math.floor(Date.now() / 1000); // 从真实时钟派生，断言只依赖相对差

describe("formatRelative：epoch 秒输入（后端契约，§6.3 回归）", () => {
  it("30 秒前 → 刚刚", () => {
    expect(formatRelative(NOW_S - 30)).toBe("刚刚");
  });

  it("5 分钟前 → n 分钟前", () => {
    expect(formatRelative(NOW_S - 5 * 60)).toBe("5 分钟前");
  });

  it("3 小时前 → n 小时前", () => {
    expect(formatRelative(NOW_S - 3 * 3600)).toBe("3 小时前");
  });

  it("2 天前 → n 天前", () => {
    expect(formatRelative(NOW_S - 2 * 86400)).toBe("2 天前");
  });

  it("30 天前 → 「M月D日」且落在正确的年份（不再渲染成 1970 年）", () => {
    const s = NOW_S - 30 * 86400;
    const d = new Date(s * 1000);
    expect(formatRelative(s)).toBe(`${d.getMonth() + 1}月${d.getDate()}日`);
    // 直接锁死本缺陷的症状面：绝不允许把秒当毫秒解析回 1970 年
    expect(formatRelative(s)).not.toBe("1月21日");
    expect(formatRelative(s)).not.toBe("1月22日");
  });
});

describe("formatRelative：其他合法输入", () => {
  it("epoch 毫秒输入行为不变（5 分钟前）", () => {
    expect(formatRelative(NOW_S * 1000 - 5 * 60_000)).toBe("5 分钟前");
  });

  it("ISO 字符串输入可解析", () => {
    const iso = new Date(NOW_S * 1000 - 3 * 3600_000).toISOString();
    expect(formatRelative(iso)).toBe("3 小时前");
  });

  it("非法字符串 / null / undefined → 空串", () => {
    expect(formatRelative("not-a-date")).toBe("");
    expect(formatRelative(null)).toBe("");
    expect(formatRelative(undefined)).toBe("");
  });
});

/* ---------- 审批倒计时（R13-C） ---------- */

describe("审批倒计时纯函数（R13-C）", () => {
  const deadline = 1_000_000; // ms

  it("remainingSeconds：向上取整、过期截 0", () => {
    expect(remainingSeconds(deadline, deadline - 90_000)).toBe(90);
    expect(remainingSeconds(deadline, deadline - 500)).toBe(1); // 0.5s → 向上取整
    expect(remainingSeconds(deadline, deadline)).toBe(0);
    expect(remainingSeconds(deadline, deadline + 60_000)).toBe(0); // 负值截 0
  });

  it("remainingRatio：夹在 [0,1]，总时长非法时为 0", () => {
    expect(remainingRatio(deadline, deadline - 60_000, 120)).toBeCloseTo(0.5);
    expect(remainingRatio(deadline, deadline - 999_999, 120)).toBe(1); // 上限夹取
    expect(remainingRatio(deadline, deadline + 5_000, 120)).toBe(0);
    expect(remainingRatio(deadline, 0, 0)).toBe(0);
  });

  it("approvalExpired：deadline 精确判定（后端超时自动 deny 的本地镜像）", () => {
    expect(approvalExpired(deadline, deadline - 1)).toBe(false);
    expect(approvalExpired(deadline, deadline)).toBe(true);
    expect(approvalExpired(deadline, deadline + 1)).toBe(true);
  });
});
