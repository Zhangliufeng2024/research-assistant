/* R13-F：任务页行级门控纯函数。
 *
 * 背景：task 通道单槽——观察 B 会掐断 A 的观察连接；运行中发起新任务
 * 同样顶掉在跑的连接。此前「继续观察」只有样式弱化没有 disabled，
 * 点击仍然生效。这里锁死 gateReason 的判定矩阵：视图层只做取值接线。 */
import { describe, expect, it } from "vitest";
import { gateReason } from "@/lib/taskGate";

const idle = {
  boundTaskId: null,
  localRunning: false,
  channelBusy: false,
};

describe("gateReason（R13-F）", () => {
  it("空闲且通道空闲：放行（null）", () => {
    expect(gateReason(idle)).toBeNull();
    expect(gateReason(idle, "t-1")).toBeNull();
  });

  it("本地 running：一切行动禁用，本行/他行原因不同", () => {
    const ctx = { ...idle, localRunning: true, boundTaskId: "t-run" };
    expect(gateReason(ctx, "t-run")).toBe("该任务正在本地运行中");
    expect(gateReason(ctx, "t-other")).toBe("已有任务在运行中——请等待完成或先停止");
    expect(gateReason(ctx)).toBe("已有任务在运行中——请等待完成或先停止");
  });

  it("通道被观察占用：被观察行提示已在观察，其余行提示先断开", () => {
    const ctx = { ...idle, channelBusy: true, boundTaskId: "t-a" };
    expect(gateReason(ctx, "t-a")).toBe("已连接该任务的观察流");
    expect(gateReason(ctx, "t-b")).toBe("正在观察另一任务——停止观察后再试");
  });

  it("连接建立中但尚未绑定任务：给出等待提示", () => {
    const ctx = { ...idle, channelBusy: true };
    expect(gateReason(ctx, "t-b")).toBe("观察连接建立中，请稍候");
  });
});
