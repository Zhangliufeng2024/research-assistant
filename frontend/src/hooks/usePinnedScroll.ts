/* 智能滚动（R14-N）：贴底跟随 + 解除跟随期间的「回到底部」未读计数。
 *
 * 分层（与 useEscapeStack 同一手法的推广）：
 * - createPinnedScrollCore：纯状态机。滚动面以最小接口 ScrollSurface 注入
 *   （DOM 元素天然满足；node 测试用普通对象替身），零 DOM 依赖可直测；
 * - usePinnedScroll：React 封装。绑定容器 ref、挂 passive 滚动监听并做
 *   rAF 节流（onscroll 里只排一帧，量测与状态推进都在 rAF 里做）、
 *   订阅状态机把 pinned / missedCount 镜像为渲染态。
 *
 * 跟随判定语义：
 * - 「距底 < 80px」即视为贴底 → 进入/保持跟随，未读清零；
 *   用户手动滚回底部由此自然恢复跟随；
 * - 只有「向上滚」（scrollTop 变小）才解除跟随——这条方向守卫是关键：
 *   程序化平滑滚动（点 pill 回底）途中 scrollTop 单调增大，不会被误判成
 *   上翻而中途解除；流式跟随时的高度抖动同理不误伤；
 * - 首个滚动事件方向未知时按「远离底部」处理——此刻若距底很远，说明
 *   状态机与现实脱节（如初始化竞态），先解除跟随保正确性；
 * - 非跟随期间内容到达：按消息条数累加 missedCount（纯文本增长
 *   grewMessages=0 只触发不计数）；跟随期间内容到达：立即瞬时跳底
 *   （不用 smooth——平滑动画会被下一帧合帧打断，直接跳更稳）。
 *
 * 会话切换由调用方传 sessionKey，hook 内检测变化即 reset：恢复跟随、
 * 清零未读、跳底（历史恢复后应从最新一条看起）。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

/** 贴底判定阈值（px）：视口底边距内容底边小于该值视为「在底部附近」。 */
export const NEAR_BOTTOM_PX = 80;

/** 最小滚动面接口：DOM 元素天然满足；测试用普通对象替身即可。 */
export interface ScrollSurface {
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
  /** DOM 元素有；测试替身可不带（此时退化为直接写 scrollTop） */
  scrollTo?(options: { top: number; behavior?: ScrollBehavior }): void;
}

type Listener = () => void;

export interface PinnedScrollCore {
  readonly pinned: boolean;
  readonly missedCount: number;
  /** 滚动事件后调用（真实滚动与程序化滚动都会触发）。 */
  handleScroll(el: ScrollSurface): void;
  /** 内容更新后调用；grewMessages 为新到达的消息条数（纯文本增长传 0）。 */
  handleContentGrew(el: ScrollSurface, grewMessages: number): void;
  /** 回到底部并恢复跟随、清零未读。behavior 默认 smooth（pill 场景）。 */
  pinToBottom(el: ScrollSurface, behavior?: ScrollBehavior): void;
  /** 重置为跟随态并瞬时跳底（会话切换 / 历史恢复）。 */
  reset(el: ScrollSurface): void;
  /** 状态变化订阅（pinned / missedCount 变化才通知）；返回注销函数。 */
  subscribe(listener: Listener): () => void;
}

function distanceFromBottom(el: ScrollSurface): number {
  return el.scrollHeight - el.scrollTop - el.clientHeight;
}

/** 跳到底部：优先 scrollTo（支持 behavior），替身无该方法则直写 scrollTop。 */
function jumpToBottom(el: ScrollSurface, behavior?: ScrollBehavior): void {
  const top = el.scrollHeight - el.clientHeight;
  if (typeof el.scrollTo === "function") {
    el.scrollTo({ top, behavior });
  } else {
    el.scrollTop = top;
  }
}

