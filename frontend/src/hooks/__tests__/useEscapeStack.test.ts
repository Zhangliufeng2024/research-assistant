/* Esc 关闭层级栈（R14-E）：只有栈顶响应 Escape；注销即让位。
 * node 环境无 window/KeyboardEvent：用 EventTarget + 手工补 key 属性的
 * Event 替身（Node ≥15 自带 EventTarget/Event），直接走真实监听管线。
 * useEscapeStack 本体是 enterEscapeScope 的薄封装（effect 依赖 active），
 * 逻辑断言全部落在后者上。
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { enterEscapeScope } from "@/hooks/useEscapeStack";

function makeKeyEvent(key: string): Event {
  // cancelable 必须显式开：否则 preventDefault 是 no-op，defaultPrevented 恒 false
  const ev = new Event("keydown", { cancelable: true });
  (ev as unknown as { key: string }).key = key;
  return ev;
}

function press(target: EventTarget, key: string): Event {
  const ev = makeKeyEvent(key);
  target.dispatchEvent(ev);
  return ev;
}

const cleanups: Array<() => void> = [];
afterEach(() => {
  while (cleanups.length) cleanups.pop()!();
});

describe("enterEscapeScope（R14-E 层级栈核心）", () => {
  it("active=false 注册为无操作：返回空注销函数、不监听", () => {
    const target = new EventTarget();
    const handler = vi.fn();

    const un = enterEscapeScope(false, handler, target);
    press(target, "Escape");

    expect(handler).not.toHaveBeenCalled();
    expect(() => un()).not.toThrow();
  });

  it("栈顶响应 Esc；叠层后只有最上层响应；上层注销后让位下层", () => {
    const target = new EventTarget();
    const bottom = vi.fn();
    const top = vi.fn();

    const unBottom = enterEscapeScope(true, bottom, target);
    const unTop = enterEscapeScope(true, top, target);
    cleanups.push(unBottom, unTop);

    press(target, "Escape");
    expect(top).toHaveBeenCalledTimes(1);
    expect(bottom).toHaveBeenCalledTimes(0); // 下层不响应

    unTop(); // 关闭最上层的对话框
    press(target, "Escape");
    expect(bottom).toHaveBeenCalledTimes(1); // 让位后下层接管
  });

  it("非 Escape 键被忽略", () => {
    const target = new EventTarget();
    const handler = vi.fn();
    cleanups.push(enterEscapeScope(true, handler, target));

    press(target, "Enter");
    press(target, "F5");

    expect(handler).not.toHaveBeenCalled();
  });

  it("命中时 preventDefault 被调用；非 Escape 键不触碰事件", () => {
    const target = new EventTarget();
    const handler = vi.fn();
    cleanups.push(enterEscapeScope(true, handler, target));

    const hit = makeKeyEvent("Escape");
    const spyHit = vi.spyOn(hit, "preventDefault");
    target.dispatchEvent(hit);
    expect(spyHit).toHaveBeenCalledTimes(1);
    expect(hit.defaultPrevented).toBe(true);

    const miss = makeKeyEvent("Enter");
    const spyMiss = vi.spyOn(miss, "preventDefault");
    target.dispatchEvent(miss);
    expect(handler).toHaveBeenCalledTimes(1); // 只有 Escape 那次
    expect(spyMiss).not.toHaveBeenCalled();
  });

  it("乱序注销安全：先卸下层再卸上层均不抛错且全部失效", () => {
    const target = new EventTarget();
    const h1 = vi.fn();
    const h2 = vi.fn();
    const un1 = enterEscapeScope(true, h1, target);
    const un2 = enterEscapeScope(true, h2, target);

    un1(); // 先卸下层（非常规卸载顺序）
    un2();
    press(target, "Escape");

    expect(h1).not.toHaveBeenCalled();
    expect(h2).not.toHaveBeenCalled();
    expect(() => {
      un1(); // 重复注销
      un1();
    }).not.toThrow();
  });
});
