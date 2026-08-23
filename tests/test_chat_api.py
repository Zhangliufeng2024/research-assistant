"""R2 会话模式后端测试：会话 REST CRUD + /ws/chat 会话循环。

不 import 项目 app.py（避免 lifespan 的技能装配与真实 LLM 依赖）：
裸 FastAPI + include_router(chat router)，app.state 手工接线。
挂载方式与 docs/protocol.md「§ 会话协议」约定一致——同一 router include
两次（prefix="/api" 供 REST，无前缀供 /ws/chat）。

WS 循环入口 ``run_agent`` 与 ``build_llm_client`` 均被替换为假实现：
假循环依次触发 on_text / on_tool_start / on_tool_use 回调并返回
AgentResult，从而驱动服务端产出 text / tool_card / usage / result 帧。
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import research_assistant.web.chat as chat_mod  # noqa: E402
from research_assistant.agent import AgentResult  # noqa: E402
from research_assistant.kernel.approval import ToolApprovalRequest  # noqa: E402
from research_assistant.llm.base import LLMResponse  # noqa: E402
from research_assistant.tools.registry import ToolRegistry  # noqa: E402
from research_assistant.web.chat import (  # noqa: E402
    extract_artifact_paths,
    router,
)


def _make_app(tmp_path: Path) -> FastAPI:
    """裸 app：REST 挂 /api 前缀，WS 挂根路径（与生产挂载约定一致）。"""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.include_router(router)
    app.state.cwd = tmp_path
    app.state.model = "test-model"
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.active_tasks = {}
    return app


class FakeLLMClient:
    """最小 LLM client 替身：只记录收到的消息序列。"""

    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []

    async def chat(self, messages, **kwargs) -> LLMResponse:
        self.calls.append([dict(m) for m in messages])
        return LLMResponse(content="ok")

    async def close(self) -> None:
        pass


def _install_fakes(monkeypatch, behavior) -> dict:
    """替换 chat 模块的 run_agent / build_llm_client；返回捕获字典。

    *behavior* 是 ``async def behavior(kwargs) -> AgentResult``，在假循环
    内可触发 on_text / on_tool_start / on_tool_use 回调驱动服务端发帧。
    """
    captured: dict = {}

    def fake_run_agent(**kwargs):
        captured.update(kwargs)
        return behavior(kwargs)

    monkeypatch.setattr(chat_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(chat_mod, "build_llm_client",
                        lambda model=None: FakeLLMClient())
    return captured


async def _happy_behavior(kw) -> AgentResult:
    """标准一轮：文本 → 工具卡 → 文本 → 正常结束。"""
    await kw["on_text"]("你好")
    await kw["on_tool_start"]("write_file",
                              {"file_path": "figures/f.png", "content": "x"})
    await kw["on_tool_use"]("write_file", {"file_path": "figures/f.png"},
                            "Wrote file figures/f.png")
    await kw["on_text"]("，完成")
    return AgentResult(text_output="你好，完成", turns=2, stop_reason="completed")


def _collect_until(ws, stop_types: tuple[str, ...], cap=200) -> list[dict]:
    """收帧直到出现 *stop_types* 之一（该帧包含在返回内）。"""
    frames = []
    for _ in range(cap):
        msg = ws.receive_json()
        frames.append(msg)
        if msg.get("type") in stop_types:
            break
    return frames


def _wait_until(predicate, timeout: float = 5.0) -> bool:
    """轮询等待条件成立（跨线程断言 app 事件用）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# ---------------------------------------------------------------------------
# C1: REST CRUD
# ---------------------------------------------------------------------------

