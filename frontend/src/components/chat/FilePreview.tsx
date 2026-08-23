import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Markdown } from "@/components/Markdown";

const IMAGE_EXT = /\.(png|jpe?g|gif|svg|webp)$/i;

type TextPayload = { kind: "text"; content: string; truncated: boolean; size: number };

/** 行内文件预览主体（R12 P3/C2 从 FilePreviewModal 抽出）：
 * 图片/PDF 内嵌，文本类走 /api/workspace/file JSON 通道。
 * *paths* 是候选路径序列（candidatePreviewPaths 的产物，anchor 优先）：
 * 文本加载失败或图片 404 时自动尝试下一条，全部失败才报错。
 * 弹窗（FilePreviewModal）与右侧产出 dock（ArtifactsPanel）共用。 */
export function FilePreview({ paths }: { paths: string[] }) {
  const key = paths.join("\n");
  const [idx, setIdx] = useState(0);
  const [payload, setPayload] = useState<TextPayload | null>(null);
  const [error, setError] = useState("");

  // 候选序列变化：从头尝试
  useEffect(() => {
    setIdx(0);
    setPayload(null);
    setError("");
  }, [key]);

  const path = paths[Math.min(idx, Math.max(paths.length - 1, 0))] ?? "";
  const fileUrl = `/api/workspace/file?path=${encodeURIComponent(path)}`;
  const isImage = IMAGE_EXT.test(path);
  const isPdf = /\.pdf$/i.test(path);
  const isTextLike = !isImage && !isPdf;
  const hasMore = idx + 1 < paths.length;

  /** 当前候选不可用：前进到下一条；耗尽则落错误态。 */
  const advance = (msg: string) => {
    if (hasMore) {
      setIdx(idx + 1);
      setPayload(null);
      setError("");
    } else {
      setError(msg || "加载失败");
    }
  };

  useEffect(() => {
    if (!path || !isTextLike) return;
    let alive = true;
    setPayload(null);
    setError("");
    api
      .get<TextPayload>(fileUrl)
      .then((d) => {
        if (alive) setPayload(d);
      })
      .catch((e: Error) => {
        if (!alive) return;
        advance(e.message || "加载失败");
      });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileUrl, isTextLike]);

  if (!path) {
    return <div className="min-h-0 flex-1 overflow-auto p-4 text-sm text-danger">没有可预览的路径</div>;
  }

  return (
    <div className="min-h-0 flex-1 overflow-auto p-4">
      {error && <div className="text-sm text-danger">{error}</div>}
      {!error && isImage && (
        <img
          src={fileUrl}
          alt={path}
          className="mx-auto max-w-full rounded-xl"
          onError={() => advance("图片加载失败")}
        />
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
  );
}
