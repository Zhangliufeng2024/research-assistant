/** 会话运行中的等待看门狗策略（R9）。
 *
 * 背景：模型端点不可达/极慢时，服务端要经历 连接超时×重试+退避 才发错误帧，
 * 期间用户只看到永久「思考中」（R9 用户反馈的致命体验）。前端按「最近一次
 * 可见内容（文本增量/工具卡）以来的秒数」给出渐进提示，把黑盒变成可感知。
 */

/** 超过该秒数没有任何可见输出即显示等待提示。 */
export const WAIT_HINT_THRESHOLD_S = 20;

export function shouldShowWaitHint(phase: string, silentSeconds: number): boolean {
  return phase === "running" && silentSeconds >= WAIT_HINT_THRESHOLD_S;
}
