/* 全局快捷键体系（阶段 4，设计文档 §3）：单一命令注册表 + 键盘分发。
 *
 * 命令注册表（buildCommands）是唯一事实源：命令面板（CommandPalette）与
 * 全局键盘分发（useHotkeys）共用同一份列表，避免两套分发逻辑漂移。
 * 命令的 run() 惰性调用各 zustand store 的 getState()，可在任意上下文执行。
 *
 * 键位表（文档 §3）：
 *   Ctrl/Cmd+K        命令面板
 *   Ctrl/Cmd+Enter    发送消息（发送类，输入框聚焦时仍生效）
 *   Ctrl/Cmd+Shift+O  新建会话
 *   Ctrl/Cmd+B        折叠/展开左栏导航
 *   Ctrl/Cmd+I        检查器开关
 *   Ctrl/Cmd+.        中断当前回合
 *   Ctrl/Cmd+J        聚焦输入框
 *   Esc               关闭抽屉/命令面板（输入框聚焦时仍生效）
 *   Alt+↑/↓           会话列表上下切换
 *   Ctrl/Cmd+,        打开设置
 *
 * 输入框保护：焦点在 input/textarea/contenteditable 时，仅 allowInInput
 * 的命令（发送类与 Esc）生效——不劫持打字键。SessionList 等局部编辑框
 * 已自行 stopPropagation，天然免疫全局分发。
 */
import { useEffect } from "react";
import { useChatStore } from "@/stores/chatStore";
import { useUiStore } from "@/stores/uiStore";

/** Composer 监听的发送事件（Ctrl+Enter 全局发送的唯一通道）。 */
export const EVENT_COMPOSER_SEND = "ra:composer-send";

/** 命令定义。key 为规范化小写键名；ctrl 表示 Ctrl 或 Cmd（平台无关）。 */
export interface HotkeyCommand {
  id: string;
  title: string;
  /** 展示用标签（命令面板右列），如 "Ctrl+K"。 */
  hotkey?: string;
  key: string;
  ctrl?: boolean;
  shift?: boolean;
  alt?: boolean;
  /** true = 输入框聚焦时仍生效（仅发送类与 Esc）。 */
  allowInInput?: boolean;
  /** 命令面板隐藏（纯键位实现细节，如 Esc 的「无浮层即无操作」）。 */
  hidden?: boolean;
  run(): void;
}

/** HashRouter 导航：直接改 hash，路由器监听 hashchange 自行同步。 */
export function go(path: string): void {
  try {
    const target = `#${path}`;
    if (window.location.hash !== target) window.location.hash = target;
  } catch {
    /* 非浏览器环境忽略 */
  }
}

/** 命令注册表（唯一事实源）。每次调用返回新数组，run 均为惰性求值。 */
export function buildCommands(): HotkeyCommand[] {
  const ui = () => useUiStore.getState();
  const chat = () => useChatStore.getState();

  /** 会话列表上/下切换：非归档会话按列表序取相邻项。 */
  const switchSession = (delta: 1 | -1) => {
    const st = chat();
    const list = st.sessions.filter((s) => !s.archived);
    if (list.length === 0) return;
    const cur = list.findIndex((s) => s.id === st.chat.sessionId);
    const next = cur === -1 ? (delta === 1 ? 0 : list.length - 1) : (cur + delta + list.length) % list.length;
    const target = list[next];
    if (!target) return;
    go(`/chat/${encodeURIComponent(target.id)}`);
    void st.openSession(target.id).then(() => st.refreshSessions()).catch(() => {});
  };

  return [
    {
      id: "palette.open",
      title: "打开命令面板",
      hotkey: "Ctrl+K",
      key: "k",
      ctrl: true,
      run: () => ui().setPaletteOpen(true),
    },
    {
      id: "chat.send",
      title: "发送消息",
      hotkey: "Ctrl+Enter",
      key: "enter",
      ctrl: true,
      allowInInput: true,
      hidden: true, // 发送是输入框语境动作，面板里列出反而不明所以
      run: () => window.dispatchEvent(new CustomEvent(EVENT_COMPOSER_SEND)),
    },
    {
      id: "session.new",
      title: "新建会话",
      hotkey: "Ctrl+Shift+O",
      key: "o",
      ctrl: true,
      shift: true,
      run: () => {
        go("/chat");
        chat().newSession();
      },
    },
    {
      id: "nav.rail",
      title: "折叠/展开左侧导航",
      hotkey: "Ctrl+B",
      key: "b",
      ctrl: true,
      run: () => ui().toggleRailCollapsed(),
    },
    {
      id: "inspector.toggle",
      title: "检查器开关",
      hotkey: "Ctrl+I",
      key: "i",
      ctrl: true,
      run: () => {
        const s = ui();
        // 窄屏切抽屉形态，宽屏切内联 dock（U-11：任何视口都不消失）
        if (s.wideLayout) s.toggleInspector();
        else s.setInspectorDrawerOpen(!s.inspectorDrawerOpen);
      },
    },
    {
      id: "chat.stop",
      title: "中断当前回合",
      hotkey: "Ctrl+.",
      key: ".",
      ctrl: true,
      run: () => chat().stop(),
    },
    {
      id: "composer.focus",
      title: "聚焦输入框",
      hotkey: "Ctrl+J",
      key: "j",
      ctrl: true,
      run: () => {
        go("/chat");
        ui().bumpComposerFocus();
      },
    },
    {
      id: "overlay.close",
      title: "关闭抽屉/命令面板",
      hotkey: "Esc",
      key: "escape",
      allowInInput: true,
      hidden: true,
      run: () => ui().closeTopOverlay(),
    },
    {
      id: "session.prev",
      title: "上一个会话",
      hotkey: "Alt+↑",
      key: "arrowup",
      alt: true,
      run: () => switchSession(-1),
    },
    {
      id: "session.next",
      title: "下一个会话",
      hotkey: "Alt+↓",
      key: "arrowdown",
      alt: true,
      run: () => switchSession(1),
    },
    {
      id: "settings.open",
      title: "打开设置",
      hotkey: "Ctrl+,",
      key: ",",
      ctrl: true,
      run: () => go("/settings"),
    },
  ];
}

/** 命令面板可见条目（隐藏 Esc/发送等实现细节键位）。 */
export function visibleCommands(): HotkeyCommand[] {
  return buildCommands().filter((c) => !c.hidden);
}

interface KeyEventLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}

/** 键事件 → 命令匹配（ctrl 定义同时接受 Ctrl 与 Cmd）。 */
export function matchCommand(
  ev: KeyEventLike,
  commands: HotkeyCommand[],
): HotkeyCommand | null {
  const key = ev.key.toLowerCase();
  for (const c of commands) {
    if (c.key !== key) continue;
    if (!!c.ctrl !== (ev.ctrlKey || ev.metaKey)) continue;
    if (!!c.shift !== ev.shiftKey) continue;
    if (!!c.alt !== ev.altKey) continue;
    return c;
  }
  return null;
}

/** 焦点是否处于文本输入类元素（打字保护判定）。 */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    target.isContentEditable
  );
}

/** 全局键盘分发：App 壳层挂一次即可。 */
export function useHotkeys(): void {
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const cmd = matchCommand(ev, buildCommands());
      if (!cmd) return;
      // 输入框聚焦时仅发送类与 Esc 生效（不劫持打字键）
      if (isEditableTarget(ev.target) && !cmd.allowInInput) return;
      ev.preventDefault();
      cmd.run();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
