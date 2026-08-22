import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api } from "@/lib/api";
import { Markdown } from "@/components/Markdown";

const IMAGE_EXT = /\.(png|jpe?g|gif|svg|webp)$/i;

type TextPayload = { kind: "text"; content: string; truncated: boolean; size: number };

/** 工作区文件预览弹窗：图片/PDF 内嵌，文本类走 /api/workspace/file JSON 通道。 */
export function FilePreviewModal({
  path,
  onClose,
}: {
  path: string;
  onClose: () => void;
}) {
  const [payload, setPayload] = useState<TextPayload | null>(null);
  const [error, setError] = useState("");
  const fileUrl = `/api/workspace/file?path=${encodeURIComponent(path)}`;
  const isImage = IMAGE_EXT.test(path);
  const isPdf = /\.pdf$/i.test(path);
  const isTextLike = !isImage && !isPdf;

  useEffect(() => {
    if (!isTextLike) return;
    let alive = true;
    setPayload(null);
    setError("");
    api
      .get<TextPayload>(fileUrl)
      .then((d) => {
        if (alive) setPayload(d);
      })
      .catch((e: Error) => {
        if (alive) setError(e.message || "加载失败");
      });
    return () => {
      alive = false;
    };
  }, [fileUrl, isTextLike]);

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

        <div className="min-h-0 flex-1 overflow-auto p-4">
          {error && <div className="text-sm text-danger">{error}</div>}
          {!error && isImage && (
            <img src={fileUrl} alt={path} className="mx-auto max-w-full rounded-xl" />
          )}
          {!error && isPdf && (
            <iframe src={fileUrl} title={path} className="h-[70vh] w-full rounded-xl border border-edge" />
          )}
          {!error && isTextLike && payload && (
            <>
              {path.endsWith(".md") || path.endsWith(".markdown") ? (
                <Markdown>{payload.content}</Markdown>
              ) : (
                <pre className="whitespace-pre-wrap font-mono text-[12.5px] leading-6">
                  {payload.content}
                </pre>
              )}
              {payload.truncated && (
                <div className="mt-3 text-center text-[11px] text-ink-3">
                  —— 内容过长，仅显示头部 ——
                </div>
              )}
            </>
          )}
          {!error && isTextLike && !payload && (
            <div className="py-10 text-center text-sm text-ink-3">加载中…</div>
          )}
        </div>
      </motion.div>
    </div>
  );
}
