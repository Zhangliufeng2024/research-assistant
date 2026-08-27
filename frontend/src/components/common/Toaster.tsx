/* 全局轻提示渲染（R14-T）：配合 stores/toastStore 使用。
 *
 * 挂载约定：由应用壳层（App.tsx）渲染一次即可，本组件不自行挂载——
 * 后续视图改造代理负责接线。固定在右下角（避开底部输入区与 ChatView
 * 底部居中的旧式 toast），z-[60] 压过 z-50 的模态层。
 * error 用主题 danger 令牌区分；整卡可点击手动关闭。
 */
import { AnimatePresence, motion } from "framer-motion";
import type { ToastKind } from "@/lib/types";
import { useToastStore } from "@/stores/toastStore";

/** 各类别的视觉令牌：图标 + 主色（边框/文字/图标共用）。 */
const KIND_STYLE: Record<ToastKind, { icon: string; tone: string; label: string }> = {
  info: {
    icon: "ℹ",
    tone: "text-accent-hover dark:text-accent",
    label: "提示",
  },
  success: {
    icon: "✓",
    tone: "text-ok",
    label: "成功",
  },
  error: {
    icon: "⚠",
    tone: "text-danger",
    label: "错误",
  },
};

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts);
  const dismiss = useToastStore((s) => s.dismiss);

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(20rem,calc(100vw-2rem))] flex-col items-end gap-2"
    >
      <AnimatePresence initial={false}>
        {toasts.map((t) => {
          const style = KIND_STYLE[t.kind];
          return (
            <motion.button
              key={t.id}
              type="button"
              onClick={() => dismiss(t.id)}
              title="点击关闭"
              initial={{ opacity: 0, y: 12, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 24, transition: { duration: 0.15, ease: "easeIn" } }}
              transition={{ duration: 0.18, ease: "easeOut" }}
              className={`pointer-events-auto flex w-full items-start gap-2.5 rounded-2xl border bg-surface px-3.5 py-2.5 text-left shadow-card transition-colors hover:bg-surface-2 ${
                t.kind === "error" ? "border-danger/50" : "border-edge"
              }`}
            >
              <span aria-hidden className={`mt-px text-[14px] leading-5 ${style.tone}`}>
                {style.icon}
              </span>
              <span className="min-w-0 flex-1">
                <span className="sr-only">{style.label}：</span>
                <span className="block break-words text-[13px] leading-5 text-ink">
                  {t.message}
                </span>
              </span>
            </motion.button>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
