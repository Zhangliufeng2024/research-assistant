"""任务租约生命周期回归测试（缺陷群 A/B/C/D）。

背景：job 租约此前从不续期，超过 lease_seconds 的作业会被
recover_expired_jobs 翻回 queued 并被重复派发；complete/fail 也缺归属校验。
本文件用真实 PlatformStore（小租约 + 直接改库模拟到期）与桩 store 两类手法：
- 真库验证 SQL 层语义（回收、续期、写回守卫、毒丸封顶）；
- 桩 store 把续约心跳压到亚秒级，验证调度器的续期与「租约丢失即中止」。
"""

import asyncio
import sqlite3
import time

from research_assistant.runtime import DurableScheduler, PlatformStore
from research_assistant.runtime.scheduler import _DETACHED_TASKS


def _expire_all_leases(db_path, seconds_ago: float = 1.0) -> None:
    """把所有 job 租约拨到过去，模拟 worker 失联后租约到期。"""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE job_queue SET lease_until = ?", (time.time() - seconds_ago,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Store 层：回收 / 续期 / 写回守卫 / 毒丸封顶
# ---------------------------------------------------------------------------

def test_expired_running_job_recovers_to_queued(tmp_path):
    db = tmp_path / ".ra" / "platform.sqlite3"
    store = PlatformStore(db)
    project = store.ensure_project(tmp_path)
    store.enqueue_job(project_id=project["id"], workflow_id="single")

    claimed = store.claim_job(worker_id="w1", lease_seconds=10)
    assert claimed and claimed["status"] == "running"
    assert store.recover_expired_jobs() == 0  # 租约未到期不回收

    _expire_all_leases(db)
    assert store.recover_expired_jobs() == 1
    row = store.list_jobs(project["id"])[0]
    assert row["status"] == "queued"
    assert row["lease_until"] is None
    # 到期回收不消耗尝试次数以外的预算：attempts 保持领取时加过的 1
    assert row["attempts"] == 1


def test_renew_job_lease_extends_and_checks_owner(tmp_path):
    db = tmp_path / ".ra" / "platform.sqlite3"
    store = PlatformStore(db)
    project = store.ensure_project(tmp_path)
    job = store.enqueue_job(project_id=project["id"], workflow_id="single")
    claimed = store.claim_job(worker_id="w1", lease_seconds=10)
    assert claimed

    # 错误的 worker 不能续别人的租约
    assert store.renew_job_lease(job["id"], worker_id="w2", lease_seconds=10) is False
    assert store.renew_job_lease(job["id"], worker_id="w1", lease_seconds=10) is True
    row = store.list_jobs(project["id"])[0]
    assert row["lease_until"] > time.time()

    # 非 running 状态不可续期（先过期回收翻回 queued）
    _expire_all_leases(db)
    store.recover_expired_jobs()
    assert store.renew_job_lease(job["id"], worker_id="w1", lease_seconds=10) is False


def test_complete_job_is_noop_once_lease_recovered(tmp_path):
    db = tmp_path / ".ra" / "platform.sqlite3"
    store = PlatformStore(db)
    project = store.ensure_project(tmp_path)
    job = store.enqueue_job(project_id=project["id"], workflow_id="single")
    store.claim_job(worker_id="w1", lease_seconds=10)

    _expire_all_leases(db)
    store.recover_expired_jobs()  # 旧持有者失联，作业翻回 queued
    store.complete_job(job["id"])  # 迟到的完成写回必须无效

    row = store.list_jobs(project["id"])[0]
    assert row["status"] == "queued"


def test_fail_job_is_noop_once_lease_recovered(tmp_path):
    db = tmp_path / ".ra" / "platform.sqlite3"
    store = PlatformStore(db)
    project = store.ensure_project(tmp_path)
    job = store.enqueue_job(project_id=project["id"], workflow_id="single")
    store.claim_job(worker_id="w1", lease_seconds=10)

    _expire_all_leases(db)
    store.recover_expired_jobs()
    result = store.fail_job(job["id"], error="迟到的失败写回")

    assert result is None  # 未命中 running 行返回 None
    row = store.list_jobs(project["id"])[0]
    assert row["status"] == "queued"
    assert row["last_error"] == ""


def test_fail_job_still_retries_when_running(tmp_path):
    """归属守卫不能误伤正常重试路径。"""
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    job = store.enqueue_job(project_id=project["id"], workflow_id="single", max_attempts=2)
    store.claim_job(worker_id="w1", lease_seconds=10)
    retry = store.fail_job(job["id"], error="temporary", retry_delay=0.25)
    assert retry["status"] == "queued" and retry["attempts"] == 1


def test_claim_caps_crash_loop_at_max_attempts(tmp_path):
    """硬崩溃循环：反复到期回收的作业在预算耗尽时直接判失败，不再派发。"""
    db = tmp_path / ".ra" / "platform.sqlite3"
    store = PlatformStore(db)
    project = store.ensure_project(tmp_path)
    job = store.enqueue_job(project_id=project["id"], workflow_id="single", max_attempts=1)

    first = store.claim_job(worker_id="w1", lease_seconds=10)
    assert first and first["attempts"] == 1
    _expire_all_leases(db)  # worker 进程消失 → 租约到期被回收

    again = store.claim_job(worker_id="w2", lease_seconds=10)
    assert again is None  # 不派发
    row = store.list_jobs(project["id"])[0]
    assert row["id"] == job["id"]
    assert row["status"] == "failed"
    assert "超过最大尝试次数" in row["last_error"]
    assert row["lease_until"] is None


