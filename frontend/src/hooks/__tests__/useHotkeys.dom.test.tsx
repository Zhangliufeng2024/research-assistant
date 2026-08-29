// @vitest-environment jsdom
/* 阶段 4：全局快捷键（useHotkeys 单一注册表）。
 *
 * 覆盖：Ctrl+K 打开命令面板、Ctrl+B 折叠导航、Ctrl+Shift+O 新建会话、
 * Ctrl+, 打开设置、Esc 关闭抽屉、Alt+↓ 会话切换；以及输入框聚焦时
 * 仅发送类与 Esc 生效（不劫持打字键）。
 */
import { render, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useHotkeys } from "@/hooks/useHotkeys";
import { useUiStore } from "@/stores/uiStore";
import { useChatStore } from "@/stores/chatStore";
import { emptyChat } from "@/lib/protocolChat";
import type { SessionSummary } from "@/lib/types";

function resetUi() {
  useUiStore.setState({
    paletteOpen: false,
    sessionDrawerOpen: false,
    inspectorDrawerOpen: false,
    railCollapsed: false,
    wideLayout: true,
    composerFocusTick: 0,
  });
}

afterEach(() => {
  cleanup();
  localStorage.clear();
});

beforeEach(() => {
  resetUi();
});

/** 挂载 useHotkeys 的宿主组件（含一个可聚焦输入框）。 */
function HotkeyHost() {
  useHotkeys();
  return <input aria-label="测试输入框" />;
}

/** 从指定元素派发 keydown 并冒泡到 window（模拟真实焦点路径）。 */
function press(el: Element, init: KeyboardEventInit) {
  el.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init }));
}

function pressWindow(init: KeyboardEventInit) {
  press(document.body, init);
}

describe("全局快捷键分发", () => {
  it("Ctrl+K 打开命令面板", () => {
    render(<HotkeyHost />);
    pressWindow({ key: "k", ctrlKey: true });
    expect(useUiStore.getState().paletteOpen).toBe(true);
  });

  it("Ctrl+B 折叠/展开左栏导航（可往复）", () => {
    render(<HotkeyHost />);
    pressWindow({ key: "b", ctrlKey: true });
    expect(useUiStore.getState().railCollapsed).toBe(true);
    pressWindow({ key: "b", ctrlKey: true });
    expect(useUiStore.getState().railCollapsed).toBe(false);
  });

  it("Ctrl+Shift+O 新建会话", () => {
    render(<HotkeyHost />);
    const spy = vi.spyOn(useChatStore.getState(), "newSession");
    pressWindow({ key: "O", ctrlKey: true, shiftKey: true });
    expect(spy).toHaveBeenCalledOnce();
  });

  it("Ctrl+, 打开设置（hash 导航）", () => {
    render(<HotkeyHost />);
    pressWindow({ key: ",", ctrlKey: true });
    expect(window.location.hash).toBe("#/settings");
  });

  it("Esc 关闭最上层浮层（会话抽屉）", () => {
    render(<HotkeyHost />);
    useUiStore.getState().setSessionDrawerOpen(true);
    pressWindow({ key: "Escape" });
    expect(useUiStore.getState().sessionDrawerOpen).toBe(false);
  });

  it("Alt+↓ 在会话列表中向下切换（跳过归档）", () => {
    const sessions: SessionSummary[] = [
      { id: "a", title: "会话A", last_message: "", turns: 1, created_at: 1, updated_at: 2 },
      { id: "b", title: "会话B", last_message: "", turns: 1, created_at: 1, updated_at: 3, archived: true },
      { id: "c", title: "会话C", last_message: "", turns: 1, created_at: 1, updated_at: 4 },
    ];
    useChatStore.setState({
      sessions,
      chat: { ...emptyChat(), sessionId: "a" },
    });
    render(<HotkeyHost />);
    const spy = vi.spyOn(useChatStore.getState(), "openSession").mockResolvedValue(undefined);
    pressWindow({ key: "ArrowDown", altKey: true });
    // B 已归档 → 直接跳到 C
    expect(spy).toHaveBeenCalledWith("c");
  });
});

describe("输入框聚焦保护（仅发送类与 Esc 生效）", () => {
  it("输入框聚焦时 Ctrl+B 被忽略（不劫持打字键）", () => {
    render(<HotkeyHost />);
    const input = document.querySelector("input")!;
    input.focus();
    press(input, { key: "b", ctrlKey: true });
    expect(useUiStore.getState().railCollapsed).toBe(false);
    // 失焦后同一键位生效
    input.blur();
    pressWindow({ key: "b", ctrlKey: true });
    expect(useUiStore.getState().railCollapsed).toBe(true);
  });

  it("输入框聚焦时 Ctrl+Enter 仍触发发送事件", () => {
    render(<HotkeyHost />);
    const input = document.querySelector("input")!;
    input.focus();
    const sent = vi.fn();
    window.addEventListener("ra:composer-send", sent);
    press(input, { key: "Enter", ctrlKey: true });
    expect(sent).toHaveBeenCalledOnce();
    window.removeEventListener("ra:composer-send", sent);
  });

  it("输入框聚焦时 Esc 仍可关闭浮层", () => {
    render(<HotkeyHost />);
    const input = document.querySelector("input")!;
    input.focus();
    useUiStore.getState().setPaletteOpen(true);
    press(input, { key: "Escape" });
    expect(useUiStore.getState().paletteOpen).toBe(false);
  });
});
