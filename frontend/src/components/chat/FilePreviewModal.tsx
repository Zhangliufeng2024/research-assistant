import { motion } from "framer-motion";
import { FilePreview } from "@/components/chat/FilePreview";

/** 工作区文件预览弹窗（R12 P3/C2 退化为遮罩壳）：预览主体在 FilePreview，
 * 候选路径按序回退；与右侧产出 dock 共用。 */
export function FilePreviewModal({
  paths,
  onClose,
}: {
  paths: string[];
  onClose: () => void;
}) {
  const path = paths[0] ?? "";
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 p-6"
      onClick={onClose}
      role="presentation"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.97 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.15 }}
        className="flex max-h-full w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-edge bg-surface shadow-card"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`预览 ${path}`}
      >
        <div className="flex shrink-0 items-center gap-2 border-b border-edge px-4 py-2.5">
          <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink-2">
            {path}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
            aria-label="关闭预览"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
              strokeLinecap="round" className="h-4 w-4" aria-hidden>
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <FilePreview paths={paths} />
      </motion.div>
    </div>
  );
}
