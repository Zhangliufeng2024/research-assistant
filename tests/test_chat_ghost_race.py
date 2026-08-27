"""A3 幽灵会话墓碑测试：删除运行中的会话后，迟到的收尾写回不得复活目录。

背景：delete_session 旧实现对运行中会话只让出固定 0.2s 就 rmtree——回合
收尾一旦超过该窗口，_write_history / store.save·finish 会把目录重建回来，
形成只剩空壳的「幽灵会话」。修复后：删除先落墓碑（_TOMBSTONES），写回点
感知墓碑即放弃写回并自删残留；rmtree 前另等活跃回合真正退出（上限 8s）。

参照 tests/test_chat_api.py 的构造方式：不 import 项目 app.py，裸 FastAPI
+ include_router(chat router)，app.state 手工接线；run_agent /
build_llm_client 替换为假实现。覆盖：

- (a) 单元：手工往墓碑集加入 session_id 后，_write_history 与 run_state
  保存点（save / finish / log_event）均不落盘；
- (b) 集成：构造收尾很慢（取消后 0.5s 才返回）的假活跃回合，DELETE 后
  等 1.5s，断言会话目录与产物目录都没有被重建。
"""

import asyncio
import json
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import research_assistant.web.chat as chat_mod  # noqa: E402
from research_assistant.agent import AgentResult  # noqa: E402
from research_assistant.llm.base import LLMResponse  # noqa: E402
from research_assistant.session.store import SessionStore as _OrigStore  # noqa: E402

#: 各测试共用的会话 ID（= 会话目录名，见 chat._valid_session_id 约定）
SID = "20260826_000000_doomed"


def _make_app(tmp_path: Path) -> FastAPI:
    """裸 app：REST 挂 /api 前缀，WS 挂根路径（与生产挂载约定一致）。"""
    app = FastAPI()
    app.include_router(chat_mod.router, prefix="/api")
    app.include_router(chat_mod.router)
    app.state.cwd = tmp_path
    app.state.model = "test-model"
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.active_tasks = {}
    return app


class FakeLLMClient:
    """最小 LLM client 替身：本文件只关心落盘竞态，不记录消息序列。"""

    model = "fake-model"

    async def chat(self, messages, **kwargs) -> LLMResponse:
        return LLMResponse(content="ok")

    async def close(self) -> None:
        pass


def _install_fakes(monkeypatch, behavior) -> None:
    """替换 chat 模块的 run_agent / build_llm_client 为假实现。"""

    def fake_run_agent(**kwargs):
        return behavior(kwargs)

    monkeypatch.setattr(chat_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_mod, "build_llm_client",
                        lambda model=None: FakeLLMClient())


@pytest.fixture(autouse=True)
def _clean_tombstones():
    """墓碑集是模块级状态（生产语义：进程内存活），测试间必须清场防串扰。"""
    chat_mod._TOMBSTONES.clear()
    yield
    chat_mod._TOMBSTONES.clear()


# ---------------------------------------------------------------------------
# (a) 单元：手工墓碑 → 写回点全部不落盘
# ---------------------------------------------------------------------------


class TestTombstoneBlocksWrites:
    """手工往墓碑集加入 session_id 后：history / run_state / events 不落盘。"""

    def test_write_history_not_persisted(self, tmp_path):
        run_dir = tmp_path / ".ra" / "sessions" / SID
        run_dir.mkdir(parents=True)
        chat_mod._TOMBSTONES.add(SID)

        chat_mod._write_history(run_dir, [{"role": "user", "content": "x"}])

        assert not (run_dir / "history.json").exists()  # 核心断言：不落盘
        assert not run_dir.exists()  # 收尾路径感知墓碑后自删残留目录

    def test_store_save_finish_log_not_persisted(self, tmp_path):
        """run_state 保存点（save/finish/log_event）同样被墓碑拦截。

        chat.SessionStore 已在模块级重绑为守卫子类——ws_chat 调用期拿到的
        就是它（名字解析发生在调用期），这里直接验证其行为。
        """
        assert issubclass(chat_mod.SessionStore, _OrigStore)
        run_dir = tmp_path / ".ra" / "sessions" / SID
        run_dir.mkdir(parents=True)
        store = chat_mod.SessionStore(run_dir)
        chat_mod._TOMBSTONES.add(SID)

        store.save()
        store.log_event("turn_start", {"chars": 1})
        store.finish("complete", {"cost_usd": 0.0})

        assert not (run_dir / "run.json").exists()
        assert not (run_dir / "events.jsonl").exists()
        assert not run_dir.exists()

    def test_store_writes_normally_without_tombstone(self, tmp_path):
        """对照组：未入墓碑的会话写回不受影响（防拦截面扩大化）。"""
        run_dir = tmp_path / ".ra" / "sessions" / SID
        run_dir.mkdir(parents=True)
        store = chat_mod.SessionStore(run_dir)

        store.save()
        store.finish("complete", {})

        state = json.loads(
            (run_dir / "run.json").read_text(encoding="utf-8"))
        assert state["status"] == "complete"
        kinds = {
            json.loads(line)["kind"]
            for line in (run_dir / "events.jsonl")
            .read_text(encoding="utf-8").splitlines()
        }
        assert "run_end" in kinds

    def test_late_write_after_real_delete_blocked(self, tmp_path):
        """显式删除普通会话同样落墓碑：之后的迟到写回不得复活目录。"""
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions").json()["id"]

        assert client.delete(f"/api/chat/sessions/{sid}").json() == {"ok": True}
        assert sid in chat_mod._TOMBSTONES  # 墓碑保留到进程结束

        chat_mod._write_history(tmp_path / ".ra" / "sessions" / sid,
                                [{"role": "user", "content": "复活?"}])
        assert not (tmp_path / ".ra" / "sessions" / sid).exists()


