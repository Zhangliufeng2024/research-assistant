"""P2-2 回归：task_hub._persist_frame 单事务合并。

旧实现一帧内每个 store 操作各自 _connect()（读 steps、写 step、
_advance_steps、append_event 各一次建连），最坏 4-5 次/帧。
合并后必须恰好 1 次建连，且行为与旧实现等价、异常时整体回滚。
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from research_assistant.runtime import BackgroundTaskHub, PlatformStore
from research_assistant.runtime import task_hub as task_hub_module


@pytest.fixture()
def env(tmp_path: Path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    hub = BackgroundTaskHub(store)
    return store, project, hub


def _make_task(store: PlatformStore, project_id: str) -> str:
    task_id = "t" + "0" * 11
    store.create_task(task_id=task_id, project_id=project_id, query="q", mode="paper")
    store.create_steps(
        task_id,
        [
            {"id": "plan", "title": "Plan"},
            {"id": "research", "title": "Research"},
            {"id": "figures", "title": "Figures"},
            {"id": "assemble", "title": "Assemble"},
        ],
    )
    return task_id


def _count_connects(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """包装 PlatformStore._connect 计数；返回可断言的调用次数容器。"""
    counter = [0]
    real_connect = PlatformStore._connect

    @contextmanager
    def counting_connect(self: PlatformStore):
        counter[0] += 1
        with real_connect(self) as conn:
            yield conn

    monkeypatch.setattr(PlatformStore, "_connect", counting_connect)
    return counter


class TestPersistFrameSingleConnection:
    def test_step_frame_uses_one_connection(self, env, monkeypatch):
        """核心回归：带 step 转换的帧（读 steps + 关闭前序 + 置 running + 追加
        event）必须只建连 1 次。旧实现这里是 4 次。"""
        store, project, hub = env
        task_id = _make_task(store, project["id"])
        counter = _count_connects(monkeypatch)

        seq = hub._persist_frame(task_id, {"type": "progress", "stage": "assemble"})
        assert counter[0] == 1, f"期望 1 次建连，实际 {counter[0]} 次"
        assert seq == 1
        # 行为等价：assemble 置 running，research/figures 被关闭；
        # plan 不在 assemble 的 close_before 特殊映射里，保持 pending（原行为）
        statuses = {s["id"]: s["status"] for s in store.list_steps(task_id)}
        assert statuses["assemble"] == "running"
        assert statuses["research"] == "done"
        assert statuses["figures"] == "done"
        assert statuses["plan"] == "pending"

    def test_plain_frame_uses_one_connection(self, env, monkeypatch):
        """无 step_id 的帧只 append_event，同样 1 次建连。"""
        store, project, hub = env
        task_id = _make_task(store, project["id"])
        counter = _count_connects(monkeypatch)

        hub._persist_frame(task_id, {"type": "progress", "stage": "work"})
        assert counter[0] == 1
        assert len(store.read_events(task_id)) == 1

    def test_explicit_status_frame_uses_one_connection(self, env, monkeypatch):
        """explicit_status 路径（resumed/done/...）同样 1 次建连。"""
        store, project, hub = env
        task_id = _make_task(store, project["id"])
        counter = _count_connects(monkeypatch)

        hub._persist_frame(
            task_id,
            {"type": "progress", "stage": "plan", "details": {"step_id": "plan", "status": "done"}},
        )
        assert counter[0] == 1
        statuses = {s["id"]: s["status"] for s in store.list_steps(task_id)}
        assert statuses["plan"] == "done"


class TestPersistFrameAtomicity:
    def test_failure_rolls_back_step_update(self, env, monkeypatch):
        """append_event 抛错时，同事务内的 step 更新必须回滚。"""
        store, project, hub = env
        task_id = _make_task(store, project["id"])

        def exploding_append(conn: Any, tid: str, payload: dict) -> int:
            raise RuntimeError("磁盘写炸了")

        monkeypatch.setattr(store, "_append_event_conn", exploding_append)
        with pytest.raises(RuntimeError):
            hub._persist_frame(task_id, {"type": "progress", "stage": "assemble"})

        # step 未被更新（回滚生效）
        statuses = {s["id"]: s["status"] for s in store.list_steps(task_id)}
        assert statuses["assemble"] == "pending"
        assert statuses["research"] == "pending"
        # event 未落库
        assert store.read_events(task_id) == []

    def test_recovery_after_rollback(self, env, monkeypatch):
        """回滚后同帧重放必须成功（事务未污染连接状态）。"""
        store, project, hub = env
        task_id = _make_task(store, project["id"])

        original = store._append_event_conn
        calls = {"n": 0}

        def flaky_append(conn: Any, tid: str, payload: dict) -> int:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("第一次失败")
            return original(conn, tid, payload)

        monkeypatch.setattr(store, "_append_event_conn", flaky_append)
        with pytest.raises(RuntimeError):
            hub._persist_frame(task_id, {"type": "progress", "stage": "work"})
        seq = hub._persist_frame(task_id, {"type": "progress", "stage": "work"})
        assert seq == 1  # 回滚后 seq 从头开始，不跳号
        assert len(store.read_events(task_id)) == 1


class TestPersistFrameSeqMonotonic:
    def test_seq_monotonic_across_frames(self, env):
        """多帧顺序持久化，seq 严格递增且事件可回放。"""
        store, project, hub = env
        task_id = _make_task(store, project["id"])
        seqs = [
            hub._persist_frame(task_id, {"type": "progress", "stage": "plan"}),
            hub._persist_frame(task_id, {"type": "progress", "stage": "research"}),
            hub._persist_frame(task_id, {"type": "progress", "stage": "assemble"}),
        ]
        assert seqs == [1, 2, 3]
        replayed = store.read_events(task_id)
        assert [e["seq"] for e in replayed] == [1, 2, 3]


class TestPublishIntegration:
    def test_publish_via_to_thread_end_to_end(self, env):
        """publish()（asyncio.to_thread 路径）端到端：帧落库且订阅者收到 seq。"""
        store, project, hub = env
        task_id = _make_task(store, project["id"])
        hub.handles[task_id] = task_hub_module.TaskHandle(
            task_id=task_id, query="q", project_id=project["id"],
        )
        queue: asyncio.Queue = asyncio.Queue(maxsize=10)
        hub.handles[task_id].subscribers.add(queue)

        async def main():
            await hub.publish(task_id, {"type": "progress", "stage": "plan"})
            return queue.get_nowait()

        message = asyncio.run(main())
        assert message["seq"] == 1
        assert len(store.read_events(task_id)) == 1
