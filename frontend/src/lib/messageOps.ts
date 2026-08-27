/* 消息操作纯函数层（R14-M：重新生成 / 编辑重发）。
 *
 * ── 持久化一致性取舍（改动语义前必读）──────────────────────────
 * 后端会话持久化是追加式 history.json（web/chat.py），没有截断、改写
 * 或分支 API；本地若删改 items，重开该会话时 GET history 会把原始轮次
 * 原样带回，界面出现「被删掉的问答幽灵复活」。因此 chatStore 的两个
 * 操作都采取保守语义：
 * - regenerateMessage：不删历史、不回退本地流——定位该 assistant 气泡
 *   之前最近的 user 提问，以同一提示词原样重新发起一轮（等价于用户
 *   手动把同一个问题再发一遍）；
 * - editAndResend：不回改原 user 气泡的文本——直接以新文本发起一轮。
 * 服务端历史与本地上屏在任何时刻都保持一致；代价是旧问答仍留在流中，
 * 交给视图层用视觉手段（折叠/弱化旧轮次）呈现，而不是伪造数据。
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
