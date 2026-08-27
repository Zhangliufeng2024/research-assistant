/* 路由级骨架屏（R15）：Suspense fallback，lazy chunk 加载期占位。
 *
 * 形似典型页面布局（顶条 + 统计卡行 + 两栏内容块），全部用主题令牌色
 * （surface-2）做脉冲动画，浅/深主题自适应；不依赖任何业务数据。
 */
export function PageSkeleton() {
  return (
    <div aria-hidden className="mx-auto max-w-6xl animate-pulse space-y-5 px-6 py-6">
      {/* 页头 */}
      <div className="space-y-2.5">
        <div className="h-3 w-28 rounded-full bg-surface-2" />
        <div className="h-6 w-72 rounded-lg bg-surface-2" />
      </div>

      {/* 统计卡行 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="rounded-2xl border border-edge/60 bg-surface p-4 shadow-card">
            <div className="h-2.5 w-16 rounded-full bg-surface-2" />
            <div className="mt-2.5 h-6 w-12 rounded-md bg-surface-2" />
          </div>
        ))}
      </div>

      {/* 内容区：宽栏 + 窄栏 */}
      <div className="grid gap-5 xl:grid-cols-[1.35fr_1fr]">
        <div className="space-y-3">
          <div className="h-24 rounded-2xl border border-edge/60 bg-surface shadow-card" />
          <div className="h-40 rounded-2xl border border-edge/60 bg-surface shadow-card" />
        </div>
        <div className="space-y-3">
          <div className="h-32 rounded-2xl border border-edge/60 bg-surface shadow-card" />
          <div className="h-20 rounded-2xl border border-edge/60 bg-surface shadow-card" />
        </div>
      </div>
    </div>
  );
}
