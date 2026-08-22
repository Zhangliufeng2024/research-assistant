/** 过渡占位视图：各路由的真实实现分别在 P3/P4 阶段落位。 */
export default function Placeholder({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-sm rounded-2xl border border-edge bg-surface p-10 text-center shadow-card">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-accent-tint text-xl text-accent">
          ✦
        </div>
        <h1 className="text-lg font-semibold">{title}</h1>
        <p className="mt-1.5 text-sm text-ink-2">{desc}</p>
      </div>
    </div>
  );
}