class TestSweepSkipsTombstoned:
    """_sweep_zero_turn_sessions 必须跳过墓碑会话（删除流程可能仍在等回合）。"""

    def test_stale_zero_turn_tombstoned_kept(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions",
                          json={"title": "残骸"}).json()["id"]
        run_dir = tmp_path / ".ra" / "sessions" / sid
        path = run_dir / "run.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["updated_at"] = time.time() - 7200  # 回拨：越过零轮次 TTL
        path.write_text(json.dumps(state), encoding="utf-8")
        chat_mod._TOMBSTONES.add(sid)

        client.get("/api/chat/sessions")  # 触发清退扫描

        assert run_dir.exists()  # 墓碑会话未被清退
        items = client.get("/api/chat/sessions").json()
        assert any(i["id"] == sid for i in items)


# ---------------------------------------------------------------------------
# (b) 集成：收尾很慢的假活跃回合，删除后目录不得被重建
# ---------------------------------------------------------------------------


class TestDeleteSlowFinalizeRace:
    """删除「收尾超过旧 0.2s 窗口」的运行中会话：幽灵会话不得出现。"""

    @staticmethod
    def _recv_until_disconnect(ws, timeout: float = 5.0) -> int:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                ws.receive_json()
            except WebSocketDisconnect as exc:
                return exc.code
        raise AssertionError("活跃连接未被服务端关闭（超时）")

    def test_slow_finalize_does_not_resurrect_deleted_session(
            self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        captured: dict = {}

        async def slow_finalize_behavior(kw):
            captured["cancel"] = kw["config"].cancel_event
            while not kw["config"].cancel_event.is_set():
                await asyncio.sleep(0.01)
            # 模拟取消传播后的慢收尾：0.5s 后才返回——结构性大于旧实现的
            # 0.2s 固定窗口（旧行为下该收尾必然把目录重建回幽灵会话）。
            await asyncio.sleep(0.5)
            await kw["on_text"]("迟来的回复")
            return AgentResult(text_output="迟来的回复",
                               stop_reason="cancelled", turns=1)

        _install_fakes(monkeypatch, slow_finalize_behavior)

        # 侦测收尾写回的尝试时刻：证明它发生在删除开始之后 ≥0.25s
        # （即晚于旧实现的 rmtree 时点），而目录依然没有被重建。
        real_write = chat_mod._write_history
        attempts: list[tuple[str, float]] = []
        delete_t0 = {"t": None}

        def spying_write(run_dir, messages):
            attempts.append((Path(run_dir).name, time.monotonic()))
            return real_write(run_dir, messages)

        monkeypatch.setattr(chat_mod, "_write_history", spying_write)

        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/chat?session={SID}") as ws:
                assert ws.receive_json()["session_id"] == SID
                ws.send_json({"action": "user", "text": "长任务"})
                deadline = time.time() + 5
                while "cancel" not in captured and time.time() < deadline:
                    time.sleep(0.01)
                assert "cancel" in captured

                delete_t0["t"] = time.monotonic()
                resp = client.delete(f"/api/chat/sessions/{SID}")
                assert resp.json() == {"ok": True}
                # 删除端点先关连接再等回合退出：客户端应收到 4002 关闭帧
                assert self._recv_until_disconnect(ws) == 4002

        # 慢收尾确实发生过，且落在删除开始之后（越过旧 0.2s 窗口）
        late = [t for s, t in attempts if s == SID and t > delete_t0["t"]]
        assert late, "慢收尾的写回尝试未被观测到"
        assert late[0] - delete_t0["t"] >= 0.25

        # 等 1.5s：会话目录与产物目录都不得被重建（幽灵会话修复的核心断言）
        time.sleep(1.5)
        assert not (tmp_path / ".ra" / "sessions" / SID).exists()
        assert not (tmp_path / "outputs" / SID).exists()

        # 墓碑仍在（进程内不移除）：此刻补一笔迟到写回同样不得落盘
        assert SID in chat_mod._TOMBSTONES
        chat_mod._write_history(tmp_path / ".ra" / "sessions" / SID,
                                [{"role": "user", "content": "迟到"}])
        assert not (tmp_path / ".ra" / "sessions" / SID).exists()

    def test_delete_running_session_still_closes_and_removes(
            self, tmp_path, monkeypatch):
        """回归对照：快速收尾的运行中会话删除流程行为不变（4002 + 目录消失）。"""
        app = _make_app(tmp_path)
        captured: dict = {}

        async def quick_behavior(kw):
            captured["cancel"] = kw["config"].cancel_event
            while not kw["config"].cancel_event.is_set():
                await asyncio.sleep(0.01)
            return AgentResult(text_output="x", stop_reason="cancelled")

        _install_fakes(monkeypatch, quick_behavior)
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/chat?session={SID}") as ws:
                assert ws.receive_json()["session_id"] == SID
                ws.send_json({"action": "user", "text": "长任务"})
                deadline = time.time() + 5
                while "cancel" not in captured and time.time() < deadline:
                    time.sleep(0.01)
                assert client.delete(f"/api/chat/sessions/{SID}").json() == {"ok": True}
                assert self._recv_until_disconnect(ws) == 4002

        assert not (tmp_path / ".ra" / "sessions" / SID).exists()
        assert not (tmp_path / "outputs" / SID).exists()
