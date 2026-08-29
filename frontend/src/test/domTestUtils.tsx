/* DOM 测试基础设施（A+ 阶段 1.2 引入；原属阶段 4 的 U-5）
 *
 * 背景：此前前端没有 jsdom / @testing-library/react，`.tsx` 用例只能用
 * `ReactDOMServer.renderToStaticMarkup` 做「结构 + 纯度」断言——**交互链路
 * 零覆盖**。这正是 R7~R9 三轮前端状态机 bug 逃逸测试网的根因（那几次
 * 最终是靠真实浏览器 E2E 才抓到的）。
 *
 * 之所以提前到阶段 1：1.2 的两个 P0 修复（无限轮询、错误边界）都**只能**
 * 用真实渲染 + 真实 effect 来验证，否则只能停留在人工复现步骤。
 *
 * 使用约定：
 *   - 文件名以 `.dom.test.tsx` 结尾，并在**首行**写 `// @vitest-environment jsdom`；
 *     其它测试继续跑 node 环境，互不影响（不用已废弃的 environmentMatchGlobs）。
 *   - 覆盖率配置已排除 `src/test/**`（见 vite.config.ts）。
 */
import { cleanup, render } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach } from "vitest";

// vitest 未启用 globals，RTL 的自动 cleanup 不会注册 —— 这里手动挂载，
// 否则每个用例的 DOM 会残留并相互污染。
afterEach(() => {
  cleanup();
  try {
    localStorage.clear();
  } catch {
    /* jsdom 无 localStorage 时忽略 */
  }
});

/** 渲染需要 Router 上下文的组件（Link / useLocation 等）。 */
export function renderWithRouter(ui: ReactElement, route = "/") {
  return render(<MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>);
}

/** 给需要 Router 的场景套一层，便于 rerender 时保持同一棵树。 */
export function withRouter(children: ReactNode, route = "/") {
  return <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>;
}

/**
 * 把 logger 暂时替换为记录器，返回收集到的调用。
 *
 * 用途有二：① 断言确实走到了告警/错误分支；② 压掉 React 对「组件渲染抛错」
 * 的预期内噪声输出（错误边界测试里会大量出现）。
 */
export function captureConsole(method: "error" | "warn" | "log" = "error") {
  const messages: unknown[][] = [];
  const original = console[method];
  const stub = (...args: unknown[]) => {
    messages.push(args);
  };
  console[method] = stub as typeof console.error;
  return {
    messages,
    restore: () => {
      console[method] = original;
    },
  };
}
