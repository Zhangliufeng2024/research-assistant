/* 消息操作纯函数层（R14-M：重新生成 / 编辑重发）。
 *
 * ── 持久化一致性取舍（改动语义前必读）──────────────────────────
 * P2-10 更正：本头注此前描述的是**最初的保守语义**（「不删历史、不回改
 * 气泡」），代码后来演进为**真替换**，注释未跟上——以本段为准：
 * 后端已提供截断/改写 API（PATCH history / truncate），chatStore 的两个
 * 操作均按真替换实现：
 * - regenerateMessage：定位该 assistant 气泡之前最近的 user 提问，调用
 *   truncateHistory 截掉旧轮次后以同一提示词（连同原附件）重新发起；
 * - editAndResend：同样 truncate 后以新文本重发，本地原气泡文本随服务端
 *   历史一并更新。
 * 服务端历史与本地在截断点之后保持一致；截断点之前的轮次不受影响。
 * 离线/草稿态（无 sessionId）回落保守重发，见 chatStore 内联注释。
 *
 * 身份模型：ChatItem 没有稳定 id，「messageId」即 chat.items 的数组下标
 * （与 MessageList 渲染顺序一一对应）。会话切换/历史恢复后下标失效，
 * 调用方必须用当前 store 里的 items 重新解析下标。
 */
import type { ChatItem } from "./types";

/** 操作结果码：沿用 send() 的三态，另加 busy（流式中拒绝执行）。 */
export type MessageOpResult = "ok" | "empty" | "offline" | "busy";

/**
 * 解析「重新生成」应复用的 user 提示词下标。
 * messageId 直接指向 user 气泡时返回自身；指向 assistant 文本气泡时向前
 * 找最近的 user 气泡；越界 / 非整数 / 找不到时返回 null。
 */
export function resolveRegenerateTarget(
  items: ChatItem[],
  messageId: number,
): number | null {
  if (!Number.isInteger(messageId) || messageId < 0 || messageId >= items.length) {
    return null;
  }
  if (items[messageId]!.kind === "user") return messageId;
  for (let i = messageId - 1; i >= 0; i--) {
    if (items[i]!.kind === "user") return i;
  }
  return null;
}

/** messageId 是否恰好指向一条 user 消息（editAndResend 的硬性前置）。 */
export function isValidUserIndex(items: ChatItem[], messageId: number): boolean {
  return (
    Number.isInteger(messageId) &&
    messageId >= 0 &&
    messageId < items.length &&
    items[messageId]!.kind === "user"
  );
}