# ---------------------------------------------------------------------------
# Scheduler 层：租约心跳 / 租约丢失中止 / stop(drain=False)
# ---------------------------------------------------------------------------

class _StubStore:
    """DurableScheduler._run_claimed 依赖的最小 store 桩。

    payload 里带 ``_lease_seconds=0.6`` 把续约心跳压到 0.2s，让「长时间
    作业期间持续续期」可以在亚秒级断言。
    """

    def __init__(self) -> None:
        self.job_lease_ok = True
        self.resource_lease_ok = True
        self.renew_job_calls: list[tuple[str, str]] = []
        self.completed: list[str] = []
        self.failed: list[str] = []
        self.released_leases: list[str] = []

    def release_due_triggers(self) -> int:
        return 0

    def recover_expired_jobs(self) -> int:
        return 0

    def recover_expired_resource_leases(self) -> int:
        return 0

    def claim_job(self, *, worker_id: str, lease_seconds: float = 300):
        return {
            "id": "job-1", "workflow_id": "fake", "resource_key": "",
            "payload": {"_lease_seconds": 0.6},
        }

    def renew_job_lease(self, job_id, *, worker_id=None, lease_seconds=300):
        self.renew_job_calls.append((str(job_id), str(worker_id)))
        return self.job_lease_ok

    def acquire_resource_lease(self, **kwargs):
        return {"id": "lease-1", "resource_key": kwargs.get("resource_key", "")}

    def renew_resource_lease(self, lease_id, *, lease_seconds=3600):
        return self.resource_lease_ok

    def release_resource_lease(self, lease_id):
        self.released_leases.append(str(lease_id))
        return True

    def complete_job(self, job_id) -> None:
        self.completed.append(str(job_id))

    def fail_job(self, job_id, *, error, retry_delay=30.0):
        self.failed.append(str(job_id))


def test_run_claimed_keeps_renewing_job_lease():
    async def main():
        store = _StubStore()
        sched = DurableScheduler(store, worker_id="w1")
        started = asyncio.Event()
        finish = asyncio.Event()

        async def fake_dispatcher(job):
            started.set()
            await finish.wait()

        sched.register("fake", fake_dispatcher)
        runner = asyncio.create_task(sched._run_claimed(store.claim_job(worker_id="w1")))
        await asyncio.wait_for(started.wait(), timeout=2)
        # lease=0.6s → 心跳间隔 min(0.6/3, 60)=0.2s：0.5s 内至少续期一次
        await asyncio.sleep(0.5)
        assert len(store.renew_job_calls) >= 1
        assert all(owner == "w1" for _, owner in store.renew_job_calls)
        finish.set()
        await asyncio.wait_for(runner, timeout=2)
        assert store.completed == ["job-1"]
        assert store.failed == []

    asyncio.run(main())


def test_lost_job_lease_aborts_without_write_back():
    async def main():
        store = _StubStore()
        store.job_lease_ok = False  # 首次续约即失败：已被回收重领
        sched = DurableScheduler(store, worker_id="w1")
        interrupted = asyncio.Event()
        ran_to_end = asyncio.Event()

        async def fake_dispatcher(job):
            try:
                await asyncio.sleep(5)  # 远长于首个心跳间隔
                ran_to_end.set()
            except asyncio.CancelledError:
                interrupted.set()
                raise

        sched.register("fake", fake_dispatcher)
        task = asyncio.create_task(sched._run_claimed(store.claim_job(worker_id="w1")))
        await asyncio.wait_for(interrupted.wait(), timeout=3)
        assert not ran_to_end.is_set()  # 执行被中止
        assert store.completed == [] and store.failed == []  # 旧结果不得写回
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)
        assert store.released_leases == ["lease-1"]  # 资源租约照常清理

    asyncio.run(main())


def test_scheduler_stop_without_drain_returns_fast(tmp_path):
    async def main():
        db = tmp_path / ".ra" / "platform.sqlite3"
        store = PlatformStore(db)
        project = store.ensure_project(tmp_path)
        store.enqueue_job(project_id=project["id"], workflow_id="fake")
        sched = DurableScheduler(store, poll_seconds=0.25)
        entered = asyncio.Event()
        exited = asyncio.Event()
        gate = asyncio.Event()

        async def fake_dispatcher(job):
            entered.set()
            await gate.wait()
            exited.set()

        sched.register("fake", fake_dispatcher)
        sched.start()
        await asyncio.wait_for(entered.wait(), timeout=5)

        t0 = time.monotonic()
        await asyncio.wait_for(sched.stop(drain=False), timeout=3)
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0, f"stop(drain=False) 耗时 {elapsed:.2f}s，不应等待排空"
        assert not exited.is_set()  # 活跃假作业仍在跑

        # 被搁置的任务必须保住引用不被 GC，并能自然跑完
        gate.set()
        await asyncio.wait_for(exited.wait(), timeout=3)
        for _ in range(30):
            await asyncio.sleep(0.02)
        pending = [t for t in _DETACHED_TASKS if not t.done()]
        assert not pending, "detached 任务应自然结束且引用由实例持有"

    asyncio.run(main())
