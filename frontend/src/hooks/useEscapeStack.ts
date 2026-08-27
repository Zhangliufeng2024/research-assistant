/* Esc 关闭层级栈（R14-E）：模态 / 抽屉 / 向导叠加时只有最上层响应 Esc。
 *
 * 模块级栈数组 + 单一 keydown 监听 per 注册层：active 时压栈并挂
 * window keydown，注销时按条目移除（不假设 LIFO 卸载顺序）。按键命中时
 * 仅当本条目位于栈顶才触发回调——下层（先打开的对话框）不会被误关。
 *
 * 核心逻辑独立为 enterEscapeScope（监听目标可注入），便于无 DOM 测试；
 * useEscapeStack 是其 React 封装（handler 经 ref 透传最新闭包，
 * effect 只依赖 active，避免每次渲染重挂监听）。
 */
import { useEffect, useRef } from "react";

export type EscapeHandler = () => void;

/** 最小监听目标接口：window 或测试用的 EventTarget 替身皆可。 */
interface EscapeTarget {
  addEventListener(type: string, listener: (ev: Event) => void): void;
  removeEventListener(type: string, listener: (ev: Event) => void): void;
}

interface StackEntry {
  handler: EscapeHandler;
}

const stack: StackEntry[] = [];

/**
 * 压入一个 Esc 响应层。active=false 时为无操作（返回空注销函数）。
 * 返回注销函数：移除条目与监听；重复调用安全。
 */
export function enterEscapeScope(
  active: boolean,
  handler: EscapeHandler,
  target: EscapeTarget = window,
): () => void {
  if (!active) return () => {};
  const entry: StackEntry = { handler };
  stack.push(entry);
  const onKey = (ev: Event): void => {
    // 测试替身以普通 Event 冒充 KeyboardEvent（仅补 key 字段），故此处收窄而非改签名
    if ((ev as KeyboardEvent).key !== "Escape") return;
    if (stack[stack.length - 1] !== entry) return; // 只有栈顶响应
    ev.preventDefault?.();
    entry.handler();
  };
  target.addEventListener("keydown", onKey);
  return () => {
    const i = stack.indexOf(entry);
    if (i >= 0) stack.splice(i, 1);
    target.removeEventListener("keydown", onKey);
  };
}

/** React hook 形态：active 切换即注册/注销，onEscape 取最新闭包。 */
export function useEscapeStack(active: boolean, onEscape: EscapeHandler): void {
  const cbRef = useRef(onEscape);
  cbRef.current = onEscape; // 每次渲染同步，effect 不依赖回调身份
  useEffect(
    () => enterEscapeScope(active, () => cbRef.current()),
    [active],
  );
}