export function createPinnedScrollCore(opts?: {
  nearBottomPx?: number;
}): PinnedScrollCore {
  const nearBottomPx = opts?.nearBottomPx ?? NEAR_BOTTOM_PX;
  let pinned = true;
  let missedCount = 0;
  /** 上一次已知 scrollTop（NaN=尚无基准，方向未知）。 */
  let prevTop = Number.NaN;
  const listeners = new Set<Listener>();

  const notify = () => listeners.forEach((l) => l());
  const setPinned = (v: boolean) => {
    if (pinned !== v) {
      pinned = v;
      notify();
    }
  };
  const setMissed = (v: number) => {
    if (missedCount !== v) {
      missedCount = v;
      notify();
    }
  };

  return {
    get pinned() {
      return pinned;
    },
    get missedCount() {
      return missedCount;
    },

    handleScroll: (el) => {
      // 方向守卫：只有向上滚才允许解除跟随。首事件无基准时按上翻处理，
      // 避免「状态机自认贴底、实际远在顶部」的死锁。
      const goingUp = !Number.isFinite(prevTop) || el.scrollTop < prevTop;
      prevTop = el.scrollTop;
      if (distanceFromBottom(el) <= nearBottomPx) {
        // 贴底（含用户手动滚到底）：恢复跟随并清空未读
        setPinned(true);
        setMissed(0);
      } else if (pinned && goingUp) {
        setPinned(false);
      }
    },

    handleContentGrew: (el, grewMessages) => {
      if (pinned) {
        prevTop = el.scrollTop;
        jumpToBottom(el, "auto");
      } else if (grewMessages > 0) {
        setMissed(missedCount + grewMessages);
      }
    },

    pinToBottom: (el, behavior = "smooth") => {
      setPinned(true);
      setMissed(0);
      // 方向基准取「点击时刻」的位置而非滚动终点：平滑回底动画从当前位置
      // 向下逼近底部，途中 scrollTop 单调增大——以旧位置为基准时全程
      // goingUp=false 不误解除；若用户中途真的向上拨（scrollTop 变小），
      // 立即如实解除。若基准写成终点（> 当前位置），每一帧都会被误判上翻。
      prevTop = el.scrollTop;
      jumpToBottom(el, behavior);
    },

    reset: (el) => {
      setPinned(true);
      setMissed(0);
      prevTop = el.scrollTop;
      jumpToBottom(el, "auto");
    },

    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

export interface PinnedScrollOptions {
  /** 内容信号：引用每次内容更新都变（如 chat.items 数组，store 合帧后逐帧换新）。 */
  contentToken: unknown;
  /** 消息条数（建议只数 user/text，不含工具卡）；增量用于未读计数。 */
  messageCount: number;
  /** 会话标识：变化即重置为跟随态（切会话/新建会话）。 */
  sessionKey: string | null;
}

export interface PinnedScrollBinding {
  containerRef: RefObject<HTMLDivElement>;
  /** 是否处于贴底跟随态（false 时视图显示「回到底部」pill）。 */
  pinned: boolean;
  /** 解除跟随期间新到的消息条数。 */
  missedCount: number;
  /** 平滑滚回底部、恢复跟随、清零未读。 */
  scrollToBottom(): void;
}

export function usePinnedScroll(opts: PinnedScrollOptions): PinnedScrollBinding {
  const coreRef = useRef<PinnedScrollCore | null>(null);
  if (coreRef.current === null) coreRef.current = createPinnedScrollCore();
  const core = coreRef.current;

  const containerRef = useRef<HTMLDivElement>(null);
  const [snapshot, setSnapshot] = useState({ pinned: true, missedCount: 0 });

  // 状态机 → 渲染态镜像（仅在 pinned/missed 实际变化时收到通知）
  useEffect(
    () =>
      core.subscribe(() =>
        setSnapshot({ pinned: core.pinned, missedCount: core.missedCount }),
      ),
    [core],
  );

  // passive 滚动监听 + rAF 节流：onscroll 只排帧，量测与推进都在 rAF 内
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    let raf = 0;
    let scheduled = false;
    const onScroll = () => {
      if (scheduled) return;
      scheduled = true;
      raf = requestAnimationFrame(() => {
        scheduled = false;
        raf = 0;
        core.handleScroll(el);
      });
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
      if (raf !== 0) cancelAnimationFrame(raf);
    };
  }, [core]);

  // 内容更新：贴底→跟随跳底；未贴底→按消息增量累计未读
  const prevMessageCount = useRef(opts.messageCount);
  useEffect(() => {
    const grew = Math.max(0, opts.messageCount - prevMessageCount.current);
    prevMessageCount.current = opts.messageCount;
    const el = containerRef.current;
    if (!el) return;
    core.handleContentGrew(el, grew);
  }, [core, opts.contentToken, opts.messageCount]);

  // 会话切换：恢复跟随态（历史恢复后从最新一条看起）
  const prevSessionKey = useRef(opts.sessionKey);
  useEffect(() => {
    if (prevSessionKey.current === opts.sessionKey) return;
    prevSessionKey.current = opts.sessionKey;
    const el = containerRef.current;
    if (el) core.reset(el);
  }, [core, opts.sessionKey]);

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current;
    if (el) core.pinToBottom(el, "smooth");
  }, [core]);

  return {
    containerRef,
    pinned: snapshot.pinned,
    missedCount: snapshot.missedCount,
    scrollToBottom,
  };
}
