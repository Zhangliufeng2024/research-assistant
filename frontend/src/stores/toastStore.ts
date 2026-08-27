/* 全局轻提示（toast）状态（R14-T）。
 *
 * 设计要点：
 * - 定时器由 store 持有（而非渲染组件）：push 即排程，手动 dismiss 或到期
 *   都走同一出口，栈顶挤掉时同步清掉被逐条的定时器；
 * - 栈上限 5 条，超出挤掉最旧——右下角常驻区域不应被错误风暴刷屏；
 * - error 默认 8s（info/success 4s）：报错需要更长的阅读窗口；
 * - toast.success/error/info 是便捷单例：不依赖 React 上下文，可在
 *   store action、非组件模块里直接调用（视图层也可用）。
 */
import { create } from "zustand";
import type { ToastData, ToastKind } from "@/lib/types";

const DEFAULT_DURATION_MS: Record<ToastKind, number> = {
  info: 4_000,
  success: 4_000,
  error: 8_000,
};

/** 同屏上限；超出时挤掉最旧的提示。 */
const MAX_TOASTS = 5;

export interface ToastInput {
  kind?: ToastKind;
  message: string;
  /** 覆盖默认自动消失时长（ms）；传 Infinity 表示不自动消失 */
  duration?: number;
}

interface ToastStore {
  toasts: ToastData[];
  /** 入列一条提示，返回其 id（供手动 dismiss）。 */
  push(input: ToastInput): string;
  /** 手动关闭（幂等：未知 id 无操作）。 */
  dismiss(id: string): void;
}

/** 自增序号 + 时间戳：保证 id 唯一且大致有序（AnimatePresence 的 key 稳定）。 */
let seq = 0;
function nextId(): string {
  return `t-${Date.now().toString(36)}-${++seq}`;
}

/** 存活的自动消失定时器：dismiss / 挤出时必须清掉，防止幽灵回调。 */
const timers = new Map<string, ReturnType<typeof setTimeout>>();

function clearTimer(id: string): void {
  const t = timers.get(id);
  if (t !== undefined) {
    clearTimeout(t);
    timers.delete(id);
  }
}

export const useToastStore = create<ToastStore>()((set, get) => ({
  toasts: [],

  push: (input) => {
    const kind: ToastKind = input.kind ?? "info";
    const duration = input.duration ?? DEFAULT_DURATION_MS[kind];
    const item: ToastData = { id: nextId(), kind, message: input.message, duration };

    // 上限治理：先挤出最旧（清它的定时器），再排程本条的
    let toasts = [...get().toasts, item];
    while (toasts.length > MAX_TOASTS) {
      const evicted = toasts[0]!;
      clearTimer(evicted.id);
      toasts = toasts.slice(1);
    }

    if (duration !== Infinity) {
      timers.set(
        item.id,
        setTimeout(() => get().dismiss(item.id), duration),
      );
    }
    set({ toasts });
    return item.id;
  },

  dismiss: (id) => {
    clearTimer(id);
    const before = get().toasts;
    const toasts = before.filter((t) => t.id !== id);
    if (toasts.length === before.length) return; // 未知/已移除：避免无谓的重渲染
    set({ toasts });
  },
}));

/** 便捷单例：任何模块可调（store action / 事件回调 / 视图皆可），内部走同一 store。 */
export const toast = {
  info: (message: string, duration?: number) =>
    useToastStore.getState().push({ kind: "info", message, duration }),
  success: (message: string, duration?: number) =>
    useToastStore.getState().push({ kind: "success", message, duration }),
  error: (message: string, duration?: number) =>
    useToastStore.getState().push({ kind: "error", message, duration }),
};
