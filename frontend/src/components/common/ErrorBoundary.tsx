/* 错误边界（A+ 阶段 1.2）
 *
 * 修复前全库 grep `ErrorBoundary` / `componentDidCatch` 零命中：任一 view 渲染
 * 抛错（典型如后端字段形状变化导致 `items.map is not a function`）会白屏整个
 * 应用，用户只能杀进程重启；15 个 lazy chunk 也没有加载失败兜底——发版后
 * 停留在旧页面的客户端请求已删除的 hash chunk 时，会永久卡在 PageSkeleton。
 *
 * 两层包裹，职责不同：
 *   1. App 层包 <Routes>：单页崩溃不白屏整站，侧栏/顶栏仍可导航逃生；
 *   2. Suspense 内层：chunk 加载失败有明确文案与重载入口。
 *
 * 刻意不做的事：
 *   - 不上报远端——本产品本地优先且 .env 存 API Key，没有遥测通道；
 *   - 不自动重载——静默 reload 会把用户丢回首页并可能再次触发同一错误，
 *     形成刷新循环。把选择权留给用户（「重试」只重置边界，不重载页面）。
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

export interface ErrorBoundaryProps {
  children: ReactNode;
  /** 出现在这个边界内的区域名，用于文案与日志定位。 */
  label?: string;
  /** 自定义降级 UI；不传则用内置卡片。入参含 reset 以便自定义重试入口。 */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /** 便于测试与日志埋点观察捕获行为。 */
  onError?: (error: Error, info: ErrorInfo) => void;
  /**
   * 变化时自动清除错误态（例如传路由 pathname）。
   *
   * 没有它的话，一旦某个页面崩溃，边界会一直显示降级 UI——侧栏虽然还能
   * 点，但 URL 变了、内容区仍卡在错误页，用户只能手动刷新。用 key 重挂
   * 也能达到目的，但会让 Suspense 在正常导航时也闪一次 fallback，故改用
   * componentDidUpdate 里的值比较（不重挂、不闪烁）。
   */
  resetKey?: string | number;
}

interface ErrorBoundaryState {
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 留现场在控制台：用户反馈时可据此附日志。
    console.error(`[ErrorBoundary${this.props.label ? `:${this.props.label}` : ""}]`, error, info);
    this.props.onError?.(error, info);
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps): void {
    // 重置键变化（如用户导航到别的路由）→ 清除错误态，让内容重新渲染。
    if (
      this.state.error !== null &&
      this.props.resetKey !== undefined &&
      this.props.resetKey !== prevProps.resetKey
    ) {
      this.setState({ error: null });
    }
  }

  private reset = (): void => {
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.fallback) return this.props.fallback(error, this.reset);

    const where = this.props.label ?? "此页面";
    return (
      <div
        role="alert"
        className="m-6 rounded-xl border border-danger/30 bg-danger/5 p-5"
      >
        <h2 className="text-[15px] font-medium text-ink">{where}出错了</h2>
        <p className="mt-1.5 text-[13px] leading-6 text-ink-2">
          其余功能不受影响，可从左侧导航继续使用。
        </p>
        <pre className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-2 p-3 text-[12px] leading-5 text-ink-3">
          {error.message || String(error)}
        </pre>
        <div className="mt-4 flex gap-2.5">
          <button
            type="button"
            onClick={this.reset}
            className="rounded-xl border border-edge bg-surface px-4 py-2 text-[13px] font-medium transition-colors hover:bg-surface-2"
          >
            重试
          </button>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="rounded-xl bg-accent px-4 py-2 text-[13px] font-medium text-white transition-colors hover:bg-accent-hover"
          >
            重新加载应用
          </button>
        </div>
      </div>
    );
  }
}
