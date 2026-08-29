// @vitest-environment jsdom
/* 错误边界（A+ 1.2）。
 *
 * 修复前全库无 ErrorBoundary：任一 view 渲染抛错即白屏整个应用，且 15 个
 * lazy chunk 无加载失败兜底。这些用例锁定四类行为——捕获、降级、重试、
 * resetKey 自动恢复，以及「未出错时必须完全透明」这一反向约束。 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { captureConsole } from "@/test/domTestUtils";

/**
 * 开关式抛错桩。
 *
 * ⚠️ 不能用「第 N 次渲染才抛」的计数式桩：React 在错误边界捕获时会**同步
 * 重试一次渲染**以采集更完整的 componentStack，计数器会被多推一格，
 * 于是重试渲染反而拿到正常分支，错误态被自动清掉（表现为用例看到
 * "恢复正常"而不是降级 UI）。显式开关没有这个歧义。
 *
 * 同时注意：实例必须提到渲染之外（`const t = makeFlaky()`），不能在 JSX
 * 里现造——那会每次渲染都重置开关。
 */
function makeFlaky(message = "炸了") {
  const state = { shouldThrow: true };
  return {
    state,
    Component() {
      if (state.shouldThrow) throw new Error(message);
      return <div>恢复正常</div>;
    },
  };
}

/** 无条件抛错（用于不需要恢复的场景）。 */
function AlwaysBoom(): never {
  throw new Error("总是炸");
}

describe("ErrorBoundary", () => {
  it("捕获渲染异常并显示降级 UI，而不是整页白屏", () => {
    const cap = captureConsole("error");
    try {
      render(
        <ErrorBoundary label="页面">
          <AlwaysBoom />
        </ErrorBoundary>,
      );
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(screen.getByText("页面出错了")).toBeTruthy();
      // 降级 UI 里回显了错误信息，便于用户反馈
      expect(screen.getByText("总是炸")).toBeTruthy();
    } finally {
      cap.restore();
    }
  });

  it("未抛错时完全透明：原样渲染 children，不产生 alert 节点", () => {
    render(
      <ErrorBoundary label="页面">
        <div>正常内容</div>
      </ErrorBoundary>,
    );
    expect(screen.getByText("正常内容")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("componentDidCatch 触发 onError 回调并带上组件栈", () => {
    const cap = captureConsole("error");
    const seen: Array<{ message: string; hasStack: boolean }> = [];
    try {
      render(
        <ErrorBoundary
          label="页面"
          onError={(error, info) =>
            seen.push({
              message: error.message,
              hasStack: typeof info.componentStack === "string",
            })
          }
        >
          <AlwaysBoom />
        </ErrorBoundary>,
      );
    } finally {
      cap.restore();
    }
    expect(seen).toHaveLength(1);
    expect(seen[0].message).toBe("总是炸");
    expect(seen[0].hasStack).toBe(true);
  });

  it("点击「重试」清除错误态并重新渲染 children", async () => {
    const cap = captureConsole("error");
    const flaky = makeFlaky("首次渲染炸了");
    try {
      render(
        <ErrorBoundary label="页面">
          <flaky.Component />
        </ErrorBoundary>,
      );
      expect(screen.getByRole("alert")).toBeTruthy();

      // 触发条件消失（例如后端恢复了、数据形状修好了）
      flaky.state.shouldThrow = false;
      await userEvent.click(screen.getByRole("button", { name: "重试" }));

      expect(screen.getByText("恢复正常")).toBeTruthy();
      expect(screen.queryByRole("alert")).toBeNull();
    } finally {
      cap.restore();
    }
  });

  it("resetKey 变化（导航到别的路由）后自动恢复，无需手动刷新", () => {
    const cap = captureConsole("error");
    const state = { broken: true };
    function RouteLike() {
      if (state.broken) throw new Error("此路由崩了");
      return <div>另一页内容</div>;
    }
    try {
      const { rerender } = render(
        <ErrorBoundary label="页面" resetKey="/broken">
          <RouteLike />
        </ErrorBoundary>,
      );
      expect(screen.getByRole("alert")).toBeTruthy();

      // 模拟用户导航到另一个能正常渲染的路由
      state.broken = false;
      rerender(
        <ErrorBoundary label="页面" resetKey="/healthy">
          <RouteLike />
        </ErrorBoundary>,
      );

      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByText("另一页内容")).toBeTruthy();
    } finally {
      cap.restore();
    }
  });

  it("resetKey 未变时不自动恢复（避免把用户卡在闪烁的重渲染里）", () => {
    const cap = captureConsole("error");
    try {
      const { rerender } = render(
        <ErrorBoundary label="页面" resetKey="/broken">
          <AlwaysBoom />
        </ErrorBoundary>,
      );
      // 同一 resetKey 下因父组件更新而重渲染
      rerender(
        <ErrorBoundary label="页面" resetKey="/broken">
          <div>无关更新</div>
        </ErrorBoundary>,
      );
      // 错误态保持：用户看到的是稳定的降级 UI，而不是闪烁
      expect(screen.getByRole("alert")).toBeTruthy();
      expect(screen.queryByText("无关更新")).toBeNull();
    } finally {
      cap.restore();
    }
  });

  it("自定义 fallback 优先于内置卡片，并拿到 reset", async () => {
    const cap = captureConsole("error");
    const flaky = makeFlaky("首次渲染炸了");
    try {
      render(
        <ErrorBoundary
          label="页面"
          fallback={(error, reset) => (
            <div>
              <span>自定义：{error.message}</span>
              <button type="button" onClick={reset}>
                自定义重试
              </button>
            </div>
          )}
        >
          <flaky.Component />
        </ErrorBoundary>,
      );
      expect(screen.getByText("自定义：首次渲染炸了")).toBeTruthy();
      // 自定义 fallback 不套内置卡片的 role="alert"
      expect(screen.queryByRole("alert")).toBeNull();

      flaky.state.shouldThrow = false;
      await userEvent.click(screen.getByRole("button", { name: "自定义重试" }));
      expect(screen.getByText("恢复正常")).toBeTruthy();
    } finally {
      cap.restore();
    }
  });
});
