/* useFirstRunWizard 存储层（R15）：读/写引导标记与降级路径。
 * node 环境无 localStorage：用内存 Map 替身与抛错替身直接驱动纯函数；
 * hook 本体是 useState 薄封装（与 useEscapeStack 同一测试策略）。
 */
import { describe, expect, it } from "vitest";
import {
  completeOnboarding,
  ONBOARDING_KEY,
  readOnboarded,
  shouldShowWizard,
  type StorageLike,
} from "@/hooks/useFirstRunWizard";

class MemStorage implements StorageLike {
  private map = new Map<string, string>();
  getItem(key: string): string | null {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string): void {
    this.map.set(key, String(value));
  }
}

class BrokenStorage implements StorageLike {
  getItem(): string | null {
    throw new Error("storage blocked");
  }
  setItem(): void {
    throw new Error("storage blocked");
  }
}

describe("readOnboarded / completeOnboarding（R15 首次运行向导）", () => {
  it("键名固定为 ra.onboarded.v1", () => {
    expect(ONBOARDING_KEY).toBe("ra.onboarded.v1");
  });

  it("全新存储：未引导（false）；写入后读取为已引导（true）", () => {
    const store = new MemStorage();
    expect(readOnboarded(store)).toBe(false);

    completeOnboarding(store);
    expect(store.getItem(ONBOARDING_KEY)).toBe("1");
    expect(readOnboarded(store)).toBe(true);
  });

  it("其它键存在不影响判定；值非 '1' 视为未引导", () => {
    const store = new MemStorage();
    store.setItem("ra.recentProjects", "[]");
    expect(readOnboarded(store)).toBe(false);

    store.setItem(ONBOARDING_KEY, "yes");
    expect(readOnboarded(store)).toBe(false);
  });

  it("无存储能力（null）：视为已引导，写入为无操作", () => {
    expect(readOnboarded(null)).toBe(true);
    expect(() => completeOnboarding(null)).not.toThrow();
  });

  it("存储抛错（隐私模式等）：读取降级为已引导，写入静默不抛", () => {
    const store = new BrokenStorage();
    expect(readOnboarded(store)).toBe(true);
    expect(() => completeOnboarding(store)).not.toThrow();
  });
});

describe("shouldShowWizard（极性回归锁）", () => {
  // E2E 冒烟抓出的真实回归：hook 曾把 readOnboarded 直接当 show 用——
  // 向导对新用户永不出现、对已引导用户永远关不掉。极性必须是取反。
  it("全新用户：向导显示", () => {
    expect(shouldShowWizard(new MemStorage())).toBe(true);
  });

  it("已完成引导：向导不再显示；完成后与显示互斥", () => {
    const store = new MemStorage();
    expect(shouldShowWizard(store)).toBe(true);
    completeOnboarding(store);
    expect(shouldShowWizard(store)).toBe(false);
  });

  it("无存储 / 读失败：视为已引导，不打扰", () => {
    expect(shouldShowWizard(null)).toBe(false);
    expect(shouldShowWizard(new BrokenStorage())).toBe(false);
  });
});
