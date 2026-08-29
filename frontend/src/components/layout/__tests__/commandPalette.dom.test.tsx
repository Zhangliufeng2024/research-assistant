// @vitest-environment jsdom
/* 阶段 4：命令面板（Ctrl+K 载体）——开关、模糊过滤、执行命令后关闭。
 * 全局 Ctrl+K 分发已在 useHotkeys.dom.test.tsx 覆盖，这里直接驱动 uiStore
 * （store 置开须在 render 前或 act 内，保证 React 同步刷新）。
 */
import { act, render, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { useUiStore } from "@/stores/uiStore";
import { useChatStore } from "@/stores/chatStore";
import { emptyChat } from "@/lib/protocolChat";
import type { SessionSummary } from "@/lib/types";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

beforeEach(() => {
  useUiStore.setState({ paletteOpen: false });
  useChatStore.setState({ sessions: [], chat: emptyChat() });
});

const session: SessionSummary = {
  id: "s1",
  title: "铁电材料调研",
  last_message: "",
  turns: 2,
  created_at: 1,
  updated_at: 2,
};

describe("CommandPalette", () => {
  it("默认不渲染；置开后出现对话框与输入框", () => {
    const { queryByRole, getByRole } = render(<CommandPalette />);
    expect(queryByRole("dialog")).toBeNull();
    act(() => useUiStore.getState().setPaletteOpen(true));
    expect(getByRole("dialog", { name: "命令面板" })).toBeTruthy();
  });

  it("默认列表包含命令与会话条目（同池展示）", () => {
    useUiStore.setState({ paletteOpen: true });
    useChatStore.setState({ sessions: [session] });
    render(<CommandPalette />);
    expect(document.body.textContent).toContain("打开设置");
    expect(document.body.textContent).toContain("铁电材料调研");
  });

  it("模糊过滤：输入「铁电」只剩会话条目", () => {
    useUiStore.setState({ paletteOpen: true });
    useChatStore.setState({ sessions: [session] });
    const { container } = render(<CommandPalette />);
    const input = container.querySelector("input")!;
    // 以原生 setter 驱动受控输入（React 18 受控组件兼容写法）
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, "铁电");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    expect(document.body.textContent).toContain("铁电材料调研");
    expect(document.body.textContent).not.toContain("打开设置");
  });

  it("执行命令后自动关闭面板（点击「打开设置」→ hash 跳转）", async () => {
    const user = userEvent.setup();
    useUiStore.setState({ paletteOpen: true });
    render(<CommandPalette />);
    const item = [...document.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("打开设置"),
    );
    expect(item).toBeTruthy();
    await user.click(item!);
    expect(window.location.hash).toBe("#/settings");
    expect(useUiStore.getState().paletteOpen).toBe(false);
  });

  it("Esc 关闭面板（输入框内 Esc，不落全局分发）", async () => {
    const user = userEvent.setup();
    useUiStore.setState({ paletteOpen: true });
    render(<CommandPalette />);
    await user.type(document.querySelector("input")!, "{Escape}");
    expect(useUiStore.getState().paletteOpen).toBe(false);
  });
});
