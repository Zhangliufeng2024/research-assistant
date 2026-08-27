/* 审批全局感知判定（R15）：来源页面归属与提醒文案。
 * ApprovalToastWatcher 的 React 订阅层薄，核心断言落在本纯逻辑上。
 */
import { describe, expect, it } from "vitest";
import {
  formatApprovalNotice,
  isOnSourcePage,
  shouldNotifyApproval,
} from "@/components/layout/approvalNotify";

describe("isOnSourcePage（审批来源 → 页面归属）", () => {
  it("chat 来源：会话页及其子路径视为在场", () => {
    expect(isOnSourcePage("/chat", "chat")).toBe(true);
    expect(isOnSourcePage("/chat/anything", "chat")).toBe(true);
    expect(isOnSourcePage("/", "chat")).toBe(false);
    expect(isOnSourcePage("/tasks", "chat")).toBe(false);
    expect(isOnSourcePage("/settings", "chat")).toBe(false);
  });

  it("task 来源：任务中心聚合组三页均算在场", () => {
    expect(isOnSourcePage("/tasks", "task")).toBe(true);
    expect(isOnSourcePage("/scheduler", "task")).toBe(true);
    expect(isOnSourcePage("/analysis", "task")).toBe(true);
    expect(isOnSourcePage("/chat", "task")).toBe(false);
    expect(isOnSourcePage("/papers", "task")).toBe(false);
  });

  it("段边界：/chatty 不算会话页", () => {
    expect(isOnSourcePage("/chatty", "chat")).toBe(false);
  });
});

describe("shouldNotifyApproval（不在对应页面才提醒）", () => {
  it("与 isOnSourcePage 互为反相", () => {
    expect(shouldNotifyApproval("/settings", "chat")).toBe(true);
    expect(shouldNotifyApproval("/chat", "chat")).toBe(false);
    expect(shouldNotifyApproval("/research", "task")).toBe(true);
    expect(shouldNotifyApproval("/analysis", "task")).toBe(false);
  });
});

describe("formatApprovalNotice（toast 文案）", () => {
  it("格式为 待审批：{tool} — {summary}", () => {
    expect(
      formatApprovalNotice({ tool: "bash", summary: "执行 rm -rf tmp/" }),
    ).toBe("待审批：bash — 执行 rm -rf tmp/");
  });

  it("空 summary 不产生悬空分隔符以外的怪异文案", () => {
    expect(formatApprovalNotice({ tool: "python_exec", summary: "" })).toBe(
      "待审批：python_exec — ",
    );
  });
});
