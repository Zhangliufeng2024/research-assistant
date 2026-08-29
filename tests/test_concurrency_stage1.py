"""A+ 阶段 1：并发正确性专项回归。

覆盖四个确定性缺陷（编号沿用 2026-08-28-A-plus-refactor-plan.md）：

- **C-1** `task_hub.handles` 永不清理 → 每个已完成任务常驻一份句柄
  （subscribers set + 两个队列 + Task 引用），`live_count` 随时间虚高。
- **C-2** 重复 attach 抬高 `observers` 计数 → 孤儿看门狗永不武装，
  无人观察的回合一直跑到预算耗尽。
- **C-3** `_LIVE`/`_SINKS` 注册竞态 → 帧投递到错误的连接。
- **C-4** `_start_turn` 无活动回合占位检查 → 并发回合丢更新。
- **F-5** `write_file` 只 resolve 父目录 → 符号链接可写穿路径围栏。

设计原则（A+ 验收要求「并发测试必须确定性」）：
  1. 断言用**事件同步**而非 sleep 猜时间；确需等待的用轮询 + 超时；
  2. 每条用例都要能区分「修好了」与「没修好」——反向断言不可省；
  3. 不依赖调度顺序，避免 flaky。
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from research_assistant.runtime.platform_store import PlatformStore
from research_assistant.runtime.task_hub import BackgroundTaskHub

# ---------------------------------------------------------------------------
# C-1：BackgroundTaskHub.handles 终态释放
# ---------------------------------------------------------------------------


def _store(tmp_path: Path) -> PlatformStore:
    return PlatformStore(tmp_path / ".ra" / "platform.sqlite3")


def _ok_runner():
    async def runner(_handle):
        yield {"type": "progress", "stage": "work", "message": "ok"}
        yield {"type": "result", "status": "success"}

    return runner


class TestTaskHandleRelease:
    def test_handle_registered_while_running(self, tmp_path):
        async def main():
            store = _store(tmp_path)
            project = store.ensure_project(tmp_path)
            hub = BackgroundTaskHub(store)
            handle = hub.start(
                project_id=project["id"], query="q", mode="single",
                runner_factory=_ok_runner(),
            )
            # 反向断言：运行中**必须**登记在册，否则订阅者收不到帧。
            assert handle.task_id in hub.handles
            await handle.task

        asyncio.run(main())

    def test_handle_released_after_terminal(self, tmp_path):
        """核心回归：终态后句柄必须被摘除。"""
        async def main():
            store = _store(tmp_path)
            project = store.ensure_project(tmp_path)
            hub = BackgroundTaskHub(store)
            handle = hub.start(
                project_id=project["id"], query="q", mode="single",
                runner_factory=_ok_runner(),
            )
            await handle.task
            assert handle.task_id not in hub.handles, "终态后句柄未释放（C-1 泄漏）"

        asyncio.run(main())

    def test_handle_released_on_failure(self, tmp_path):
        """失败路径同样要释放（原实现的 finally 不区分成功/失败）。"""
        async def main():
            async def failing(_handle):
                yield {"type": "progress", "stage": "work", "message": "boom"}
                raise RuntimeError("任务炸了")
                yield {"type": "result", "status": "success"}  # pragma: no cover

            store = _store(tmp_path)
            project = store.ensure_project(tmp_path)
            hub = BackgroundTaskHub(store)
            handle = hub.start(
                project_id=project["id"], query="q", mode="single",
                runner_factory=failing,
            )
            await handle.task
            assert handle.task_id not in hub.handles
            assert handle.status == "failed"

        asyncio.run(main())

    def test_handles_do_not_accumulate(self, tmp_path):
        """串行跑 20 个任务后不得残留（原实现每个都留一条）。"""
        async def main():
            store = _store(tmp_path)
            project = store.ensure_project(tmp_path)
            hub = BackgroundTaskHub(store)
            for i in range(20):
                handle = hub.start(
                    project_id=project["id"], query=f"q{i}", mode="single",
                    runner_factory=_ok_runner(),
                )
                await handle.task
            assert hub.handles == {}

        asyncio.run(main())

    def test_terminal_frame_still_delivered(self, tmp_path):
        """反向断言：释放句柄不能把 done 帧弄丢——这是把 pop 放在 finally
        末尾而非开头的原因（publish 靠 handles 找订阅者）。"""
        async def main():
            store = _store(tmp_path)
            project = store.ensure_project(tmp_path)
            hub = BackgroundTaskHub(store)
            queue = None

            handle = hub.start(
                project_id=project["id"], query="q", mode="single",
                runner_factory=_ok_runner(),
            )
            queue = hub.subscribe(handle.task_id)
            assert queue is not None
            await handle.task

            frames = []
            while not queue.empty():
                frames.append(queue.get_nowait())
            kinds = [f.get("type") for f in frames]
            assert "done" in kinds, f"done 帧丢失，实际收到：{kinds}"

        asyncio.run(main())


# ---------------------------------------------------------------------------
# C-3：连接登记原子性（原实现的 await 竞态）
# ---------------------------------------------------------------------------


class TestRegisterConnection:
    def test_registration_is_synchronous(self):
        """同步调用后登记表立即更新——证明占位不在任何 await 之后。"""
        import research_assistant.web.chat as chat_mod

        sentinel_a = object()
        sentinel_b = object()
        sink_a = object()
        sink_b = object()
        try:
            prev = chat_mod._register_connection("s-sync", sentinel_a, sink_a)
            assert prev is None
            assert chat_mod._LIVE["s-sync"] is sentinel_a
            assert chat_mod._SINKS["s-sync"] is sink_a

            prev = chat_mod._register_connection("s-sync", sentinel_b, sink_b)
            assert prev is sentinel_a           # 返回被替换的旧 socket
            assert chat_mod._LIVE["s-sync"] is sentinel_b
            assert chat_mod._SINKS["s-sync"] is sink_b
        finally:
            chat_mod._LIVE.pop("s-sync", None)
            chat_mod._SINKS.pop("s-sync", None)

    def test_critical_section_has_no_await(self):
        """结构性回归锁：登记函数内不得出现 await / async with / async for。

        这是 C-3 的根因——原实现把 `await previous.close()` 夹在读旧值和
        写登记表之间。竞态很难用行为测试稳定复现，故用 AST 锁死结构。
        （用 AST 而非字符串匹配：函数文档里提到 await 字样不应算违规。）
        """
        import ast

        import research_assistant.web.chat as chat_mod

        tree = ast.parse(inspect.getsource(chat_mod._register_connection))
        offenders = [
            type(n).__name__
            for n in ast.walk(tree)
            if isinstance(n, (ast.Await, ast.AsyncFor, ast.AsyncWith))
        ]
        assert not offenders, f"登记函数内出现异步节点 {offenders} —— 竞态会回归"

    def test_registration_survives_uncooperative_close(self):
        """旧连接 close 永不返回时，新连接的登记依然完整。

        这正是原实现的失效场景：await close 挂住 → 登记表停在旧值/半更新态。
        """
        import research_assistant.web.chat as chat_mod

        class HangingSocket:
            def __init__(self) -> None:
                self.closed = False

            async def close(self, *args, **kwargs):
                # 永不返回
                await asyncio.Event().wait()

        old_sock = HangingSocket()
        new_sock = object()
        sink = object()
        try:
            chat_mod._LIVE["s-hang"] = old_sock
            chat_mod._SINKS["s-hang"] = object()

            async def main():
                previous = chat_mod._register_connection("s-hang", new_sock, sink)
                # 不 await previous.close()，登记表也应已完整指向新连接
                assert chat_mod._LIVE["s-hang"] is new_sock
                assert chat_mod._SINKS["s-hang"] is sink
                return previous

            prev = asyncio.run(main())
            assert prev is old_sock
        finally:
            chat_mod._LIVE.pop("s-hang", None)
            chat_mod._SINKS.pop("s-hang", None)

    def test_close_quietly_swallows_errors(self):
        """被替换的旧连接关闭失败不得影响新连接（原实现用 try/except 吞掉）。"""
        import research_assistant.web.chat as chat_mod

        class ExplodingSocket:
            async def close(self, *args, **kwargs):
                raise RuntimeError("close failed")

        # 不得抛出异常
        asyncio.run(
            chat_mod._close_quietly(ExplodingSocket(), code=4001, reason="replaced")
        )


# ---------------------------------------------------------------------------
# C-4：活动回合占位判据
# ---------------------------------------------------------------------------


class TestHasActiveTurn:
    async def test_no_handle_means_no_active_turn(self):
        import research_assistant.web.chat as chat_mod

        chat_mod._ACTIVE.pop("s-none", None)
        assert chat_mod._has_active_turn("s-none") is False

    async def test_running_task_means_active(self):
        import research_assistant.web.chat as chat_mod

        handle = chat_mod._TurnHandle()
        gate = asyncio.Event()

        async def pending():
            await gate.wait()

        handle.task = asyncio.ensure_future(pending())
        chat_mod._ACTIVE["s-run"] = handle
        try:
            assert chat_mod._has_active_turn("s-run") is True
        finally:
            handle.task.cancel()
            chat_mod._ACTIVE.pop("s-run", None)

    async def test_finished_task_means_inactive(self):
        """已完成（但尚未从 _ACTIVE 摘除）的回合不算活动。"""
        import research_assistant.web.chat as chat_mod

        async def done():
            return None

        task = asyncio.ensure_future(done())
        await task
        handle = chat_mod._TurnHandle()
        handle.task = task
        chat_mod._ACTIVE["s-done"] = handle
        try:
            assert chat_mod._has_active_turn("s-done") is False
        finally:
            chat_mod._ACTIVE.pop("s-done", None)

    async def test_none_task_treated_as_active(self):
        """task 尚未 spawn（None）时按活动处理——保守方向，宁可拒绝也不并发。"""
        import research_assistant.web.chat as chat_mod

        handle = chat_mod._TurnHandle()
        handle.task = None
        chat_mod._ACTIVE["s-pending"] = handle
        try:
            assert chat_mod._has_active_turn("s-pending") is True
        finally:
            chat_mod._ACTIVE.pop("s-pending", None)


# ---------------------------------------------------------------------------
# C-6：job_queue 写路径 BEGIN IMMEDIATE（WAL 下的 SQLITE_BUSY_SNAPSHOT）
# ---------------------------------------------------------------------------


class TestJobQueueWriteTransactions:
    """WAL + deferred 事务下，先读后写会在并发提交时抛 SQLITE_BUSY_SNAPSHOT
    （**不等待** busy_timeout），导致整次状态转换被丢掉。`fail_job` 正是
    read-modify-write：读 attempts 快照 → 判定终态/重试 → 写回。

    竞态本身在单进程里很难稳定复现，故此处用两条互补断言：
      1. 结构性：四个写方法都显式取写锁（AST/源码级，防被改回去）；
      2. 行为性：多 worker（独立 store 实例 = 独立连接与锁）并发跑完一批
         作业，不得抛错、不得丢状态转换。
    """

    _METHODS = ("complete_job", "fail_job", "defer_job", "recover_expired_jobs")

    def test_write_paths_take_immediate_lock(self):
        import research_assistant.runtime.platform_store as ps_mod

        for name in self._METHODS:
            src = inspect.getsource(getattr(ps_mod.PlatformStore, name))
            assert "BEGIN IMMEDIATE" in src, (
                f"{name} 未显式取写锁 —— 多 worker 下可能丢状态转换（C-6 回归）"
            )

    def test_claim_job_already_uses_immediate_lock(self):
        """对照：claim_job 一直是这么写的，其余四个应与它同口径。"""
        import research_assistant.runtime.platform_store as ps_mod

        assert "BEGIN IMMEDIATE" in inspect.getsource(ps_mod.PlatformStore.claim_job)

    def test_concurrent_workers_do_not_lose_transitions(self, tmp_path):
        """两个独立 store 实例（模拟两个进程/线程 worker）并发消费同一队列。"""
        import threading

        db = tmp_path / ".ra" / "platform.sqlite3"
        store = PlatformStore(db)
        project = store.ensure_project(tmp_path)
        for i in range(12):
            store.enqueue_job(
                project_id=project["id"], workflow_id="single",
                payload={"query": f"q{i}"},
            )

        # 每个 worker 用自己的实例：连接与 _lock 都不共享，才是真实多进程形态
        workers = [PlatformStore(db) for _ in range(3)]
        errors: list[BaseException] = []
        completed: list[str] = []
        completed_lock = threading.Lock()

        def run(w: PlatformStore, wid: str) -> None:
            try:
                while True:
                    job = w.claim_job(worker_id=wid, lease_seconds=60)
                    if job is None:
                        return
                    w.complete_job(job["id"])
                    with completed_lock:
                        completed.append(job["id"])
            except BaseException as exc:  # noqa: BLE001 - 收集后统一断言
                errors.append(exc)

        threads = [
            threading.Thread(target=run, args=(w, f"w{i}")) for i, w in enumerate(workers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"并发写回抛错：{errors!r}"
        assert len(set(completed)) == 12, f"状态转换丢失，仅完成 {len(set(completed))}/12"
        rows = store.list_jobs(project["id"])
        assert all(r["status"] == "complete" for r in rows)


# ---------------------------------------------------------------------------
# C-7：出站信箱有界（背压）
# ---------------------------------------------------------------------------


class TestOutboxBackpressure:
    def test_default_maxsize_is_bounded(self):
        """默认必须有界 —— 无界会让慢客户端把帧无限堆进内存。"""
        import research_assistant.web.chat as chat_mod

        assert chat_mod.OUTBOX_MAXSIZE > 0

    def test_maxsize_respects_env_override(self, monkeypatch):
        import research_assistant.web.chat as chat_mod

        monkeypatch.setenv("RA_CHAT_OUTBOX_MAXSIZE", "7")
        assert chat_mod._outbox_maxsize() == 7

    def test_maxsize_zero_means_unbounded(self, monkeypatch):
        """0 = 退回旧的无界行为（保留逃生开关）。"""
        import research_assistant.web.chat as chat_mod

        monkeypatch.setenv("RA_CHAT_OUTBOX_MAXSIZE", "0")
        assert chat_mod._outbox_maxsize() == 0

    def test_maxsize_invalid_env_falls_back(self, monkeypatch):
        import research_assistant.web.chat as chat_mod

        monkeypatch.setenv("RA_CHAT_OUTBOX_MAXSIZE", "not-a-number")
        assert chat_mod._outbox_maxsize() == 1000

    def test_ws_chat_applies_the_bound(self):
        import research_assistant.web.chat as chat_mod

        src = inspect.getsource(chat_mod.ws_chat)
        assert "maxsize=OUTBOX_MAXSIZE" in src, "出站队列未套用上限（C-7 回归）"

    def test_post_goes_through_bounded_put(self):
        """_post 必须走有界入队，不能退回裸 put_nowait。"""
        import research_assistant.web.chat as chat_mod

        src = inspect.getsource(chat_mod.ws_chat)
        assert "bounded_put(outbox" in src, "出站入队绕过了背压（C-7 回归）"


class TestBoundedPut:
    """丢最旧背压策略的直接验证（C-7）。"""

    @staticmethod
    def _q(maxsize: int) -> asyncio.Queue:
        return asyncio.Queue(maxsize=maxsize)

    def test_below_capacity_puts_without_dropping(self):
        import research_assistant.web.chat as chat_mod

        q = self._q(3)
        assert chat_mod.bounded_put(q, {"n": 1}) is False
        assert chat_mod.bounded_put(q, {"n": 2}) is False
        assert [q.get_nowait()["n"] for _ in range(2)] == [1, 2]

    def test_full_drops_oldest_and_keeps_newest(self):
        import research_assistant.web.chat as chat_mod

        q = self._q(2)
        chat_mod.bounded_put(q, {"n": 1})
        chat_mod.bounded_put(q, {"n": 2})
        dropped = chat_mod.bounded_put(q, {"n": 3})

        assert dropped is True, "满队列未报告丢弃"
        assert q.qsize() == 2
        remaining = [q.get_nowait()["n"] for _ in range(2)]
        assert remaining == [2, 3], f"应丢最旧保留最新，实际 {remaining}"

    def test_terminal_frames_survive(self):
        """关键语义：终态帧（result/usage）必须留下，丢的只能是最老的。"""
        import research_assistant.web.chat as chat_mod

        q = self._q(2)
        for i in range(50):
            chat_mod.bounded_put(q, {"n": i})
        chat_mod.bounded_put(q, {"type": "result"})
        frames = [q.get_nowait() for _ in range(q.qsize())]
        assert frames[-1]["type"] == "result", "终态帧被丢弃"

    def test_unbounded_queue_never_drops(self):
        """maxsize<=0（RA_CHAT_OUTBOX_MAXSIZE=0 逃生开关）时退化为无界。"""
        import research_assistant.web.chat as chat_mod

        q = self._q(0)
        for i in range(500):
            assert chat_mod.bounded_put(q, {"n": i}) is False
        assert q.qsize() == 500

    def test_frame_objects_are_not_mutated(self):
        """反向断言：不得就地改写帧——入队对象可能与环形缓冲共享引用。"""
        import research_assistant.web.chat as chat_mod

        q = self._q(1)
        frame = {"n": 1}
        chat_mod.bounded_put(q, frame)
        chat_mod.bounded_put(q, {"n": 2})
        assert frame == {"n": 1}, "入队时修改了调用方的帧对象"


# ---------------------------------------------------------------------------
# F-5：write_file 路径围栏（符号链接写穿）
# ---------------------------------------------------------------------------


class TestWriteFilePathFence:
    def test_resolves_full_path_not_just_parent(self, tmp_path, monkeypatch):
        """核心回归（平台无关）：write_file 必须对**完整路径**做围栏校验。

        修复前只 resolve 父目录再把文件名裸拼回去，因此文件名那一层完全
        不受围栏保护。这里探测 safe_resolve 收到的实参来锁定该行为——
        比构造符号链接更可靠（Windows 无开发者模式时 symlink_to 会静默
        产出普通文件，导致链接类用例被跳过）。
        """
        import research_assistant.core as core_mod
        import research_assistant.tools.file_ops as file_ops_mod

        sandbox = tmp_path / "ws"
        sandbox.mkdir()
        seen: list[Path] = []
        original = core_mod.safe_resolve

        def spy(path, sandbox_path, *args, **kwargs):
            seen.append(Path(path))
            return original(path, sandbox_path, *args, **kwargs)

        monkeypatch.setattr(file_ops_mod, "safe_resolve", spy)

        asyncio.run(file_ops_mod.write_file("notes.txt", "hello", sandbox=str(sandbox)))

        assert seen, "safe_resolve 未被调用"
        assert seen[-1].name == "notes.txt", (
            f"围栏只校验到父目录（收到 {seen[-1]}），文件名那一层未受保护 —— F-5 回归"
        )

    def test_normal_write_still_works(self, tmp_path):
        """反向断言：围栏收紧不能把正常写入也堵死。"""
        from research_assistant.tools.file_ops import write_file

        sandbox = tmp_path / "ws"
        sandbox.mkdir()
        result = asyncio.run(write_file("notes.txt", "hello", sandbox=str(sandbox)))
        assert result.startswith("Successfully wrote")
        assert (sandbox / "notes.txt").read_text(encoding="utf-8") == "hello"

    def test_nested_relative_path_still_works(self, tmp_path):
        """子目录下的相对写入同样正常（防过度收紧）。"""
        from research_assistant.tools.file_ops import write_file

        sandbox = tmp_path / "ws"
        sandbox.mkdir()
        result = asyncio.run(
            write_file("sub/dir/deep.txt", "x" * 10, sandbox=str(sandbox))
        )
        assert result.startswith("Successfully wrote")
        assert (sandbox / "sub" / "dir" / "deep.txt").exists()

    def test_symlink_outside_sandbox_is_refused(self, tmp_path):
        """符号链接写穿（仅在真能创建符号链接的环境下执行）。

        ⚠️ Windows 未开启开发者模式时 `Path.symlink_to` 可能**不报错地**
        产出普通文件（is_symlink() 为 False），此时链路其实没建起来，
        测了等于没测——必须以 is_symlink() 为准跳过，不能只 catch 异常。
        CI（ubuntu-latest）上符号链接可用，会在那里真正执行。
        """
        from research_assistant.tools.file_ops import write_file

        sandbox = tmp_path / "ws"
        sandbox.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("原始内容", encoding="utf-8")
        link = sandbox / "escape.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("当前环境无法创建符号链接")
        if not link.is_symlink():
            pytest.skip("符号链接未真正建立（Windows 需开发者模式或管理员权限）")

        result = asyncio.run(write_file("escape.txt", "被写入的内容", sandbox=str(sandbox)))

        assert result.startswith("Error"), f"越权写入未被拦截：{result}"
        assert outside.read_text(encoding="utf-8") == "原始内容", "沙箱外文件被改写"

    def test_symlinked_directory_is_refused(self, tmp_path):
        """目录级符号链接同样要拦（父目录在沙箱内、解析后逸出）。"""
        from research_assistant.tools.file_ops import write_file

        sandbox = tmp_path / "ws"
        sandbox.mkdir()
        outside_dir = tmp_path / "outside_dir"
        outside_dir.mkdir()
        link_dir = sandbox / "linked"
        try:
            link_dir.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("当前环境无法创建目录符号链接")
        if not link_dir.is_symlink():
            pytest.skip("目录符号链接未真正建立（Windows 需开发者模式或管理员权限）")

        result = asyncio.run(write_file("linked/x.txt", "内容", sandbox=str(sandbox)))
        assert result.startswith("Error"), f"目录级越权未被拦截：{result}"
        assert not (outside_dir / "x.txt").exists()
