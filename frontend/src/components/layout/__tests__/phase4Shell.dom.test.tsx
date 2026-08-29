// @vitest-environment jsdom
/* 阶段 4 壳层集成：常驻会话区（U-4）、检查器抽屉兜底（U-11）、会话二级抽屉。
 *
 * - 导航离开 /chat 再回来，聊天组件树不卸载、输入草稿保留；
 * - <1280px（matchMedia 桩）检查器为抽屉形态；宽屏为内联 dock 细条；
 * - 导航栏会话项滑出二级抽屉（SessionList 复用）。
 */
import { render, cleanup, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import App from "@/App";
import { ChatView } from "@/views/ChatView";
import { SessionDrawer } from "@/components/layout/SessionDrawer";
import { useUiStore } from "@/stores/uiStore";
import { ONBOARDING_KEY } from "@/hooks/useFirstRunWizard";
import { useHotkeys } from "@/hooks/useHotkeys";
import { renderWithRouter } from "@/test/domTestUtils";

/** 窄屏桩：<1280px（jsdom 无 matchMedia，需显式注入）。 */
function stubMatchMedia(matches: boolean) {
  window.matchMedia = ((query: string) =>
    ({
      matches: matches,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  localStorage.clear();
  localStorage.setItem(ONBOARDING_KEY, "1"); // 跳过首次运行向导
  window.location.hash = "";
  useUiStore.setState({
    paletteOpen: false,
    sessionDrawerOpen: false,
    inspectorDrawerOpen: false,
    railCollapsed: false,
    inspectorOpen: true,
    wideLayout: true,
    composerFocusTick: 0,
  });
});

afterEach(() => {
  cleanup();
  // @ts-expect-error 测试后移除桩，避免影响其它用例
  delete window.matchMedia;
  localStorage.clear();
});

describe("U-4 常驻会话区", () => {
  it("导航到其它页后聊天组件树不卸载，草稿原样保留", async () => {
    const user = userEvent.setup();
    window.location.hash = "#/chat";
    render(<App />);

    // 懒加载的常驻会话区就绪
    const composer = await screen.findByPlaceholderText("输入消息，与助手讨论…");
    await user.type(composer, "常驻草稿记忆");

    // 经导航栏切到资料库（文库）
    await user.click(screen.getByRole("link", { name: "文库" }));
    await waitFor(() => {
      expect(screen.getByRole("main").className).not.toContain("hidden");
    });
    // 会话区只是隐藏（display:none），聊天组件仍在文档中且草稿未丢
    const section = screen.getByRole("region", { name: "会话区" }) as HTMLElement;
    expect(section.className).toContain("hidden");
    expect((screen.getByPlaceholderText("输入消息，与助手讨论…") as HTMLTextAreaElement).value).toBe(
      "常驻草稿记忆",
    );

    // 切回会话区：可见性恢复，草稿仍在（会话项同时滑出二级抽屉，不影响断言）
    await user.click(screen.getByRole("button", { name: "会话" }));
    await waitFor(() => {
      expect(section.className).not.toContain("hidden");
    });
    expect((screen.getByPlaceholderText("输入消息，与助手讨论…") as HTMLTextAreaElement).value).toBe(
      "常驻草稿记忆",
    );
  });
});

describe("U-11 检查器形态切换", () => {
  it("窄屏（<1280px）：工具条「产物」入口滑出检查器抽屉", async () => {
    stubMatchMedia(false);
    useUiStore.setState({ inspectorOpen: false });
    renderWithRouter(<ChatView />, "/chat");
    const entry = await screen.findByRole("button", { name: "产物" });
    expect(screen.queryByTestId("inspector-drawer")).toBeNull();
    fireEvent.click(entry);
    expect(screen.getByTestId("inspector-drawer")).toBeTruthy();
    expect(screen.getByRole("complementary", { name: "检查器" })).toBeTruthy();
  });

  it("宽屏（≥1280px）：检查器为内联细条（无抽屉）", async () => {
    stubMatchMedia(true);
    useUiStore.setState({ inspectorOpen: false });
    renderWithRouter(<ChatView />, "/chat");
    // 折叠态 → 竖排细条把手；抽屉形态不存在
    expect(await screen.findByRole("button", { name: "展开产出文件面板" })).toBeTruthy();
    expect(screen.queryByTestId("inspector-drawer")).toBeNull();
  });
});

describe("导航栏会话二级抽屉", () => {
  it("打开时渲染会话列表（含新会话草稿行），全局 Esc 关闭", async () => {
    useUiStore.getState().setSessionDrawerOpen(true);
    // useHotkeys 宿主 + 抽屉：Esc 走全局注册表分发（与 App 一致）
    function HotkeyHost() {
      useHotkeys();
      return null;
    }
    render(
      <>
        <HotkeyHost />
        <SessionDrawer />
      </>,
    );
    expect(screen.getByRole("complementary", { name: "会话列表" })).toBeTruthy();
    // 空会话态：未发送草稿行可见（SessionList 语义保留）
    expect(screen.getByText("点击输入第一条消息")).toBeTruthy();
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => {
      expect(useUiStore.getState().sessionDrawerOpen).toBe(false);
    });
  });
});
