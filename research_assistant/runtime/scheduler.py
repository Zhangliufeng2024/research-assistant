"""Durable queue worker primitives used by desktop and headless runners.

The scheduler is intentionally transport-neutral: WebSocket connections may
come and go, while a worker can keep claiming persisted jobs and recover leases
after a crash.  Hosts register a dispatcher per workflow; dispatchers are
async callables receiving the queue row.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .platform_store import PlatformStore

Dispatcher = Callable[[dict[str, Any]], Awaitable[None]]

#: stop(drain=False) 搁置的流水线任务注册表（模块级）。asyncio 对 Task 仅持
#: 弱引用，而搁置场景（工作区切换）会让旧调度器实例立即不可达——强引用必须
#: 挂在比实例更长寿的位置，否则被搁置的生成任务可能在任意 GC 轮被静默取消。
_DETACHED_TASKS: set[asyncio.Task] = set()


def _prune_detached() -> None:
    """清理已完成的搁置任务，防模块级集合无界增长。"""
    _DETACHED_TASKS.difference_update(t for t in list(_DETACHED_TASKS) if t.done())


class DurableScheduler:
    def __init__(self, store: PlatformStore, *, worker_id: str | None = None,
                 poll_seconds: float = 2.0, max_concurrency: int | None = None,
                 janitor_cwd: Path | None = None) -> None:
        self.store = store
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.poll_seconds = max(0.25, float(poll_seconds))
        # R17 Janitor：分层生命周期清理，挂调度器周期触发（默认每小时，
        # RA_JANITOR_INTERVAL_SECONDS 可调，0 = 关闭）。
        self.janitor_cwd = janitor_cwd
        try:
            self.janitor_interval = float(os.getenv("RA_JANITOR_INTERVAL_SECONDS", "3600"))
        except ValueError:
            self.janitor_interval = 3600.0
        self._janitor_last = 0.0
        configured = max_concurrency
        if configured is None:
            try:
                configured = int(os.getenv("RA_SCHEDULER_CONCURRENCY", "2"))
            except ValueError:
                configured = 2
        self.max_concurrency = max(1, min(int(configured), 16))
        self.dispatchers: dict[str, Dispatcher] = {}
        self._stop = asyncio.Event()
        self._drain = True
        self._task: asyncio.Task | None = None
        self._active: set[asyncio.Task] = set()
        try:
            self.max_per_resource = max(1, min(int(os.getenv("RA_PROVIDER_CONCURRENCY", "2")), 16))
        except ValueError:
            self.max_per_resource = 2

    def register(self, workflow_id: str, dispatcher: Dispatcher) -> None:
        self.dispatchers[str(workflow_id)] = dispatcher

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._drain = True
            self._task = asyncio.create_task(self.run())

    async def stop(self, *, drain: bool = True) -> None:
        """停止调度器。

        - ``drain=True``（默认）：等待全部已派发流水线收尾后再返回（原行为）。
        - ``drain=False``：仅通知轮询循环退出、跳过排空。工作区切换等场景
          用它避免 HTTP 请求被数小时的生成任务阻塞；活跃任务持有旧
          store/hub 的绝对路径引用可自然跑完并照常落库，只是本实例不再
          claim 新作业。未完成任务转存到模块级 ``_DETACHED_TASKS`` 保住引用
          （实例本身在切换后可能立即不可达，不能作为引用锚点）。
        """
        self._drain = bool(drain)
        self._stop.set()
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if drain:
            if self._active:
                await asyncio.gather(*self._active, return_exceptions=True)
            self._active.clear()
        else:
            self._park_active()

    def _park_active(self) -> None:
        """不排空退出：把未完成活跃任务转存模块级注册表防 GC 丢引用。

        引用必须挂在比实例更长寿的位置：工作区切换会立刻重绑
        ``app.state.scheduler``，旧实例随之不可达——若停靠集合挂在实例上，
        被搁置的流水线恰好失去保护（asyncio 对 Task 仅持弱引用）。
        """
        _DETACHED_TASKS.update(task for task in self._active if not task.done())
        _prune_detached()
        self._active.clear()

    async def run(self) -> None:
        while not self._stop.is_set():
            self._active = {task for task in self._active if not task.done()}
            _prune_detached()
            await asyncio.to_thread(self.store.release_due_triggers)
            await asyncio.to_thread(self.store.recover_expired_jobs)
            await asyncio.to_thread(self.store.recover_expired_resource_leases)
            await self._maybe_run_janitor()
            while len(self._active) < self.max_concurrency:
                job = await asyncio.to_thread(self.store.claim_job, worker_id=self.worker_id)
                if job is None:
                    break
                task = asyncio.create_task(self._run_claimed(job))
                self._active.add(task)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass
        # 循环退出收尾：drain=True 等待全部活跃流水线；drain=False 转存引用
        # 后立即返回，由 stop(drain=False) 的调用方语义决定不等待。
        if self._drain:
            if self._active:
                await asyncio.gather(*self._active, return_exceptions=True)
            self._active.clear()
        else:
            self._park_active()

    async def _maybe_run_janitor(self) -> None:
        """按间隔触发 Janitor（独立 try：清理失败绝不影响调度主循环）。"""
        if self.janitor_cwd is None or self.janitor_interval <= 0:
            return
        now = asyncio.get_running_loop().time()
        if now - self._janitor_last < self.janitor_interval:
            return
        self._janitor_last = now
        try:
            from .janitor import run_janitor

            await asyncio.to_thread(run_janitor, self.janitor_cwd, self.store)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("ra.runtime.scheduler").exception("janitor 执行失败")

    async def tick(self) -> bool:
        await asyncio.to_thread(self.store.release_due_triggers)
        await asyncio.to_thread(self.store.recover_expired_jobs)
        await asyncio.to_thread(self.store.recover_expired_resource_leases)
        job = await asyncio.to_thread(self.store.claim_job, worker_id=self.worker_id)
        if job is None:
            return False
        await self._run_claimed(job)
        return True

    async def _run_claimed(self, job: dict[str, Any]) -> None:
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        resource = str(job.get("resource_key") or payload.get("provider") or payload.get("model") or "default")
        lease = await asyncio.to_thread(
            self.store.acquire_resource_lease,
            resource_key=resource, worker_id=self.worker_id, job_id=str(job["id"]),
            max_slots=self.max_per_resource,
        )
        if lease is None:
            # Resource contention is back-pressure, not a failed attempt. Put
            # the job back without consuming retry budget so a busy provider
            # cannot make otherwise healthy work terminally fail.
            await asyncio.to_thread(
                self.store.defer_job, job["id"], delay=2.0,
                reason=f"资源 {resource} 达到并发上限，等待空闲槽位",
            )
            return
        # 任务租约长度取 claim 时记录值（旧数据回退 300s）；心跳节奏取
        # min(lease/3, 60s)，保证连续错过两次心跳也不会在轮询周期被回收。
        # 下限仅防脏数据导致忙转：实际租约写入时 store 会自行抬到 ≥10s。
        lease_seconds = float(payload.get("_lease_seconds") or 300.0)
        renew_interval = min(max(lease_seconds / 3.0, 0.1), 60.0)
        lease_lost = asyncio.Event()

        async def renew() -> None:
            try:
                while True:
                    await asyncio.sleep(renew_interval)
                    job_ok = await asyncio.to_thread(
                        self.store.renew_job_lease, str(job["id"]),
                        worker_id=self.worker_id, lease_seconds=lease_seconds,
                    )
                    resource_ok = await asyncio.to_thread(
                        self.store.renew_resource_lease, lease["id"],
                    )
                    if not job_ok or not resource_ok:
                        # 租约丢失：作业已被回收（可能被其它 worker 重领）。
                        lease_lost.set()
                        return
            except asyncio.CancelledError:
                return

        lease_renewer = asyncio.create_task(renew())
        lost_watcher = asyncio.create_task(lease_lost.wait())
        dispatcher = self.dispatchers.get(str(job.get("workflow_id")))
        runner: asyncio.Task | None = None
        try:
            if dispatcher is None:
                await asyncio.to_thread(self.store.fail_job, job["id"], error=f"未注册工作流执行器: {job.get('workflow_id')}")
                return
            runner = asyncio.create_task(dispatcher(job))
            done, _pending = await asyncio.wait(
                {runner, lost_watcher}, return_when=asyncio.FIRST_COMPLETED,
            )
            if runner not in done:
                # 失去租约：取消本地执行并直接返回 —— 作业所有权已易主，
                # 绝不把旧结果写回队列（complete/fail 均不调用）。
                runner.cancel()
                await asyncio.gather(runner, return_exceptions=True)
                return
            exc = runner.exception()
            if exc is not None:
                await asyncio.to_thread(self.store.fail_job, job["id"], error=str(exc))
            else:
                await asyncio.to_thread(self.store.complete_job, job["id"])
        finally:
            for task in (lost_watcher, lease_renewer):
                task.cancel()
            await asyncio.gather(lost_watcher, lease_renewer, return_exceptions=True)
            await asyncio.to_thread(self.store.release_resource_lease, lease["id"])
