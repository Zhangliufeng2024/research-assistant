/* 任务页行级门控（R13-F，纯函数供 vitest 覆盖）。
 *
 * 背景：task 通道是单槽——socks 表里每个 channel 只有一个 socket。
 * 观察 B 任务的「继续观察」会 wsClose 掉 A 的观察连接；运行中也一样，
 * 新的 start/resume/restart 会掐掉正在跑的连接。因此凡有活跃观察/运行
 * 占用通道时，其余行的入口必须真正 disabled（此前只有 opacity 弱化，
 * 点击仍然生效）。 */

/** 门控上下文：全部来自 taskStore/WS 状态，视图层负责取值。 */
export interface TaskGateCtx {
  /** 本地任务态当前绑定的任务 id（正在运行或被观察）；null = 空闲 */
  boundTaskId: string | null;
  /** 本地任务态是否 running */
  localRunning: boolean;
  /** task 通道 WS 是否被占用（connecting/open 都算） */
  channelBusy: boolean;
}

/**
 * 行动作是否放行。返回 null = 放行；否则为禁用原因文案（直接作 title）。
 * - 本地任务 running：一切启动/续跑/观察都让路；
 * - 通道被观察占用：本行正是被观察任务 → 提示「已在观察」；
 *   其余行 → 提示先断开当前观察。
 */
export function gateReason(ctx: TaskGateCtx, rowId?: string): string | null {
  if (ctx.localRunning) {
    return rowId && ctx.boundTaskId === rowId
      ? "该任务正在本地运行中"
      : "已有任务在运行中——请等待完成或先停止";
  }
  if (ctx.channelBusy) {
    if (rowId && ctx.boundTaskId === rowId) return "已连接该任务的观察流";
    return ctx.boundTaskId
      ? "正在观察另一任务——停止观察后再试"
      : "观察连接建立中，请稍候";
  }
  return null;
}
