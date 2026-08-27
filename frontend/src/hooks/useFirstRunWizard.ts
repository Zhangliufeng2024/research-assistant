/* 首次运行向导开关（R15）：localStorage 键 ra.onboarded.v1。
 *
 * 读写全部包 try/catch：隐私模式 / 存储被禁用时静默降级——读失败视为
 * 「已引导」（不反复打扰），写失败仅跳过持久化（本次会话内仍然关闭）。
 * 存储访问经参数注入，node 环境单测可直接喂内存替身或抛错替身；
 * useFirstRunWizard 是其 React 封装。
 */
import { useCallback, useState } from "react";

export const ONBOARDING_KEY = "ra.onboarded.v1";

/** localStorage 的最小结构面（便于测试替身）。 */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

/** 读取引导完成标记；未引导返回 false。无存储 / 读失败 → 视为已引导。 */
export function readOnboarded(store: StorageLike | null): boolean {
  if (!store) return true;
  try {
    return store.getItem(ONBOARDING_KEY) === "1";
  } catch {
    return true;
  }
}

/** 写入引导完成标记；无存储 / 写失败（配额、隐私模式）时静默忽略。 */
export function completeOnboarding(store: StorageLike | null): void {
  if (!store) return;
  try {
    store.setItem(ONBOARDING_KEY, "1");
  } catch {
    // 忽略：不影响本次会话关闭向导
  }
}

/** globalThis.localStorage 访问兜底：个别嵌入环境可能直接抛错。 */
function safeLocalStorage(): StorageLike | null {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

export interface FirstRunWizardState {
  show: boolean;
  /** 关闭向导并持久化「已引导」。 */
  dismiss: () => void;
}

/**
 * 向导是否应显示：readOnboarded 极性取反（「已引导=true」→「未引导才显示」）。
 * 独立成纯函数让极性可在 node 环境单测——E2E 冒烟曾抓出内联时写反的回归。
 */
export function shouldShowWizard(store: StorageLike | null): boolean {
  return !readOnboarded(store);
}

export function useFirstRunWizard(): FirstRunWizardState {
  // 惰性初始化同步读存储：已引导用户首帧即不渲染遮罩，无闪烁
  const [show, setShow] = useState(() => shouldShowWizard(safeLocalStorage()));
  const dismiss = useCallback(() => {
    completeOnboarding(safeLocalStorage());
    setShow(false);
  }, []);
  return { show, dismiss };
}
