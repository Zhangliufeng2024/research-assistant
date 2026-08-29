// @vitest-environment jsdom
/* 阶段 4 / U-4：每会话草稿持久化（sessionStore + Composer 集成）。
 *
 * 覆盖三条关键链路：
 * 1. setDraft 写入即持久化到 localStorage（崩溃恢复可用）；
 * 2. 切换会话（draftKey 变化）草稿互不串扰、离开再回来仍在；
 * 3. 发送成功清空草稿。
 */
import { render, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Composer } from "@/components/chat/Composer";
import { NEW_DRAFT_KEY, useSessionStore } from "@/stores/sessionStore";
import type { AttachmentRef } from "@/lib/types";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

beforeEach(() => {
  useSessionStore.setState({ drafts: {}, anchors: {} });
});

const baseProps = {
  running: false,
  pendingAttachments: [] as AttachmentRef[],
  attaching: false,
  onSend: vi.fn(async () => "ok" as const),
  onAttach: vi.fn(async () => "ok" as const),
  onRemoveAttachment: vi.fn(),
};

function getComposerValue(): string {
  const textarea = document.querySelector("textarea");
  return textarea ? (textarea as HTMLTextAreaElement).value : "";
}

describe("sessionStore 草稿持久化", () => {
  it("setDraft 写入即持久化到 localStorage（按会话 id 键）", () => {
    useSessionStore.getState().setDraft("sess-1", "你好，世界");
    const raw = localStorage.getItem("ra.session-state.v1");
    expect(raw).toBeTruthy();
    expect(JSON.parse(raw!).drafts["sess-1"]).toBe("你好，世界");
    expect(useSessionStore.getState().getDraft("sess-1")).toBe("你好，世界");
  });

  it("null 会话键落到 NEW_DRAFT_KEY 兜底键", () => {
    useSessionStore.getState().setDraft(null, "未发送的新会话草稿");
    expect(useSessionStore.getState().getDraft(NEW_DRAFT_KEY)).toBe("未发送的新会话草稿");
  });
});

describe("Composer 每会话草稿（切会话不丢）", () => {
  it("切会话草稿互不串扰，切回后原草稿恢复", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Composer {...baseProps} draftKey="a" />);
    await user.type(document.querySelector("textarea")!, "会话A的草稿");
    expect(getComposerValue()).toBe("会话A的草稿");

    // 切到会话 B：输入框载入 B 的（空）草稿，A 的草稿已入 store
    rerender(<Composer {...baseProps} draftKey="b" />);
    expect(getComposerValue()).toBe("");
    await user.type(document.querySelector("textarea")!, "B");
    expect(getComposerValue()).toBe("B");

    // 切回 A：草稿原样恢复
    rerender(<Composer {...baseProps} draftKey="a" />);
    expect(getComposerValue()).toBe("会话A的草稿");
  });

  it("发送成功后草稿清空", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn(async () => "ok" as const);
    render(<Composer {...baseProps} draftKey="a" onSend={onSend} />);
    const textarea = document.querySelector("textarea")!;
    await user.type(textarea, "要发送的话");
    await user.click(document.querySelector('button[aria-label="发送消息"]')!);
    expect(onSend).toHaveBeenCalledWith("要发送的话");
    expect(useSessionStore.getState().getDraft("a")).toBe("");
  });

  it("发送失败时草稿保留原文", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn(async () => "offline" as const);
    render(<Composer {...baseProps} draftKey="a" onSend={onSend} />);
    const textarea = document.querySelector("textarea")!;
    await user.type(textarea, "发不出去的话");
    await user.click(document.querySelector('button[aria-label="发送消息"]')!);
    expect(useSessionStore.getState().getDraft("a")).toBe("发不出去的话");
  });
});
