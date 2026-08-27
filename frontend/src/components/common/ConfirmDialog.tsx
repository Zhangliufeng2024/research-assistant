/* 小型确认对话框（R15）：破坏性 / 不可逆操作的两段式确认。
 *
 * 用法：视图持有 open 状态，把执行体放进 onConfirm。Esc（useEscapeStack
 * 层级栈）与点击背景 = 取消；busy 期间冻结全部关闭路径，防止重复提交。
 * 焦点默认落在「取消」上——危险操作不应当被一个手滑的 Enter 直接触发。
 */
import { AnimatePresence, motion } from "framer-motion";
import { useEscapeStack } from "@/hooks/useEscapeStack";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** 补充说明（为什么需要确认 / 后果是什么）。 */
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** true 时确认按钮用 danger 色（删除/停止类）。 */
  danger?: boolean;
  /** 执行中：禁用两个按钮并忽略 Esc / 背景关闭。 */
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "确认",
  cancelLabel = "取消",
  danger = false,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  useEscapeStack(open && !busy, onCancel);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[70] flex items-center justify-center bg-black/30 p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.12 } }}
          onMouseDown={() => {
            if (!busy) onCancel();
          }}
        >
          <motion.div
            role="alertdialog"
            aria-modal="true"
            aria-label={title}
            className="w-full max-w-sm rounded-2xl border border-edge bg-surface p-5 shadow-card"
            initial={{ opacity: 0, y: 12, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98, transition: { duration: 0.12 } }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <h2 className="text-[15px] font-semibold">{title}</h2>
            {description && (
              <p className="mt-1.5 text-[12.5px] leading-5 text-ink-2">{description}</p>
            )}
            <div className="mt-4 flex justify-end gap-2.5">
              <button
                type="button"
                onClick={onCancel}
                disabled={busy}
                autoFocus
                className="rounded-xl border border-edge bg-surface px-4 py-2 text-[13px] font-medium transition-colors hover:bg-surface-2 disabled:opacity-50"
              >
                {cancelLabel}
              </button>
              <button
                type="button"
                onClick={onConfirm}
                disabled={busy}
                className={`rounded-xl px-4 py-2 text-[13px] font-semibold text-white transition-colors disabled:opacity-50 ${
                  danger ? "bg-danger hover:opacity-90" : "bg-accent hover:bg-accent-hover"
                }`}
              >
                {confirmLabel}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
