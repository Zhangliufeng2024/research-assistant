/* usePinnedScroll 核心（R14-N）：node 环境无 DOM/布局——滚动面用普通对象
 * 替身（scrollTop/scrollHeight/clientHeight 可写字段，可选 scrollTo mock），
 * 直接驱动 createPinnedScrollCore 状态机。usePinnedScroll 的 React 封装
 * （监听绑定/rAF 节流）不在本文件范围，由 tsc + 结构审查覆盖。
 */
import { describe, expect, it, vi } from "vitest";
import {
  createPinnedScrollCore,
  NEAR_BOTTOM_PX,
  type ScrollSurface,
} from "@/hooks/usePinnedScroll";

/** 构造滚动面替身：top=当前滚动位置，contentH=内容总高，viewH=视口高。 */
function surface(top: number, contentH: number, viewH: number): ScrollSurface {
  return { scrollTop: top, scrollHeight: contentH, clientHeight: viewH };
}

describe("createPinnedScrollCore（R14-N 智能滚动核心）", () => {
  it("初始即跟随态；NEAR_BOTTOM_PX 阈值为 80", () => {
    const core = createPinnedScrollCore();
    expect(core.pinned).toBe(true);
    expect(core.missedCount).toBe(0);
    expect(NEAR_BOTTOM_PX).toBe(80);
  });

  it("贴底跟随：内容增长时瞬时跳底保持贴底", () => {
    const core = createPinnedScrollCore();
    const el = surface(150, 250, 100); // 距底 0
    core.handleScroll(el);
    expect(core.pinned).toBe(true);

    el.scrollHeight = 400; // 流式内容长高
    core.handleContentGrew(el, 0);
    expect(el.scrollTop).toBe(300); // 400-100 跳到底
    expect(core.pinned).toBe(true);
    expect(core.missedCount).toBe(0);
  });

  it("上翻超过阈值解除跟随；此后内容增长不拉底、按条累计未读", () => {
    const core = createPinnedScrollCore();
    const el = surface(300, 400, 100);
    core.handleScroll(el);
    expect(core.pinned).toBe(true);

    el.scrollTop = 40; // 用户大幅上翻（距底 260 > 80）
    core.handleScroll(el);
    expect(core.pinned).toBe(false);

    el.scrollHeight = 520; // 新一轮问答到达
    core.handleContentGrew(el, 1);
    expect(el.scrollTop).toBe(40); // 不强制拉底
    expect(core.missedCount).toBe(1);

    core.handleContentGrew(el, 2);
    expect(core.missedCount).toBe(3);
  });

  it("纯文本增长（grewMessages=0）不累计未读——流式合帧不虚报条数", () => {
    const core = createPinnedScrollCore();
    const el = surface(40, 400, 100);
    core.handleScroll(el); // 解除跟随
    expect(core.pinned).toBe(false);

    core.handleContentGrew(el, 0);
    core.handleContentGrew(el, 0);
    expect(core.missedCount).toBe(0);
  });

  it("用户手动滚回底部：恢复跟随且未读清零", () => {
    const core = createPinnedScrollCore();
    const el = surface(40, 400, 100);
    core.handleScroll(el);
    core.handleContentGrew(el, 2);
    expect(core.missedCount).toBe(2);

    el.scrollTop = 295; // 距底 5 < 80
    core.handleScroll(el);
    expect(core.pinned).toBe(true);
    expect(core.missedCount).toBe(0);
  });

  it("方向守卫：pill 平滑回底途中 scrollTop 单调增大，距底再远也不解除", () => {
    const core = createPinnedScrollCore();
    const el = surface(40, 10000, 100); // 用户在顶部，未跟随
    core.handleScroll(el);
    expect(core.pinned).toBe(false);

    core.pinToBottom(el); // 点 pill：动画将从 40 平滑逼近 9900
    expect(core.pinned).toBe(true);

    // 动画中间帧：距底很远，但方向向下 → 不解除
    el.scrollTop = 500;
    core.handleScroll(el);
    expect(core.pinned).toBe(true);
    el.scrollTop = 3000;
    core.handleScroll(el);
    expect(core.pinned).toBe(true);

    el.scrollTop = 9895;
    core.handleScroll(el);
    expect(core.pinned).toBe(true);
  });

  it("方向守卫：平滑回底途中用户真的向上拨 → 立即如实解除", () => {
    const core = createPinnedScrollCore();
    const el = surface(40, 10000, 100);
    core.handleScroll(el);
    core.pinToBottom(el);

    el.scrollTop = 2000; // 动画推进中
    core.handleScroll(el);
    expect(core.pinned).toBe(true);

    el.scrollTop = 1500; // 用户向上拨（比上一帧小）→ 解除
    core.handleScroll(el);
    expect(core.pinned).toBe(false);
  });

  it("pinToBottom：恢复跟随、清零未读、经 scrollTo 平滑滚底（有该方法时）", () => {
    const core = createPinnedScrollCore();
    const scrollTo = vi.fn();
    const el = surface(40, 900, 100) as ScrollSurface & {
      scrollTo: typeof scrollTo;
    };
    el.scrollTo = scrollTo;
    core.handleScroll(el);
    core.handleContentGrew(el, 4);
    expect(core.pinned).toBe(false);
    expect(core.missedCount).toBe(4);

    core.pinToBottom(el, "smooth");
    expect(core.pinned).toBe(true);
    expect(core.missedCount).toBe(0);
    expect(scrollTo).toHaveBeenCalledWith({ top: 800, behavior: "smooth" });
  });

  it("pinToBottom 默认 behavior 为 smooth；无 scrollTo 的替身退化为直写 scrollTop", () => {
    const core = createPinnedScrollCore();
    const el = surface(40, 600, 100);
    core.handleScroll(el);
    core.pinToBottom(el);
    expect(el.scrollTop).toBe(500);
    expect(core.pinned).toBe(true);
  });

  it("reset：任意状态下恢复跟随、清零未读、瞬时跳底（会话切换）", () => {
    const core = createPinnedScrollCore();
    const el = surface(40, 700, 100);
    core.handleScroll(el);
    core.handleContentGrew(el, 5);
    expect(core.pinned).toBe(false);
    expect(core.missedCount).toBe(5);

    el.scrollHeight = 1200; // 切会话后历史已载入
    core.reset(el);
    expect(core.pinned).toBe(true);
    expect(core.missedCount).toBe(0);
    expect(el.scrollTop).toBe(1100);
  });

  it("首事件无方向基准且远在底部 → 解除跟随（不自锁在错误跟随态）", () => {
    const core = createPinnedScrollCore();
    const el = surface(10, 2000, 100); // 距底 1890
    core.handleScroll(el);
    expect(core.pinned).toBe(false);
  });

  it("subscribe：状态变化才通知；注销后不再通知", () => {
    const core = createPinnedScrollCore();
    const listener = vi.fn();
    const un = core.subscribe(listener);

    const el = surface(150, 250, 100);
    core.handleScroll(el); // 本就贴底、状态无变化 → 不通知
    expect(listener).not.toHaveBeenCalled();

    el.scrollTop = 20;
    core.handleScroll(el); // 解除跟随 → 通知一次
    expect(listener).toHaveBeenCalledTimes(1);

    un();
    el.scrollTop = 145;
    core.handleScroll(el); // 恢复跟随但已注销
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("自定义阈值 nearBottomPx 生效", () => {
    const core = createPinnedScrollCore({ nearBottomPx: 200 });
    const el = surface(100, 500, 100); // 距底 300 > 200 → 解除
    el.scrollTop = 100;
    core.handleScroll(el);
    expect(core.pinned).toBe(false);

    el.scrollTop = 250; // 距底 150 < 200 → 恢复
    core.handleScroll(el);
    expect(core.pinned).toBe(true);
  });
});
