/* 消息气泡 memo 边界（R14-R）：结构 + 纯度验证。
 *
 * 项目没有 @testing-library/react / react-test-renderer，node 环境无真实
 * DOM，无法直接断言「props 不变则跳过重渲染」的 React 内部行为。退而求
 * 其次做两层可机检的等价验证：
 * 1) 结构断言：三个气泡组件确实被 React.memo 包裹（$$typeof ===
 *    REACT_MEMO_TYPE）——memo 生效的前提；
 * 2) 纯度断言：用 ReactDOMServer.renderToString 证明渲染输出完全由 props
 *    决定（相同 props → 相同 HTML，不同 text → 不同 HTML）。配合默认
 *    浅比较语义与「回调一律来自 useCallback」的调用方纪律（见
 *    MessageBubbles.tsx 头注），即构成「历史消息流式期间跳过重解析」的
 *    完整链路。
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import {
  AssistantBubble,
  ToolCardRow,
  UserBubble,
} from "@/components/chat/MessageBubbles";

const REACT_MEMO_TYPE = Symbol.for("react.memo");

describe("MessageBubbles memo 边界（R14-R）", () => {
  it("三个气泡组件都是 React.memo 包裹", () => {
    for (const component of [UserBubble, AssistantBubble, ToolCardRow]) {
      expect(
        (component as unknown as { $$typeof: symbol }).$$typeof,
        "组件必须包在 React.memo 里，否则流式期间历史消息会被整树重渲染",
      ).toBe(REACT_MEMO_TYPE);
    }
  });

  it("AssistantBubble：渲染仅由 props 决定（同 props 同输出；text 变则输出变）", () => {
    const base = {
      showCursor: false,
      idx: 0,
      opsEnabled: true,
      onCopyMessage: () => {},
      onRegenerate: () => {},
    };
    const a = renderToStaticMarkup(<AssistantBubble text="## 结果一" {...base} />);
    const b = renderToStaticMarkup(<AssistantBubble text="## 结果一" {...base} />);
    const c = renderToStaticMarkup(<AssistantBubble text="## 结果二" {...base} />);

    expect(a).toBe(b);
    expect(a).not.toBe(c);
    expect(a).toContain("结果一");
  });

  it("AssistantBubble：showCursor 是渲染输入之一（光标随流式显隐）", () => {
    const base = {
      idx: 0,
      opsEnabled: false,
      onCopyMessage: () => {},
      onRegenerate: () => {},
    };
    const withCursor = renderToStaticMarkup(
      <AssistantBubble text="hi" showCursor {...base} />,
    );
    const without = renderToStaticMarkup(
      <AssistantBubble text="hi" showCursor={false} {...base} />,
    );
    expect(withCursor).not.toBe(without);
  });

  it("UserBubble：默认渲染原文与引导标记；opsEnabled=false 时不出现操作钮", () => {
    const idle = renderToStaticMarkup(
      <UserBubble
        text="第一问"
        steer
        idx={0}
        opsEnabled={false}
        onCopyMessage={() => {}}
        onEditSubmit={async () => "ok"}
      />,
    );
    expect(idle).toContain("第一问");
    expect(idle).toContain("已作为引导注入");
    expect(idle).not.toContain('aria-label="编辑重发"');
  });

  it("ToolCardRow：卡片实体引用不变即同输出（浅比较语义下可跳过子树）", () => {
    const card = {
      id: "c1",
      tool: "run_python",
      args: { code: "print(1)" },
      status: "ok",
      preview: "1",
      files: [],
      t: 1,
    };
    const a = renderToStaticMarkup(
      <ToolCardRow card={card} onOpenFile={() => {}} />,
    );
    const b = renderToStaticMarkup(
      <ToolCardRow card={card} onOpenFile={() => {}} />,
    );
    expect(a).toBe(b);
    // 新引用但内容相同 → 浅比较失败会重渲染（这正是要求稳定引用的原因）
    const sameContentNewRef = { ...card };
    const c = renderToStaticMarkup(
      <ToolCardRow card={sameContentNewRef} onOpenFile={() => {}} />,
    );
    expect(c).toBe(a); // 输出一致，但代价是重渲染——引用稳定性靠调用方纪律保证
  });
});
