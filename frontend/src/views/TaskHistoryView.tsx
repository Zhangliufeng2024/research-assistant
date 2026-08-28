/* 迭代2：任务中心 · 历史分区页。
 * 大字号检索面板（20/页）覆盖全部运行记录；总数统计条置顶。 */
import { useEffect } from "react";
import { useTaskStore } from "@/stores/taskStore";
import { RunSearchPanel } from "@/components/tasks/taskPieces";

export function TaskHistoryView() {
  const observe = useTaskStore((s) => s.observe);

  useEffect(() => {
    document.title = "研究助手 · 运行历史";
  }, []);

  function observeTask(taskId: string) {
    void observe(taskId).catch(() => {});
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4 p-5">
      <div>
        <div className="text-[10px] uppercase tracking-widest text-accent">History</div>
        <h1 className="mt-1 text-lg font-semibold">运行历史</h1>
        <p className="mt-0.5 text-[12px] text-ink-3">
          全部后台运行的标题检索与状态过滤；带「来源对话」标记的任务可回跳到派生它的会话。
        </p>
      </div>
      <RunSearchPanel onObserve={observeTask} pageSize={20} />
    </div>
  );
}
