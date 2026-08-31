"""In-process background task hub with durable event replay."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from ..workflows.registry import get_workflow_registry
from .platform_store import PlatformStore

RunnerFactory = Callable[["TaskHandle"], AsyncIterator[dict[str, Any]]]

PAPER_WORKFLOW = [
    step.to_task_step()
    for step in get_workflow_registry().get_workflow("paper").steps
]


def _step_for_frame(frame: dict[str, Any]) -> str | None:
    """Normalize existing pipeline progress names into DAG node ids."""
    details = frame.get("details")
    if isinstance(details, dict) and details.get("step_id"):
        return str(details["step_id"])
    stage = str(frame.get("stage") or "").lower()
    if stage in {"planning", "plan"}:
        return "plan"
    if stage in {"research_figures", "research"}:
        return "research"
    if stage in {"writing", "assemble"}:
        return "assemble"
    if stage in {"finalization", "finalize"}:
        return "finalize"
    return stage if stage in {"figures", "gates"} else None


def _advance_steps(store: PlatformStore, conn: Any, task_id: str, current: str) -> None:
    """Close nodes whose phase is complete when the next phase starts.

    连接级操作（P2-2）：conn 由 _persist_frame 的单事务上下文提供，
    避免每个 step 更新各自建连。
    """
    order = ["plan", "research", "figures", "assemble", "gates", "finalize"]
    if current not in order:
        return
    current_index = order.index(current)
    steps = {s["id"]: s for s in store._list_steps_conn(conn, task_id)}
    # Research and figures are parallel branches and both close at assemble.
    close_before = {"assemble": {"research", "figures"}, "gates": {"assemble"}, "finalize": {"gates"}}.get(current)
    if close_before is None:
        close_before = set(order[:current_index])
    for step_id in close_before:
        if steps.get(step_id, {}).get("status") in {"pending", "running"}:
            store._update_step_conn(conn, task_id, step_id, status="done")


@dataclass
class TaskHandle:
    task_id: str
    query: str
    project_id: str
    #: 工程债（帧级建连合并）：start() 创建线程/回合时即缓存到句柄，
    #: _drive 逐帧持久化不再 get_task 读 metadata（一帧少一次建连）。
    thread_id: str | None = None
    turn_id: str | None = None
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    approvals: asyncio.Queue = field(default_factory=asyncio.Queue)
    steers: asyncio.Queue = field(default_factory=asyncio.Queue)
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    status: str = "queued"
    approval_request_id: str = ""
    task: asyncio.Task | None = None


class BackgroundTaskHub:
    """Own task execution independently from any browser connection."""

    def __init__(self, store: PlatformStore) -> None:
        self.store = store
        self.handles: dict[str, TaskHandle] = {}

    def start(
        self,
        *,
        project_id: str,
        query: str,
        mode: str,
        runner_factory: RunnerFactory,
        output_dir: str | None = None,
        metadata: dict[str, Any] | None = None,
        steps: list[dict[str, Any]] | None = None,
        source_session_id: str | None = None,
    ) -> TaskHandle:
        task_id = uuid.uuid4().hex[:12]
        handle = TaskHandle(task_id=task_id, query=query, project_id=project_id)
        self.handles[task_id] = handle
        task_metadata = dict(metadata or {})
        self.store.create_task(
            task_id=task_id, project_id=project_id, query=query, mode=mode,
            output_dir=output_dir, metadata=task_metadata,
            source_session_id=source_session_id,
        )
        # Every durable task is also a reproducibility run.  Keeping the run id
        # in task metadata makes task → artifact → evidence navigation possible
        # without changing the existing task API shape.
        research_run = self.store.create_research_run(
            project_id=project_id, task_id=task_id,
            workflow_id=str(task_metadata.get("workflow_id") or mode),
            inputs={"query": query, "mode": mode},
        )
        self.store.add_provenance_edge(
            project_id=project_id, from_type="task", from_id=task_id,
            to_type="research_run", to_id=research_run["id"], relation="executed_as",
        )
        # Compatibility bridge: every durable task is represented in the
        # unified Thread/Turn/Item model as well.  Legacy task APIs remain the
        # execution source of truth during the migration period.
        thread = self.store.create_thread(
            project_id=project_id, title=query[:120], kind="task",
            source_task_id=task_id, metadata={"workflow_id": task_metadata.get("workflow_id"), "legacy_task_id": task_id},
        )
        turn = self.store.create_turn(thread_id=thread["id"], project_id=project_id, user_input=query, metadata={"task_id": task_id})
        handle.thread_id = thread["id"]
        handle.turn_id = turn["id"]
        task_metadata["thread_id"] = thread["id"]
        task_metadata["turn_id"] = turn["id"]
        task_metadata["research_run_id"] = research_run["id"]
        self.store.update_task(task_id, metadata=task_metadata)
        self.store.create_steps(task_id, steps or [])
        handle.task = asyncio.create_task(self._drive(handle, runner_factory))
        return handle

    async def _drive(self, handle: TaskHandle, runner_factory: RunnerFactory) -> None:
        handle.status = "running"
        self.store.update_task(handle.task_id, status="running")
        latest_usage: dict[str, Any] = {}
        try:
            async for frame in runner_factory(handle):
                if frame.get("type") == "usage" and isinstance(frame.get("budget"), dict):
                    latest_usage = dict(frame["budget"])
                if frame.get("type") == "result" and frame.get("status") == "failed":
                    handle.status = "failed"
                # 工程债：帧级副作用（step 状态/agent_run/thread item/event）
                # 合并为一次建连一个事务；旧实现一帧最多 4 次建连。
                seq = await asyncio.to_thread(self._persist_frame_full, handle, frame)
                message = {**frame, "seq": seq}
                for queue in tuple(handle.subscribers):
                    if queue.full():
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass  # 控制流：腾位与消费方之间的极窄竞态
                    queue.put_nowait(message)
            if handle.cancel_event.is_set():
                handle.status = "cancelled"
            elif handle.status != "failed":
                handle.status = "complete"
        except asyncio.CancelledError:
            handle.status = "cancelled"
            raise
        except Exception as exc:
            handle.status = "failed"
            self.store.update_task(handle.task_id, error=str(exc))
            await self.publish(handle.task_id, {"type": "error", "message": str(exc)})
        finally:
            self.store.update_task(handle.task_id, status=handle.status)
            task_record = self.store.get_task(handle.task_id) or {}
            run_id = (task_record.get("metadata") or {}).get("research_run_id")
            if run_id:
                self.store.finish_research_run(
                    str(run_id), status=handle.status,
                    outputs={"output_dir": task_record.get("output_dir"), "usage": latest_usage},
                )
            output_dir = task_record.get("output_dir")
            if output_dir and handle.status in {"complete", "failed"}:
                # Turn the filesystem result into reviewable, hash-addressed
                # artifact rows without moving or copying user files.
                self.store.index_task_artifacts(
                    project_id=handle.project_id, output_dir=str(output_dir),
                    task_id=handle.task_id, run_id=str(run_id) if run_id else None,
                    thread_id=str((task_record.get("metadata") or {}).get("thread_id") or "") or None,
                )
            self.store.create_notification(
                project_id=handle.project_id,
                kind="task_complete" if handle.status == "complete" else "task_failed" if handle.status == "failed" else "task_stopped",
                title="研究任务已完成" if handle.status == "complete" else "研究任务需要关注",
                message=f"{handle.query[:160]} · 状态：{handle.status}",
                object_type="task", object_id=handle.task_id,
            )
            if (task_record.get("metadata") or {}).get("turn_id"):
                self.store.finish_turn(str(task_record["metadata"]["turn_id"]), status="complete" if handle.status == "complete" else handle.status, error=str(task_record.get("error") or ""))
            if handle.status == "complete":
                for step in self.store.list_steps(handle.task_id):
                    if step["status"] in {"pending", "running"}:
                        self.store.update_step(handle.task_id, step["id"], status="done")
            if handle.status in {"failed", "cancelled"}:
                for step in self.store.list_steps(handle.task_id):
                    if step["status"] == "running":
                        self.store.update_step(handle.task_id, step["id"], status=handle.status)
            await self.publish(
                handle.task_id,
                {"type": "done", "status": handle.status, "task_id": handle.task_id},
            )
            # 释放 handle（A+ 阶段 1 / C-1：确定性内存泄漏修复）。
            #
            # 位置很关键：必须在**最后一次 publish 之后**。publish 靠
            # self.handles.get(task_id) 找订阅者，提前摘除会让终端的 done 帧
            # 发不出去，前端就永远等不到任务结束。
            #
            # 终态之后 handle 已无用途：stop/steer/approve 都会先检查
            # status not in {"queued","running"} 再返回 False；subscribe /
            # unsubscribe 对 handle is None 有兜底（从 store 回放事件）。
            # 因此摘除不影响任何既有行为，只是不再让每个已完成任务都常驻
            # 一份（subscribers set + 两个队列 + Task 引用）。
            self.handles.pop(handle.task_id, None)

    async def publish(self, task_id: str, frame: dict[str, Any]) -> None:
        seq = await asyncio.to_thread(self._persist_frame, task_id, frame)
        message = {**frame, "seq": seq}
        handle = self.handles.get(task_id)
        if handle is None:
            return
        for queue in tuple(handle.subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass  # 控制流：腾位与消费方之间的极窄竞态，直接落入下方 put_nowait
            queue.put_nowait(message)

    def _persist_frame(self, task_id: str, frame: dict[str, Any]) -> int:
        """Persist one frame off the event loop; callers retain ordering.

        P2-2：整帧的 step 读取/更新与 event 追加合并为**一次建连、一个事务**
        （旧实现逐操作 _connect()，一帧最多 4-5 次建连）。退出时统一 commit，
        任一环节异常则整体回滚——帧持久化要么完整生效、要么不生效。
        """
        step_id = _step_for_frame(frame)
        with self.store.transaction() as conn:
            if step_id:
                details = frame.get("details")
                explicit_status = details.get("status") if isinstance(details, dict) else None
                known_steps = {step["id"] for step in self.store._list_steps_conn(conn, task_id)}
                if step_id in known_steps and explicit_status in {
                    "resumed", "done", "failed", "cancelled", "skipped"
                }:
                    self.store._update_step_conn(
                        conn, task_id, step_id,
                        status="done" if explicit_status == "resumed" else explicit_status,
                    )
                elif step_id in known_steps:
                    _advance_steps(self.store, conn, task_id, step_id)
                    self.store._update_step_conn(conn, task_id, step_id, status="running")
            return self.store._append_event_conn(conn, task_id, frame)

    def _persist_frame_full(self, handle: TaskHandle, frame: dict[str, Any]) -> int:
        """一帧一次建连/一个事务：step 状态 + agent_run + thread item + event。

        ``_persist_frame`` 只处理 step + event（供 publish/测试），本方法是
        _drive 热路径的完整版——把原逐帧分散的 get_task/update_agent_run/
        append_agent_item/append_event 合并进同一事务。行为与原实现逐分支
        等价（见 _drive 的旧代码），异常时整体回滚。
        """
        task_id = handle.task_id
        step_id = _step_for_frame(frame)
        with self.store.transaction() as conn:
            if step_id:
                details = frame.get("details")
                explicit_status = (
                    details.get("status") if isinstance(details, dict) else None
                )
                known_steps = {
                    step["id"] for step in self.store._list_steps_conn(conn, task_id)
                }
                if step_id in known_steps and explicit_status in {
                    "resumed", "done", "failed", "cancelled", "skipped",
                }:
                    self.store._update_step_conn(
                        conn, task_id, step_id,
                        status="done" if explicit_status == "resumed" else explicit_status,
                    )
                elif step_id in known_steps:
                    _advance_steps(self.store, conn, task_id, step_id)
                    self.store._update_step_conn(conn, task_id, step_id, status="running")
            ftype = frame.get("type")
            agent_id = frame.get("agent_id")
            if agent_id and ftype == "usage" and isinstance(frame.get("budget"), dict):
                self.store._update_agent_run_conn(
                    conn, task_id, str(agent_id), budget=dict(frame["budget"]),
                )
            elif agent_id and ftype == "agent_status":
                self.store._update_agent_run_conn(
                    conn, task_id, str(agent_id),
                    status=str(frame.get("status") or "pending"),
                    role=str(frame.get("role") or "") or None,
                )
            if ftype != "usage" and handle.thread_id:
                self.store._append_agent_item_conn(
                    conn, thread_id=handle.thread_id, project_id=handle.project_id,
                    turn_id=handle.turn_id, item_type=str(ftype or "event"),
                    title=str(frame.get("stage") or ftype or ""),
                    content=frame,
                    status="error" if ftype == "error" else "complete",
                )
            return self.store._append_event_conn(conn, task_id, frame)

    def subscribe(self, task_id: str, after: int = 0) -> asyncio.Queue | None:
        if self.store.get_task(task_id) is None:
            return None
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        handle = self.handles.get(task_id)
        if handle is not None:
            handle.subscribers.add(queue)
        for event in self.store.read_events(task_id, after=after):
            if queue.full():
                break
            queue.put_nowait(event)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        handle = self.handles.get(task_id)
        if handle is not None:
            handle.subscribers.discard(queue)

    def stop(self, task_id: str) -> bool:
        handle = self.handles.get(task_id)
        if handle is None or handle.status not in {"queued", "running"}:
            return False
        handle.status = "stopping"
        handle.cancel_event.set()
        handle.approvals.put_nowait(None)
        self.store.update_task(task_id, status="stopping")
        return True

    def steer(self, task_id: str, message: str) -> bool:
        handle = self.handles.get(task_id)
        if handle is None or handle.status not in {"queued", "running"}:
            return False
        handle.steers.put_nowait(message)
        return True

    def approve(self, task_id: str, approved: bool, request_id: str | None = None, note: str = "") -> bool:
        handle = self.handles.get(task_id)
        if handle is None or handle.status not in {"queued", "running"}:
            return False
        if request_id and request_id != handle.approval_request_id:
            return False
        if request_id:
            self.store.resolve_agent_approval(request_id, handle.project_id, approved=approved, note=note)
        handle.approval_request_id = ""
        handle.approvals.put_nowait(bool(approved))
        return True

    def live_task(self, task_id: str) -> TaskHandle | None:
        return self.handles.get(task_id)