class TestSessionRest:
    def test_create_returns_id_and_persists(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)

        data = client.post("/api/chat/sessions").json()
        assert set(data) == {"id", "created_at"}
        assert isinstance(data["created_at"], float)

        run_dir = tmp_path / ".ra" / "sessions" / data["id"]
        assert run_dir.is_dir()
        state = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        assert state["mode"] == "chat"
        assert state["status"] == "running"
        history = json.loads(
            (run_dir / "history.json").read_text(encoding="utf-8"))
        assert history["messages"] == []

    def test_create_with_title_derives_slug(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)

        data = client.post("/api/chat/sessions",
                           json={"title": "量子计算 综述!"}).json()
        assert "量子计算_" in data["id"]

    def test_list_sorted_by_updated_at_desc(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)

        first = client.post("/api/chat/sessions",
                            json={"title": "会话一"}).json()
        time.sleep(0.01)  # 保证 updated_at 可分
        second = client.post("/api/chat/sessions",
                             json={"title": "会话二"}).json()

        items = client.get("/api/chat/sessions").json()
        assert [i["id"] for i in items] == [second["id"], first["id"]]
        item = items[0]
        for key in ("id", "title", "last_message", "turns",
                    "created_at", "updated_at"):
            assert key in item
        assert item["title"] == "会话二"
        assert item["turns"] == 0
        assert item["last_message"] == ""

    def test_list_summary_from_history(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions", json={"title": "t"}).json()["id"]
        chat_mod._write_history(
            tmp_path / ".ra" / "sessions" / sid,
            [{"role": "user", "content": "帮我画图" * 30},
             {"role": "assistant", "content": "好的，图已生成"},
             {"role": "user", "content": "   "}])

        items = client.get("/api/chat/sessions").json()
        item = items[0]
        assert item["turns"] == 2  # 用户消息数（空白消息不计入 last，但计 turns）
        assert item["last_message"] == "好的，图已生成"
        assert len(item["last_message"]) <= 80

    def test_detail_returns_full_history(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions").json()["id"]
        msgs = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
        chat_mod._write_history(tmp_path / ".ra" / "sessions" / sid, msgs)

        data = client.get(f"/api/chat/sessions/{sid}").json()
        assert data["id"] == sid
        assert data["messages"] == msgs

    def test_detail_unknown_404_and_bad_id_403(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        assert client.get("/api/chat/sessions/ghost").status_code == 404
        # ".." 会被 HTTP 客户端规范化掉，路径穿越防御直接测解析函数
        with pytest.raises(ValueError):
            chat_mod._resolve_session_dir(tmp_path, "..")
        with pytest.raises(ValueError):
            chat_mod._resolve_session_dir(tmp_path, "a\\b")
        with pytest.raises(ValueError):
            chat_mod._resolve_session_dir(tmp_path, "C:evil")

    def test_delete_removes_dir_then_404(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions").json()["id"]

        assert client.delete(f"/api/chat/sessions/{sid}").json() == {"ok": True}
        assert not (tmp_path / ".ra" / "sessions" / sid).exists()
        assert client.delete(f"/api/chat/sessions/{sid}").status_code == 404


class TestZeroTurnGc:
    """§6.4 空会话治理：列表时清退「零轮次且过期」的会话目录。

    背景：前端先 POST 建目录再连 WS，连接失败的残骸是零轮次目录；
    用户消息在回合开始前先落盘（_run_turn），故零轮次严格等价于
    「从未收到任何用户消息」，整目录删除不丢任何对话内容。
    """

    @staticmethod
    def _backdate(tmp_path: Path, sid: str, seconds: float) -> Path:
        """把会话的 run.json updated_at 回拨 *seconds* 秒，返回目录路径。"""
        run_dir = tmp_path / ".ra" / "sessions" / sid
        path = run_dir / "run.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["updated_at"] = time.time() - seconds
        path.write_text(json.dumps(state), encoding="utf-8")
        return run_dir

    def test_stale_zero_turn_swept_from_list_and_disk(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions", json={"title": "残骸"}).json()["id"]
        run_dir = self._backdate(tmp_path, sid, seconds=7200)

        items = client.get("/api/chat/sessions").json()
        assert all(i["id"] != sid for i in items)
        assert not run_dir.exists()  # 目录一并清退，不留磁盘垃圾

    def test_fresh_zero_turn_kept(self, tmp_path):
        """刚建目录尚未开回合的会话必须保留（in-flight 保护）。"""
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions").json()["id"]

        items = client.get("/api/chat/sessions").json()
        assert [i["id"] for i in items] == [sid]

    def test_old_session_with_user_message_kept(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions").json()["id"]
        run_dir = self._backdate(tmp_path, sid, seconds=7200)
        chat_mod._write_history(
            run_dir, [{"role": "user", "content": "真实对话"}])

        items = client.get("/api/chat/sessions").json()
        assert [i["id"] for i in items] == [sid]
        assert run_dir.exists()


# ---------------------------------------------------------------------------
# C2/C3: WS 会话循环
# ---------------------------------------------------------------------------

class TestWsChatTurn:
    def test_full_turn_frame_sequence_and_persistence(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                hello = ws.receive_json()
                assert hello["type"] == "connected"
                assert set(hello) == {"type", "session_id", "outputs_dir"}

                ws.send_json({"action": "user", "text": "画个图"})
                frames = _collect_until(ws, ("result",))

        types = [f["type"] for f in frames]
        assert types[0] == "text"
        assert types[-1] == "result"
        assert set(types) >= {"text", "tool_card", "usage", "result"}

        # 文本增量按序拼接为整轮回复
        deltas = "".join(f["delta"] for f in frames if f["type"] == "text")
        assert deltas == "你好，完成"

        # 工具卡：running → done，done 帧带预览与产物文件
        cards = [f for f in frames if f["type"] == "tool_card"]
        assert [c["status"] for c in cards] == ["running", "done"]
        assert cards[0]["tool"] == "write_file"
        assert cards[0]["arguments"] == {"file_path": "figures/f.png", "content": "x"}
        assert cards[1]["id"] == cards[0]["id"]  # 同一卡片按 id 合并
        assert cards[1]["result_preview"].startswith("Wrote file")
        assert len(cards[1]["result_preview"]) <= 400
        assert cards[1]["files"] == [{"path": "figures/f.png"}]

        # usage 帧：budget 快照（B5 格式）
        usage = [f for f in frames if f["type"] == "usage"]
        assert usage and isinstance(usage[-1]["budget"], dict)
        assert "cost_usd" in usage[-1]["budget"]

        # result 帧
        result = frames[-1]
        assert result["stop_reason"] == "completed"
        assert result["turns"] == 2

        # history.json 落盘且 REST 可读回（D2 唯一权威）
        sid = hello["session_id"]
        history = json.loads((tmp_path / ".ra" / "sessions" / sid
                              / "history.json").read_text(encoding="utf-8"))
        assert history["messages"] == [
            {"role": "user", "content": "画个图"},
            {"role": "assistant", "content": "你好，完成"},
        ]
        data = client.get(f"/api/chat/sessions/{sid}").json()
        assert data["messages"] == history["messages"]
        run_state = json.loads((tmp_path / ".ra" / "sessions" / sid
                                / "run.json").read_text(encoding="utf-8"))
        assert run_state["status"] == "complete"

        # 会话列表可见且摘要正确
        items = client.get("/api/chat/sessions").json()
        assert items[0]["id"] == sid
        assert items[0]["turns"] == 1
        assert items[0]["last_message"] == "你好，完成"

    def test_resume_injects_history_into_first_llm_call(self, tmp_path, monkeypatch):
        """二次连接恢复历史：归约历史经适配层注入本轮首个 LLM 请求。"""

        async def _resume_behavior(kw):
            # 模拟内核的首个 LLM 调用：单条 user 消息 → 包装层应前置拼接历史
            await kw["llm_client"].chat([{"role": "user", "content": kw["prompt"]}])
            await kw["on_text"]("收到")
            return AgentResult(text_output="收到", stop_reason="completed")

        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                sid = ws.receive_json()["session_id"]
                ws.send_json({"action": "user", "text": "第一问"})
                _collect_until(ws, ("result",))

            captured = _install_fakes(monkeypatch, _resume_behavior)
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                assert ws.receive_json()["session_id"] == sid
                ws.send_json({"action": "user", "text": "第二问"})
                _collect_until(ws, ("result",))

        # 适配层：本轮首个请求 = 既往归约历史 + 新用户消息
        llm = captured["llm_client"]
        assert [m["content"] for m in llm.prefix] == ["第一问", "你好，完成"]
        first_call = llm._inner.calls[0]  # 真实请求打在内层 client 上
        assert [m["content"] for m in first_call] == [
            "第一问", "你好，完成", "第二问"]

        history = json.loads((tmp_path / ".ra" / "sessions" / sid
                              / "history.json").read_text(encoding="utf-8"))
        assert history["messages"] == [
            {"role": "user", "content": "第一问"},
            {"role": "assistant", "content": "你好，完成"},
            {"role": "user", "content": "第二问"},
            {"role": "assistant", "content": "收到"},
        ]

    def test_new_session_created_when_query_missing(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                sid = ws.receive_json()["session_id"]
        assert (tmp_path / ".ra" / "sessions" / sid / "run.json").is_file()

    def test_unknown_session_id_auto_recreated(self, tmp_path, monkeypatch):
        """已删除的会话按同名幂等重建（不卡死 UI）。"""
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat?session=ghost") as ws:
                assert ws.receive_json() == {"type": "connected",
                                             "session_id": "ghost",
                                             "outputs_dir": "outputs/ghost"}
        assert (tmp_path / ".ra" / "sessions" / "ghost" / "run.json").is_file()

    def test_illegal_session_id_rejected(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        with TestClient(app) as client:
            with client.websocket_connect(
                    "/ws/chat?session=..%2Fescape") as ws:
                err = ws.receive_json()
                assert err["type"] == "error"
                assert "不合法" in err["message"]
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
        assert not (tmp_path / ".ra" / "escape").exists()


class TestWsChatControl:
    def test_oversize_and_empty_steer_rejected(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)

        async def behavior(kw):
            q = kw["steer_queue"]
            got = None
            try:
                got = await asyncio.wait_for(q.get(), timeout=5)
            except asyncio.TimeoutError:
                pass
            await kw["on_text"](f"steer={got}")
            return AgentResult(text_output=f"steer={got}",
                               stop_reason="completed")

        _install_fakes(monkeypatch, behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                ws.receive_json()
                ws.send_json({"action": "user", "text": "开始"})
                ws.send_json({"action": "steer", "message": "长" * 2001})
                ws.send_json({"action": "steer", "message": "   "})
                ws.send_json({"action": "steer", "message": "改为英文"})
                frames = _collect_until(ws, ("result",))

        errors = [f for f in frames if f["type"] == "error"]
        assert any("过长" in f["message"] for f in errors)
        assert any("不能为空" in f["message"] for f in errors)
        # 合法 steer 仍送达内核队列并注入
        deltas = "".join(f["delta"] for f in frames if f["type"] == "text")
        assert deltas == "steer=改为英文"

    def test_idle_steer_queued_for_next_turn(self, tmp_path, monkeypatch):
        """空闲期收到的 steer 入队，下一轮开始时被内核消费。"""
        app = _make_app(tmp_path)
        captured: dict = {}

        async def behavior(kw):
            captured.setdefault("queues", []).append(kw["steer_queue"])
            got = []
            try:
                got.append(await asyncio.wait_for(kw["steer_queue"].get(),
                                                  timeout=2))
            except asyncio.TimeoutError:
                pass
            await kw["on_text"](f"got={got}")
            return AgentResult(text_output=f"got={got}",
                               stop_reason="completed")

        _install_fakes(monkeypatch, behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                ws.receive_json()
                ws.send_json({"action": "steer", "message": "先想好再答"})
                ws.send_json({"action": "user", "text": "问题"})
                frames = _collect_until(ws, ("result",))
                # 第二轮：队列已被第一轮消费，拿不到新 steer
                ws.send_json({"action": "user", "text": "再来"})
                _collect_until(ws, ("result",))

        deltas = [f["delta"] for f in frames if f["type"] == "text"]
        assert deltas == ["got=['先想好再答']"]

    def test_stop_action_cancels_turn(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)

        async def behavior(kw):
            ce = kw["config"].cancel_event
            while not ce.is_set():
                await asyncio.sleep(0.01)
            return AgentResult(text_output="停了", stop_reason="cancelled",
                               turns=1)

        _install_fakes(monkeypatch, behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                ws.receive_json()
                ws.send_json({"action": "user", "text": "慢慢跑"})
                ws.send_json({"action": "stop"})
                frames = _collect_until(ws, ("result",))

        assert frames[-1]["stop_reason"] == "cancelled"
        # 取消轮的回复同样落盘（对话流完整）
        sid = None
        for child in (tmp_path / ".ra" / "sessions").iterdir():
            sid = child.name
        history = json.loads((tmp_path / ".ra" / "sessions" / sid
                              / "history.json").read_text(encoding="utf-8"))
        assert history["messages"][-1] == {"role": "assistant", "content": "停了"}

    def test_approval_round_trip(self, tmp_path, monkeypatch):
        """审批问询帧 + 回执经 QueueApprover 闭环（沿用 ws.py 先例）。"""
        app = _make_app(tmp_path)

        async def behavior(kw):
            req = ToolApprovalRequest(tool_name="bash",
                                      arguments={"command": "ls"}, turn=1)
            decision = await kw["config"].approver(req)
            await kw["on_text"](f"approved={decision.approved}")
            return AgentResult(text_output=f"approved={decision.approved}",
                               stop_reason="completed")

        _install_fakes(monkeypatch, behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                ws.receive_json()
                ws.send_json({"action": "user", "text": "跑个命令"})
                ask = ws.receive_json()
                assert ask["type"] == "approval_request"
                assert ask["tool"] == "bash"
                assert "ls" in ask["summary"]
                assert ask["id"]

                ws.send_json({"action": "approval", "id": ask["id"],
                              "approved": True})
                frames = _collect_until(ws, ("result",))

        deltas = [f["delta"] for f in frames if f["type"] == "text"]
        assert deltas == ["approved=True"]

    def test_stale_approval_receipt_ignored(self, tmp_path, monkeypatch):
        """迟到/未知 id 的审批回执不得自动应答下一次问询。"""
        app = _make_app(tmp_path)
        state = {"phase": 0}

        async def behavior(kw):
            state["phase"] += 1
            req = ToolApprovalRequest(tool_name="bash",
                                      arguments={"command": f"cmd{state['phase']}"},
                                      turn=1)
            decision = await kw["config"].approver(req)
            await kw["on_text"](f"r{state['phase']}={decision.approved}")
            return AgentResult(text_output=f"r{state['phase']}={decision.approved}",
                               stop_reason="completed")

        _install_fakes(monkeypatch, behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                ws.receive_json()
                # 第一轮：先发一个无人问询时的"预答"（应被忽略）
                ws.send_json({"action": "approval", "id": "bogus",
                              "approved": True})
                ws.send_json({"action": "user", "text": "第一轮"})
                ask1 = ws.receive_json()
                assert ask1["type"] == "approval_request"
                ws.send_json({"action": "approval", "id": ask1["id"],
                              "approved": False})
                frames1 = _collect_until(ws, ("result",))
                assert frames1[-1]["type"] == "result"

                # 第二轮：残留的 True 不应自动放行 —— 问询仍在等待
                ws.send_json({"action": "user", "text": "第二轮"})
                ask2 = ws.receive_json()
                assert ask2["type"] == "approval_request"
                ws.send_json({"action": "approval", "id": ask2["id"],
                              "approved": True})
                frames2 = _collect_until(ws, ("result",))

        texts = [f["delta"] for f in frames1 + frames2 if f["type"] == "text"]
        assert texts == ["r1=False", "r2=True"]

    def test_disconnect_cancels_running_turn(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        captured: dict = {}

        async def behavior(kw):
            captured["cancel"] = kw["config"].cancel_event
            while not kw["config"].cancel_event.is_set():
                await asyncio.sleep(0.01)
            return AgentResult(text_output="x", stop_reason="cancelled")

        _install_fakes(monkeypatch, behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                ws.receive_json()
                ws.send_json({"action": "user", "text": "长任务"})
                assert _wait_until(lambda: "cancel" in captured)
            # 退出 with：socket 关闭 → 服务端必须置位 cancel_event
            assert _wait_until(lambda: captured["cancel"].is_set())

    def test_concurrent_connection_kicks_previous(self, tmp_path, monkeypatch):
        """同一会话并发连接：后连者踢前者（旧 socket 收到 close）。"""
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat?session=duo") as ws1:
                assert ws1.receive_json()["session_id"] == "duo"
                with client.websocket_connect("/ws/chat?session=duo") as ws2:
                    assert ws2.receive_json()["session_id"] == "duo"
                    with pytest.raises(WebSocketDisconnect):
                        ws1.receive_json()

    def test_user_message_validation(self, tmp_path, monkeypatch):
        """空消息 / 超长消息被拒且不触发循环。"""
        app = _make_app(tmp_path)
        calls: list = []

        async def behavior(kw):  # pragma: no cover - 不应被调用
            calls.append(True)
            return AgentResult(text_output="x", stop_reason="completed")

        _install_fakes(monkeypatch, behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                ws.receive_json()
                ws.send_json({"action": "user", "text": "   "})
                err1 = ws.receive_json()
                ws.send_json({"action": "user", "text": "超" * 8001})
                err2 = ws.receive_json()
                ws.send_json({"action": "nonsense"})
                err3 = ws.receive_json()

        assert err1["type"] == "error" and "不能为空" in err1["message"]
        assert err2["type"] == "error" and "过长" in err2["message"]
        assert err3["type"] == "error" and "未知 action" in err3["message"]
        assert calls == []


# ---------------------------------------------------------------------------
# C4: 产物路径提取（纯函数）
# ---------------------------------------------------------------------------

class TestExtractArtifactPaths:
    def test_write_file_takes_argument_path(self):
        out = extract_artifact_paths(
            "write_file", {"file_path": "writing_outputs/x/draft.docx"}, "OK")
        assert out == [{"path": "writing_outputs/x/draft.docx"}]

    def test_edit_file_takes_argument_path(self):
        out = extract_artifact_paths(
            "edit_file", {"file_path": "notes.md"}, "done")
        assert out == [{"path": "notes.md"}]

    def test_run_python_scans_result_text(self):
        text = ("Saved figure to figures/loss_curve.png and table at out/stats.csv\n"
                "also D:\\data\\summary.pdf written")
        out = extract_artifact_paths("run_python", {}, text)
        paths = [f["path"] for f in out]
        assert "figures/loss_curve.png" in paths
        assert "out/stats.csv" in paths
        assert "D:\\data\\summary.pdf" in paths

    def test_read_file_and_glob_not_extracted(self):
        assert extract_artifact_paths(
            "read_file", {"file_path": "data/raw.csv"}, "...content...") == []
        assert extract_artifact_paths(
            "glob_files", {"path": "figures"}, "figures/a.png\nfigures/b.png") == []

    def test_denied_and_error_results_yield_nothing(self):
        denied = extract_artifact_paths(
            "write_file", {"file_path": "x.png"}, "[DENIED by policy] nope")
        assert denied == []
        errored = extract_artifact_paths(
            "run_python", {}, "Error executing run_python: boom.png")
        assert errored == []

    def test_dedupe_and_cap(self):
        text = " ".join(f"f{i}.png" for i in range(20))
        out = extract_artifact_paths("run_python", {}, text)
        assert len(out) == 8  # ARTIFACT_PATH_LIMIT
        assert len({f["path"] for f in out}) == 8

    def test_non_dict_arguments_tolerated(self):
        assert extract_artifact_paths("write_file", None, "ok") == []


# ---------------------------------------------------------------------------
# R12 P2/B4: 会话产物目录接线（双轨制的会话侧）
# ---------------------------------------------------------------------------


class TestChatOutputsDir:
    """连接即建 ``<工作区>/outputs/<sid>/`` 并全链路接线。

    - 连接时建目录：frozen_exec 对不存在的 CWD 硬失败，不能推迟到首回合；
    - run.json 落盘 outputs_dir（相对 POSIX 路径）；connected 帧为前端权威源
      （REST 列表在工作区切换后会错接另一工作区的同名目录）；
    - ToolRegistry(work_dir=根, write_anchor=产物目录, exec_cwd=产物目录)：
      相对写入与 bash/run_python 默认 CWD 都归巢产物目录；
    - POST 建会话**不**建产物目录（防零轮次孤儿）；旧会话重连惰性补建；
    - 清退 / 删除会话时配对删除 outputs/<sid>。
    """

    @staticmethod
    def _outputs(tmp_path: Path, sid: str) -> Path:
        return tmp_path / "outputs" / sid

    def test_connected_frame_creates_and_reports_outputs_dir(
            self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                hello = ws.receive_json()
        sid = hello["session_id"]
        assert hello["outputs_dir"] == f"outputs/{sid}"
        assert self._outputs(tmp_path, sid).is_dir()

    def test_run_json_persists_outputs_dir(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                sid = ws.receive_json()["session_id"]
        state = json.loads(
            (tmp_path / ".ra" / "sessions" / sid / "run.json")
            .read_text(encoding="utf-8"))
        assert state["outputs_dir"] == f"outputs/{sid}"

    def test_registry_anchored_and_cwd_homed(self, tmp_path, monkeypatch):
        """ToolRegistry 三参口径：sandbox=根不变，anchor/exec_cwd=产物目录。"""
        app = _make_app(tmp_path)
        captured = _install_fakes(monkeypatch, _happy_behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat") as ws:
                sid = ws.receive_json()["session_id"]
                ws.send_json({"action": "user", "text": "干活"})
                _collect_until(ws, ("result",))
        tools = captured["tools"]
        assert isinstance(tools, ToolRegistry)
        assert tools.work_dir == str(tmp_path)
        assert tools.write_anchor == str(self._outputs(tmp_path, sid))
        assert tools.exec_cwd == str(self._outputs(tmp_path, sid))

    def test_post_does_not_create_outputs_dir(self, tmp_path):
        """POST 只建会话目录——产物目录由 WS 连接补建，防零轮次孤儿。"""
        app = _make_app(tmp_path)
        client = TestClient(app)
        data = client.post("/api/chat/sessions").json()
        assert not self._outputs(tmp_path, data["id"]).exists()

    def test_reopen_legacy_session_lazily_creates_outputs_dir(
            self, tmp_path, monkeypatch):
        """B4 之前的旧会话（run.json 无 outputs_dir）重连时惰性补建。"""
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions", json={"title": "旧"}).json()["id"]
        # 手工抹掉 outputs_dir 字段模拟 legacy run.json（POST 本就不建目录）
        state = json.loads(
            (tmp_path / ".ra" / "sessions" / sid / "run.json")
            .read_text(encoding="utf-8"))
        state.pop("outputs_dir", None)
        (tmp_path / ".ra" / "sessions" / sid / "run.json").write_text(
            json.dumps(state), encoding="utf-8")

        with TestClient(app) as tc:
            with tc.websocket_connect(f"/ws/chat?session={sid}") as ws:
                hello = ws.receive_json()
        assert hello["outputs_dir"] == f"outputs/{sid}"
        assert self._outputs(tmp_path, sid).is_dir()

    def test_summary_outputs_dir_null_for_legacy_session(self, tmp_path):
        """列表摘要带 outputs_dir；legacy 会话为 null（前端空态兜底）。"""
        app = _make_app(tmp_path)
        client = TestClient(app)
        run_dir = tmp_path / ".ra" / "sessions" / "20200101_000000_legacy"
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(json.dumps({
            "mode": "chat", "query": "旧会话",
            "created_at": 1.0, "updated_at": 2.0,
        }), encoding="utf-8")
        # 带一条用户消息：否则零轮次 + 远古时间戳会被 §6.4 清退掉
        chat_mod._write_history(
            run_dir, [{"role": "user", "content": "真实对话"}])

        items = client.get("/api/chat/sessions").json()
        assert items[0]["id"] == "20200101_000000_legacy"
        assert items[0]["outputs_dir"] is None

    def test_sweep_pairs_deletion_of_outputs_dir(self, tmp_path):
        """零轮次清退时，outputs/<sid> 与会话目录 1:1 配对删除。"""
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions", json={"title": "残骸"}).json()["id"]
        out = self._outputs(tmp_path, sid)
        out.mkdir(parents=True)
        (out / "a.png").write_text("x", encoding="utf-8")
        run_dir = tmp_path / ".ra" / "sessions" / sid
        path = run_dir / "run.json"
        state = json.loads(path.read_text(encoding="utf-8"))
        state["updated_at"] = time.time() - 7200
        path.write_text(json.dumps(state), encoding="utf-8")

        items = client.get("/api/chat/sessions").json()
        assert all(i["id"] != sid for i in items)
        assert not run_dir.exists()
        assert not out.exists()

    def test_delete_session_pairs_deletion_of_outputs_dir(self, tmp_path):
        """用户显式删除会话 → 其产物目录一并删除（不留孤儿）。"""
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions").json()["id"]
        out = self._outputs(tmp_path, sid)
        out.mkdir(parents=True)

        assert client.delete(f"/api/chat/sessions/{sid}").json() == {"ok": True}
        assert not out.exists()


class TestChatSystemInstructions:
    """双绝对路径口径 + 执行契约注入（P1 的最后一个 choke point）。"""

    @staticmethod
    def _build(tmp_path: Path) -> str:
        return chat_mod._chat_system_instructions(
            tmp_path, tmp_path / "outputs" / "s1")

    def test_contains_both_absolute_paths(self, tmp_path):
        text = self._build(tmp_path)
        assert str(tmp_path) in text           # 共享根：读共享数据用绝对路径
        assert str(tmp_path / "outputs" / "s1") in text  # 产物目录

    def test_dev_contract_has_no_run_script(self, tmp_path):
        text = self._build(tmp_path)
        assert "run_script" not in text

    def test_frozen_contract_injected(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        text = self._build(tmp_path)
        assert "run_script" in text
        assert "sys.executable" in text
