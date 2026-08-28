/* 迭代2：任务中心 · 看板分区页。
 * 全量任务按状态四列铺开（每列上限 24，超出用下方检索定位），
 * 检索面板兜底精确定位。observe 复用 taskStore 的耐久通道。 */
import { useEffect } from "react";
import { useTaskStore } from "@/stores/taskStore";
import { KanbanBoard, RunSearchPanel } from "@/components/tasks/taskPieces";

export function TaskBoardView() {
  const durableTasks = useTaskStore((s) => s.durableTasks);
  const refreshDurableTasks = useTaskStore((s) => s.refreshDurableTasks);
  const observe = useTaskStore((s) => s.observe);

  useEffect(() => {
    document.title = "研究助手 · 任务看板";
    refreshDurableTasks().catch(() => {});
  }, [refreshDurableTasks]);

  function observeTask(taskId: string) {
    void observe(taskId).catch(() => {});
  }

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-5">
      <div>
        <div className="text-[10px] uppercase tracking-widest text-accent">Board</div>
        <h1 className="mt-1 text-lg font-semibold">任务看板</h1>
        <p className="mt-0.5 text-[12px] text-ink-3">
          按状态浏览全部后台任务；运行中的任务点「观察」接入实时通道。
        </p>
      </div>
      <KanbanBoard
        tasks={durableTasks}
        onObserve={observeTask}
        perColumn={24}
      />
      <RunSearchPanel onObserve={observeTask} pageSize={10} />
    </div>
  );
}
