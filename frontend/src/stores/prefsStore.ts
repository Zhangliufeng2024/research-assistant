/* R17 思考链显示分级：三档 verbosity 偏好（简洁/标准/调试）。
 *
 * 持久化双写：localStorage 立即生效（首帧无闪烁）+ /api/settings/ui.verbosity
 * 跨端同步（platform.sqlite3，换浏览器不丢——与归档迁移同一原则）。
 * 读取顺序：本地缓存 → 后台拉服务端覆盖（服务端为权威）。
 */
import { create } from "zustand";
import { api } from "@/lib/api";

/** L0/L1/L2 三档：
 * - minimal（简洁，默认）：L0 展开、L1 折叠一行、L2 隐藏；
 * - standard（标准）：L0 展开、L1 折叠但运行中自动展开当前项、L2 隐藏；
 * - debug（调试）：全部展开，L2（堆栈/全参数）可见。 */
export type Verbosity = "minimal" | "standard" | "debug";

const LOCAL_KEY = "ra.ui.verbosity.v1";
const SERVER_KEY = "ui.verbosity";
const VALID: readonly Verbosity[] = ["minimal", "standard", "debug"];

function readLocal(): Verbosity {
  try {
    const raw = globalThis.localStorage?.getItem(LOCAL_KEY);
    return VALID.includes(raw as Verbosity) ? (raw as Verbosity) : "minimal";
  } catch {
    return "minimal";
  }
}

interface PrefsState {
  verbosity: Verbosity;
  /** 服务端同步已完成（避免首帧被服务端旧值回闪）。 */
  hydrated: boolean;
  setVerbosity(v: Verbosity): void;
  hydrate(): Promise<void>;
}

export const usePrefsStore = create<PrefsState>()((set, get) => ({
  verbosity: readLocal(),
  hydrated: false,

  setVerbosity: (v) => {
    set({ verbosity: v });
    try {
      globalThis.localStorage?.setItem(LOCAL_KEY, v);
    } catch {
      /* 隐私模式：仅内存态 */
    }
    api.put(`/api/settings/${SERVER_KEY}`, { value: v }).catch(() => {});
  },

  hydrate: async () => {
    if (get().hydrated) return;
    try {
      const res = await api.get<{ value: string | null }>(
        `/api/settings/${SERVER_KEY}`,
      );
      if (res.value && VALID.includes(res.value as Verbosity)) {
        const v = res.value as Verbosity;
        set({ verbosity: v, hydrated: true });
        try {
          globalThis.localStorage?.setItem(LOCAL_KEY, v);
        } catch {
          /* 忽略 */
        }
        return;
      }
    } catch {
      /* 离线/旧服务端：保持本地档 */
    }
    set({ hydrated: true });
  },
}));

/** 便捷选择器：当前是否调试档（L2 内容可见）。 */
export const selectDebug = (s: PrefsState) => s.verbosity === "debug";
