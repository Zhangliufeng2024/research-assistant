/* 消息悬浮操作钮组（R14-M 三件套呈现层）：复制 / 重新生成 / 编辑重发。
 *
 * 呈现约定：
 * - 绝对定位于气泡角落，hover（或键盘聚焦到组内）时浮现——invisible 而非
 *   仅 opacity-0，避免透明按钮截获点击；group 类挂在气泡根节点上；
 * - 定位两档：user 气泡贴右缘 → 组悬于左侧垂直居中（水平空间恒有余量，
 *   无上下裁切风险）；assistant 气泡 → 悬于右上角上方（列表 py-6 顶部
 *   留白兜住大部分场景，仅首条消息贴顶滚动时可能轻微出视口，可接受）；
 * - 流式进行中由调用方整体不渲染（opsEnabled=false），而非置灰——运行期
 *   两个操作都会被 store 以 busy 拒绝，藏起来比点了再提示更不打扰；
 * - 图标为 lucide 风格内联 SVG，描边体系与项目现有按钮一致，双主题走令牌。
 */
import type { ReactNode } from "react";

/** 角标定位档位。 */
export type ActionPlacement = "left-center" | "above-right";

const PLACEMENT_CLASS: Record<ActionPlacement, string> = {
  "left-center": "right-full top-1/2 mr-1.5 -translate-y-1/2",
  "above-right": "-top-2 right-0 -translate-y-full",
};

export interface MessageAction {
  key: string;
  /** title 与 aria-label 共用（悬浮提示 + 可访问名）。 */
  title: string;
  icon: ReactNode;
  onClick: () => void;
}

export function MessageActionBar({
  placement,
  actions,
}: {
  placement: ActionPlacement;
  actions: MessageAction[];
}) {
  return (
    <div
      className={`absolute z-10 flex items-center gap-0.5 rounded-lg border border-edge bg-surface p-0.5 shadow-sm opacity-0 invisible transition-opacity duration-150 focus-within:visible focus-within:opacity-100 group-hover:visible group-hover:opacity-100 ${PLACEMENT_CLASS[placement]}`}
    >
      {actions.map((a) => (
        <button
          key={a.key}
          type="button"
          title={a.title}
          aria-label={a.title}
          onClick={a.onClick}
          className="flex h-6.5 w-6.5 items-center justify-center rounded-md text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
        >
          {a.icon}
        </button>
      ))}
    </div>
  );
}

/* ---- 内联图标（lucide 风格：24 viewBox / currentColor 描边） ---- */

const ICON_PROPS = {
  className: "h-3.5 w-3.5",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
} as const;

export function IconCopy() {
  return (
    <svg {...ICON_PROPS}>
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M4 16V6a2 2 0 0 1 2-2h10" />
    </svg>
  );
}
export function IconRegenerate() {
  return (
    <svg {...ICON_PROPS}>
      <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8" />
      <path d="M21 3v5h-5" />
    </svg>
  );
}
export function IconEditPencil() {
  return (
    <svg {...ICON_PROPS}>
      <path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" />
      <path d="m15 5 4 4" />
    </svg>
  );
}
