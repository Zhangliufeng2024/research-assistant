import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { WorkspaceInfo } from "@/lib/types";

/**
 * 更换工作目录（R8 反馈 #1，Claude Desktop 式）：
 * - 桌面壳内优先走原生选夹（pywebview js_api → DesktopBridge.select_folder）；
 * - 桥不可用（浏览器直连 / 注入竞态）时降级为手动输入绝对路径；
 * - 确认后 POST /api/workspace/root 运行时切换（os.chdir + app.state 刷新）。
 */

const inputCls =
  "w-full rounded-xl border border-edge bg-canvas px-3 py-2 text-[13px] font-mono outline-none transition-colors placeholder:text-ink-3 placeholder:font-sans focus:border-accent/60";

export function WorkspaceModal({
  info,
  onClose,
  onSwitched,
}: {
  info: WorkspaceInfo;
  onClose: () => void;
  /** 切换成功回调：父组件负责刷新工作区名片 + 会话列表 + 轻提示。 */
  onSwitched: (next: WorkspaceInfo) => void;
}) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [nativeOk, setNativeOk] = useState(false);

  useEffect(() => {
    // pywebview 对象是窗口加载后异步注入的：立即探测一次，
    // 未就绪则监听官方 ready 事件补探测。
    const w = window;
    if (w.pywebview?.api?.select_folder) {
      setNativeOk(true);
      return;
    }
    const onReady = () => setNativeOk(!!w.pywebview?.api?.select_folder);
    window.addEventListener("pywebviewready", onReady);
    return () => window.removeEventListener("pywebviewready", onReady);
  }, []);

  async function doSwitch(p: string) {
    const trimmed = p.trim();
    if (!trimmed || busy) return;
    setError("");
    setBusy(true);
    try {
      await api.post<{ ok: boolean; root: string }>("/api/workspace/root", {
        path: trimmed,
      });
      // 名片以服务端最新状态为准重新拉取
      const next = await api.get<WorkspaceInfo>("/api/workspace");
      onSwitched(next);
    } catch (e) {
      setError((e as Error).message || "切换失败");
    } finally {
      setBusy(false);
    }
  }

  async function pickNative() {
    try {
      const chosen = (await window.pywebview?.api?.select_folder("选择工作目录")) ?? "";
      if (chosen) void doSwitch(chosen);
    } catch {
      setError("无法打开系统文件夹选择器，请手动输入路径");
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-edge bg-surface shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-edge px-5 py-3.5">
          <h2 className="text-[14.5px] font-semibold">更换工作目录</h2>
          <p className="mt-0.5 text-[12px] text-ink-3">
            会话产物与文件操作都发生在这里；不更换也能正常对话。
          </p>
        </div>

        <div className="space-y-4 px-5 py-4">
          <div className="rounded-xl bg-surface-2 px-3.5 py-2.5 text-[12.5px]">
            <div className="text-ink-3">当前</div>
            <div className="mt-0.5 truncate font-mono" title={info.root}>
              {info.root}
            </div>
          </div>

          {nativeOk ? (
            <button
              type="button"
              onClick={() => void pickNative()}
              disabled={busy}
              className="w-full rounded-xl border border-edge bg-canvas px-4 py-2.5 text-[13px] font-medium transition-colors hover:bg-surface-2 disabled:opacity-50"
            >
              📁 选择文件夹…（系统对话框）
            </button>
          ) : null}

          <div>
            <span className="mb-1.5 block text-[12px] text-ink-2">
              或直接输入绝对路径
            </span>
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void doSwitch(path);
              }}
              placeholder="D:\\papers\\我的研究"
              className={inputCls}
            />
          </div>

          {error && (
            <div className="rounded-xl bg-danger/10 px-3.5 py-2.5 text-[12.5px] text-danger">
              ✗ {error}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2.5 border-t border-edge px-5 py-3.5">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-xl border border-edge bg-surface px-4 py-2 text-[13px] font-medium transition-colors hover:bg-surface-2 disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => void doSwitch(path)}
            disabled={busy || !path.trim()}
            className="rounded-xl bg-accent px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
          >
            {busy ? "切换中…" : "切换"}
          </button>
        </div>
      </div>
    </div>
  );
}
