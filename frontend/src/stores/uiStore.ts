/* 壳层 UI 状态（阶段 4）：命令面板 / 会话抽屉 / 检查器抽屉 / 导航栏折叠。
 *
 * 全局快捷键（useHotkeys）与组件（NavRail / SessionDrawer / CommandPalette /
 * ChatView）共享同一份状态，避免 props 层层穿透。检查器展开态复用
 * lib/artifacts 的 localStorage 键（R12 P3 的折叠记忆语义不变，仅迁入 store）。
 */
import { create } from "zustand";
import { loadDockCollapsed, saveDockCollapsed } from "@/lib/artifacts";

interface UiStore {
  /** 命令面板（Ctrl/Cmd+K）。 */
  paletteOpen: boolean;
  /** 导航栏二级抽屉：会话列表。 */
  sessionDrawerOpen: boolean;
  /** 窄屏（<1280px）检查器抽屉。 */
  inspectorDrawerOpen: boolean;
  /** 导航栏折叠（Ctrl/Cmd+B）。 */
  railCollapsed: boolean;
  /** 宽屏（≥1280px）检查器内联 dock 展开态（持久化，R12 P3 语义）。 */
  inspectorOpen: boolean;
  /** 视口是否 ≥1280px（App 用 useMediaQuery 同步，供全局命令分流）。 */
  wideLayout: boolean;
  /** 自增信号：请求把焦点拉到会话输入框（Ctrl+J / 草稿行点击）。 */
  composerFocusTick: number;

  setPaletteOpen(v: boolean): void;
  setSessionDrawerOpen(v: boolean): void;
  setInspectorDrawerOpen(v: boolean): void;
  toggleRailCollapsed(): void;
  toggleInspector(): void;
  setWideLayout(v: boolean): void;
  bumpComposerFocus(): void;
  /** Esc 关闭最上层浮层；无浮层打开时返回 false（无操作）。 */
  closeTopOverlay(): boolean;
}

export const useUiStore = create<UiStore>()((set, get) => ({
  paletteOpen: false,
  sessionDrawerOpen: false,
  inspectorDrawerOpen: false,
  railCollapsed: false,
  inspectorOpen: !loadDockCollapsed(), // loadDockCollapsed 语义是「是否折叠」
  wideLayout: true,
  composerFocusTick: 0,

  setPaletteOpen: (v) => set({ paletteOpen: v }),
  setSessionDrawerOpen: (v) => set({ sessionDrawerOpen: v }),
  setInspectorDrawerOpen: (v) => set({ inspectorDrawerOpen: v }),
  toggleRailCollapsed: () => set((s) => ({ railCollapsed: !s.railCollapsed })),
  toggleInspector: () =>
    set((s) => {
      const next = !s.inspectorOpen;
      saveDockCollapsed(!next); // localStorage 键语义是「折叠」
      return { inspectorOpen: next };
    }),
  setWideLayout: (v) => set({ wideLayout: v }),
  bumpComposerFocus: () => set((s) => ({ composerFocusTick: s.composerFocusTick + 1 })),
  closeTopOverlay: () => {
    const s = get();
    if (s.paletteOpen) {
      set({ paletteOpen: false });
      return true;
    }
    if (s.sessionDrawerOpen) {
      set({ sessionDrawerOpen: false });
      return true;
    }
    if (s.inspectorDrawerOpen) {
      set({ inspectorDrawerOpen: false });
      return true;
    }
    return false;
  },
}));
