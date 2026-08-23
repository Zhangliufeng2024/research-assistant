import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { isIgnoredTreeName } from "@/lib/artifacts";
import { FilePreview } from "@/components/chat/FilePreview";

interface TreeNode {
  name: string;
  path: string;
  type: "dir" | "file";
  size: number | null;
  mtime: number;
}

type LayerState = "loading" | "error" | TreeNode[];

/** 右侧产出文件 dock（R12 P3/C4）：懒加载目录树 + 行内预览 + 打开所在文件夹。
 *
 * *rootRelPath* 是相对工作区根的产物目录（权威源为 connected 帧）；
 * *refreshKey* 由宿主在回合结束时自增，驱动树免刷新重载。
 */
export function ArtifactsPanel({
  rootRelPath,
  refreshKey,
  emptyRootHint,
  onCollapse,
}: {
  rootRelPath: string | null;
  refreshKey: number;
  /** 根目录缺失时的引导文案（会话页/任务页语境不同）。 */
  emptyRootHint?: React.ReactNode;
  /** 展开态头部渲染收起把手（宿主记忆折叠状态）。 */
  onCollapse?: () => void;
}) {
  const [layers, setLayers] = useState<Record<string, LayerState>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [previewFile, setPreviewFile] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [toast, setToast] = useState("");

  // 根/刷新信号变化：整棵树复位重载
  useEffect(() => {
    setLayers({});
    setExpanded(new Set());
    setPreviewFile(null);
  }, [rootRelPath, refreshKey, reloadTick]);

  const fetchLayer = useCallback(
    (dirRel: string) => {
      setLayers((m) => ({ ...m, [dirRel]: "loading" }));
      api
        .get<{ items: TreeNode[] }>(
          `/api/workspace/tree?path=${encodeURIComponent(dirRel)}`,
        )
        .then((d) =>
          setLayers((m) => ({
            ...m,
            [dirRel]: d.items.filter((it) => !isIgnoredTreeName(it.name)),
          })),
        )
        .catch(() => setLayers((m) => ({ ...m, [dirRel]: "error" })));
    },
    [],
  );

  useEffect(() => {
    if (rootRelPath && !(rootRelPath in layers)) fetchLayer(rootRelPath);
  }, [rootRelPath, layers, fetchLayer]);

  const toggleDir = (node: TreeNode) => {
    const next = new Set(expanded);
    if (next.has(node.path)) {
      next.delete(node.path);
    } else {
      next.add(node.path);
      if (!(node.path in layers)) fetchLayer(node.path);
    }
    setExpanded(next);
  };

  const openFolder = async () => {
    try {
      await api.post(
        `/api/workspace/open?path=${encodeURIComponent(rootRelPath || "")}`,
      );
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "";
      setToast(
        msg.includes("403") || msg.includes("未启用")
          ? "当前运行模式未启用系统打开"
          : "无法打开目录",
      );
    }
  };

  const renderRows = (dirRel: string, depth: number): React.ReactNode => {
    const layer = layers[dirRel];
    if (layer === "loading" || layer === undefined) {
      return (
        <div className="px-3 py-1.5 text-[11.5px] text-ink-3" style={{ paddingLeft: depth * 12 + 12 }}>
          加载中…
        </div>
      );
    }
    if (layer === "error") {
      return (
        <div className="px-3 py-1.5 text-[11.5px] text-danger" style={{ paddingLeft: depth * 12 + 12 }}>
          目录不可读
        </div>
      );
    }
    if (layer.length === 0 && depth === 0) {
      return (
        <div className="px-4 py-6 text-center text-[12px] leading-5 text-ink-3">
          本会话还没有产物。
          <br />
          让助手生成图表或文档后，文件会出现在这里。
        </div>
      );
    }
    return layer.map((node) =>
      node.type === "dir" ? (
        <div key={node.path}>
          <button
            type="button"
            onClick={() => toggleDir(node)}
            className="flex w-full items-center gap-1.5 py-1 pr-2 text-left text-[12px] text-ink transition-colors hover:bg-surface-2"
            style={{ paddingLeft: depth * 12 + 8 }}
            aria-expanded={expanded.has(node.path)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
              strokeLinecap="round" strokeLinejoin="round"
              className={`h-3 w-3 shrink-0 text-ink-3 transition-transform ${expanded.has(node.path) ? "rotate-90" : ""}`}
              aria-hidden>
              <path d="m9 18 6-6-6-6" />
            </svg>
            <span className="truncate">{node.name}</span>
          </button>
          {expanded.has(node.path) && renderRows(node.path, depth + 1)}
        </div>
      ) : (
        <button
          key={node.path}
          type="button"
          onClick={() => setPreviewFile(node.path)}
          className={`flex w-full items-center gap-1.5 py-1 pr-2 text-left text-[12px] transition-colors hover:bg-surface-2 ${
            previewFile === node.path ? "bg-accent-tint text-accent-hover dark:text-accent" : "text-ink-2"
          }`}
          style={{ paddingLeft: depth * 12 + 8 + 14 }}
          title={node.path}
        >
          <span className="truncate font-mono text-[11.5px]">{node.name}</span>
        </button>
      ),
    );
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* 头部 */}
      <div className="flex shrink-0 items-center gap-1 border-b border-edge px-3 py-2">
        {previewFile ? (
          <button
            type="button"
            onClick={() => setPreviewFile(null)}
            className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
            aria-label="返回文件列表"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
              strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5 shrink-0 text-ink-2" aria-hidden>
              <path d="m15 18-6-6 6-6" />
            </svg>
            <span className="truncate font-mono text-[11.5px] text-ink-2">
              {previewFile.split("/").pop()}
            </span>
          </button>
        ) : (
          <span className="min-w-0 flex-1 truncate text-[12px] font-semibold text-ink-2">
            产出文件{rootRelPath ? ` · ${rootRelPath.split("/").slice(1).join("/") || rootRelPath}` : ""}
          </span>
        )}
        {!previewFile && (
          <>
            {onCollapse && (
              <button
                type="button"
                onClick={onCollapse}
                className="rounded-lg p-1.5 text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
                title="收起面板"
                aria-label="收起产出文件面板"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                  strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden>
                  <path d="m9 18 6-6-6-6" />
                </svg>
              </button>
            )}
            <button
              type="button"
              onClick={() => setReloadTick((t) => t + 1)}
              className="rounded-lg p-1.5 text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
              title="刷新"
              aria-label="刷新产物树"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden>
                <path d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6" />
              </svg>
            </button>
            <button
              type="button"
              onClick={() => void openFolder()}
              className="rounded-lg p-1.5 text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
              title="打开所在文件夹"
              aria-label="在系统中打开产物文件夹"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
                strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5" aria-hidden>
                <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
              </svg>
            </button>
          </>
        )}
      </div>

      {/* 内容：行内预览 或 目录树 */}
      {previewFile ? (
        <FilePreview paths={[previewFile]} />
      ) : (
        <div className="min-h-0 flex-1 overflow-auto py-1">
          {!rootRelPath ? (
            <div className="px-4 py-6 text-center text-[12px] leading-5 text-ink-3">
              {emptyRootHint ?? (
                <>
                  本会话还没有产物目录。
                  <br />
                  发送第一条消息后自动创建。
                </>
              )}
            </div>
          ) : (
            renderRows(rootRelPath, 0)
          )}
        </div>
      )}

      {toast && (
        <div className="shrink-0 px-3 pb-2 pt-1 text-center text-[11px] text-ink-3">{toast}</div>
      )}
    </div>
  );
}
