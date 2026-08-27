"""R16 聊天耐久化契约回归：断连回放 / 游标过滤 / 孤儿收尸 / 历史治理 / 附件围栏。

被测实现 research_assistant/web/chat.py：
- ``_TurnHandle.seq/frames`` 环形缓冲与 ws_chat 的 attach 回放协议
  （replay_begin{last_seq,status} → 按 seq 过滤的帧 → replay_end /
  全新会话 replay_empty）；
- 孤儿看门狗 ``_orphan_reap``：最后观察者离开满 ORPHAN_GRACE_S（模块常量，
  默认 max(30, RA_CHAT_ORPHAN_GRACE_SECONDS)）后协作停止并把回复按
  ``partial: true`` 落盘；
- 历史治理 REST：POST …/truncate、PATCH …/messages/{i}（wire 字段为
  ``text``）、POST …/attachments（multipart 上传落 outputs/<sid>/uploads/）；
- ``_safe_upload_name`` 文件名消毒（剥目录成分 + 冒号等非法字符）与
  ``_validate_attachment_refs`` 引用围栏（越界拒绝且不开轮）；
- 运行中收到第二条 user 消息按 steer 注入运行中的回合。

辅助（app 装配 / 假循环安装 / 收帧 / 轮询等待 / happy 行为）直接复用
tests/test_chat_api.py 的同款实现，保证两份测试口径一致。
"""

import asyncio
import json
import threading
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.web.chat as chat_mod  # noqa: E402
from research_assistant.agent import AgentResult  # noqa: E402
from tests.test_chat_api import (  # noqa: E402
    _collect_until,
    _happy_behavior,
    _install_fakes,
    _make_app,
    _wait_until,
)


def _hist_path(tmp_path: Path, sid: str) -> Path:
    return tmp_path / ".ra" / "sessions" / sid / "history.json"


def _messages(tmp_path: Path, sid: str) -> list[dict]:
    data = json.loads(_hist_path(tmp_path, sid).read_text(encoding="utf-8"))
    return data.get("messages", [])


def _try_messages(tmp_path: Path, sid: str) -> list[dict] | None:
    """容错读取历史：文件尚不存在或正被替换时返回 None（供轮询谓词使用）。"""
    try:
        return _messages(tmp_path, sid)
    except (OSError, ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# A. 断连回放：回合与连接解耦，重连 attach 补发错过的帧
# ---------------------------------------------------------------------------


class TestReplayAfterDisconnect:
    def test_reconnect_replays_missed_frames(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        gate = threading.Event()

        async def behavior(kw):
            await kw["on_text"]("前半")
            # 主线程断开连接后才放行——模拟「断连期间回合继续跑」
            while not gate.is_set():
                await asyncio.sleep(0.01)
            await kw["on_text"]("后半")
            return AgentResult(text_output="前半后半",
                               stop_reason="completed", turns=1)

        _install_fakes(monkeypatch, behavior)
        sid = "dura-a"

        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                hello = ws.receive_json()
                assert hello["session_id"] == sid
                ws.send_json({"action": "user", "text": "长任务"})
                # 用户消息先行落盘（回合启动即写，不等回复）
                assert _wait_until(lambda: _hist_path(tmp_path, sid).is_file())
                # 收到「前半」帧后再断开：保证它是断点之前的已发帧
                saw_first_half = False
                for _ in range(100):
                    frame = ws.receive_json()
                    if frame.get("type") == "text" and frame.get("delta") == "前半":
                        saw_first_half = True
                        break
                assert saw_first_half
            # with 块退出即断开；回合不得随之取消（R16 耐久化核心）

            gate.set()  # 断连之后才让假循环跑出「后半」
            assert _wait_until(lambda: (
                (lambda msgs: msgs is not None
                 and len(msgs) >= 2
                 and msgs[-1].get("content") == "前半后半")
                (_try_messages(tmp_path, sid))
                and sid not in chat_mod._ACTIVE  # 收尾完成，status 已定格
            ))

            # 重连同会话并 attach(after=0)：完整回放错过的帧
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({"action": "attach", "after": 0})
                frames = _collect_until(ws, ("replay_end",))

        assert frames[0]["type"] == "replay_begin"
        assert frames[0]["status"] == "complete"
        assert frames[0]["last_seq"] > 0
        assert frames[-1]["type"] == "replay_end"
        assert frames[-1]["status"] == "complete"
        assert frames[-1]["last_seq"] == frames[0]["last_seq"]

        # 断点前后的两条文本帧都补发到位，且按 seq 保序
        texts = [f["delta"] for f in frames if f["type"] == "text"]
        assert texts == ["前半", "后半"]
        mids = frames[1:-1]
        seqs = [f["seq"] for f in mids]
        assert seqs == sorted(seqs)

        # 终态落盘：完整回复、无 partial 标记（正常完成不是残缺回答）
        msgs = _messages(tmp_path, sid)
        assert msgs[-1] == {"role": "assistant", "content": "前半后半"}


# ---------------------------------------------------------------------------
# B. after 游标过滤：只回放 seq 大于游标的帧
# ---------------------------------------------------------------------------


class TestAttachAfterCursor:
    def test_after_cursor_only_replays_newer_frames(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        sid = "dura-b"

        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({"action": "user", "text": "第一轮"})
                frames1 = _collect_until(ws, ("result",))
            last_text_seq = max(f["seq"] for f in frames1 if f["type"] == "text")
            last_seq = frames1[-1]["seq"]
            assert last_seq > last_text_seq  # 文本帧之后还有 usage/result 尾帧

            assert _wait_until(lambda: sid not in chat_mod._ACTIVE)

            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({"action": "attach", "after": last_text_seq})
                frames2 = _collect_until(ws, ("replay_end",))

        begin, end = frames2[0], frames2[-1]
        assert begin["type"] == "replay_begin"
        assert begin["last_seq"] >= last_seq  # 回放源记录到回合最后一帧
        end_seq_ok = end["type"] == "replay_end"
        assert end_seq_ok and end["last_seq"] == begin["last_seq"]
        assert end["status"] == "complete"

        mids = frames2[1:-1]
        assert mids, "游标之后的尾帧（usage/result）应当被回放"
        assert all(f["seq"] > last_text_seq for f in mids)
        assert all(f["type"] != "text" for f in mids)  # 文本帧不越过游标重放
        assert mids[-1]["type"] == "result"


# ---------------------------------------------------------------------------
# C. replay_empty：全新会话没有任何可回放的回合
# ---------------------------------------------------------------------------


class TestReplayEmpty:
    def test_fresh_session_attach_yields_replay_empty(
            self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)  # 防误触真实 LLM；不发 user
        with TestClient(app) as client:
            sid = client.post("/api/chat/sessions",
                              json={"title": "空会话"}).json()["id"]
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({"action": "attach", "after": 5})
                assert ws.receive_json() == {"type": "replay_empty"}


# ---------------------------------------------------------------------------
# D. 孤儿宽限收尸：宽限到期协作停止，回复以 partial 落盘
# ---------------------------------------------------------------------------


class TestOrphanReap:
    def test_orphan_turn_cancelled_and_persisted_as_partial(
            self, tmp_path, monkeypatch):
        # 看门狗在 await 时直接读模块常量 ORPHAN_GRACE_S，patch 即生效提速；
        # 生产默认 max(30, RA_CHAT_ORPHAN_GRACE_SECONDS)，此处无需设环境变量。
        monkeypatch.setattr(chat_mod, "ORPHAN_GRACE_S", 0.2)

        async def behavior(kw):
            ce = kw["config"].cancel_event
            while not ce.is_set():
                await asyncio.sleep(0.01)
            return AgentResult(text_output="孤儿收尾",
                               stop_reason="cancelled", turns=1)

        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, behavior)
        sid = "dura-d"

        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({"action": "user", "text": "慢慢跑"})
                assert _wait_until(lambda: _hist_path(tmp_path, sid).is_file())
            # 立刻断开成孤儿：唯一出口是看门狗宽限到期后的协作停止。
            # 注意等待必须留在 TestClient 存续期内——退出即关停事件循环，
            # 看门狗任务会被一并取消，收尸永远不会发生。

            def _reaped():
                msgs = _try_messages(tmp_path, sid)
                return bool(msgs) and msgs[-1].get("role") == "assistant" \
                    and msgs[-1].get("partial") is True

            assert _wait_until(_reaped, timeout=10.0)

        last = _messages(tmp_path, sid)[-1]
        assert last["content"] == "孤儿收尾"  # 协作停止路径的正常落盘文本


# ---------------------------------------------------------------------------
# E. truncate：截断为前 keep 条
# ---------------------------------------------------------------------------


class TestTruncateHistory:
    MSGS = [
        {"role": "user", "content": "问一"},
        {"role": "assistant", "content": "答一"},
        {"role": "user", "content": "问二"},
        {"role": "assistant", "content": "答二"},
    ]

    def _session_with_four(self, tmp_path: Path, client: TestClient) -> str:
        sid = client.post("/api/chat/sessions",
                          json={"title": "截断"}).json()["id"]
        chat_mod._write_history(tmp_path / ".ra" / "sessions" / sid,
                                list(self.MSGS))
        return sid

    def test_truncate_keeps_prefix_and_reports_counts(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = self._session_with_four(tmp_path, client)

        resp = client.post(f"/api/chat/sessions/{sid}/truncate",
                           json={"keep": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["kept"] == 2

        detail = client.get(f"/api/chat/sessions/{sid}").json()
        assert [m["content"] for m in detail["messages"]] == ["问一", "答一"]

    def test_keep_zero_empties_history(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = self._session_with_four(tmp_path, client)

        resp = client.post(f"/api/chat/sessions/{sid}/truncate",
                           json={"keep": 0})
        assert resp.status_code == 200
        assert resp.json()["kept"] == 0
        assert client.get(f"/api/chat/sessions/{sid}").json()["messages"] == []

    def test_keep_missing_or_non_integer_is_422(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = self._session_with_four(tmp_path, client)
        url = f"/api/chat/sessions/{sid}/truncate"

        assert client.post(url, json={}).status_code == 422  # keep 缺失
        assert client.post(url, content=b"",
                           headers={"Content-Type": "application/json"},
                           ).status_code == 422  # 空 body 同口径
        assert client.post(url, json={"keep": "abc"}).status_code == 422
        assert client.post(url, json={"keep": None}).status_code == 422
        assert client.post(url, json={"keep": -1}).status_code == 422
        # 非法请求不破坏原历史
        detail = client.get(f"/api/chat/sessions/{sid}").json()
        assert len(detail["messages"]) == 4

    def test_unknown_session_404(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        resp = client.post("/api/chat/sessions/ghost/truncate",
                           json={"keep": 1})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# F. 编辑用户消息：PATCH …/messages/{index}（wire 字段 text）
# ---------------------------------------------------------------------------


class TestEditUserMessage:
    def _session(self, tmp_path: Path, client: TestClient) -> str:
        sid = client.post("/api/chat/sessions",
                          json={"title": "编辑"}).json()["id"]
        chat_mod._write_history(
            tmp_path / ".ra" / "sessions" / sid,
            [{"role": "user", "content": "旧问题"},
             {"role": "assistant", "content": "旧回答"}])
        return sid

    def test_edit_rewrites_user_message_in_place(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = self._session(tmp_path, client)

        resp = client.patch(f"/api/chat/sessions/{sid}/messages/0",
                            json={"text": "新问题"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "index": 0}

        detail = client.get(f"/api/chat/sessions/{sid}").json()
        assert detail["messages"][0]["content"] == "新问题"
        assert detail["messages"][1]["content"] == "旧回答"  # 其余条目不动

    def test_edit_assistant_entry_422(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = self._session(tmp_path, client)

        resp = client.patch(f"/api/chat/sessions/{sid}/messages/1",
                            json={"text": "篡改回答"})
        assert resp.status_code == 422
        # 拒绝之外不产生副作用
        detail = client.get(f"/api/chat/sessions/{sid}").json()
        assert detail["messages"][1]["content"] == "旧回答"

    def test_edit_blank_and_overlong_422(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = self._session(tmp_path, client)
        url = f"/api/chat/sessions/{sid}/messages/0"

        assert client.patch(url, json={"text": "   "}).status_code == 422
        assert client.patch(url, json={"text": "超" * 8001}).status_code == 422
        detail = client.get(f"/api/chat/sessions/{sid}").json()
        assert detail["messages"][0]["content"] == "旧问题"


# ---------------------------------------------------------------------------
# G. 附件上传与引用围栏
# ---------------------------------------------------------------------------


class TestAttachmentUploadAndFence:
    def test_upload_sanitizes_name_and_persists_under_uploads(self, tmp_path):
        app = _make_app(tmp_path)
        client = TestClient(app)
        sid = client.post("/api/chat/sessions",
                          json={"title": "附件"}).json()["id"]

        resp = client.post(
            f"/api/chat/sessions/{sid}/attachments",
            files={"file": ("a/b..\\c:t.txt", b"hello", "text/plain")},
        )
        assert resp.status_code == 200
        files = resp.json()["files"]
        assert len(files) == 1
        up = files[0]
        # 消毒：目录成分剥除（basename），冒号（NTFS ADS 形态）替换为下划线
        assert up["name"] == "c_t.txt"
        assert ":" not in up["name"] and "/" not in up["name"]
        assert up["size"] == 5

        stored = Path(up["path"])
        assert stored.is_file()
        assert stored.read_bytes() == b"hello"
        assert stored.parent == tmp_path / "outputs" / sid / "uploads"
        # 落盘名带 时间戳_序号_ 前缀，且不含任何路径分隔符 / 冒号
        assert stored.name.endswith("_c_t.txt")
        assert not any(ch in stored.name for ch in "\\/:")

    def test_send_reference_roundtrip_and_out_of_fence_rejected(
            self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        prompts: list[str] = []

        async def behavior(kw):
            prompts.append(kw["prompt"])
            await kw["on_text"]("收到附件")
            return AgentResult(text_output="收到附件", stop_reason="completed")

        _install_fakes(monkeypatch, behavior)
        with TestClient(app) as client:
            sid = client.post("/api/chat/sessions",
                              json={"title": "围栏"}).json()["id"]
            up = client.post(
                f"/api/chat/sessions/{sid}/attachments",
                files={"file": ("notes.txt", b"data", "text/plain")},
            ).json()["files"][0]

            # 合法引用（本会话 uploads 内）：正常开轮
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({
                    "action": "user",
                    "text": "总结附件",
                    "attachments": [{"name": up["name"], "path": up["path"]}],
                })
                frames = _collect_until(ws, ("result",))
            assert not [f for f in frames if f["type"] == "error"]
            atts = _messages(tmp_path, sid)[0]["attachments"]
            # 围栏回写的是 safe_resolve 规范化后的绝对路径
            expected_path = str(Path(up["path"]).resolve())
            assert atts == [{"name": up["name"], "path": expected_path}]

            assert _wait_until(lambda: sid not in chat_mod._ACTIVE)

            # 越界引用（工作区内、但不在本会话 uploads）：error 帧且不开轮
            outside = tmp_path / "outside.txt"
            outside.write_text("x", encoding="utf-8")
            calls_before = len(prompts)
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({
                    "action": "user",
                    "text": "偷看外面",
                    "attachments": [{"name": "evil.txt", "path": str(outside)}],
                })
                err = ws.receive_json()
            assert err["type"] == "error"
            assert "越界" in err["message"]
            assert sid not in chat_mod._ACTIVE   # 未开新轮
            assert len(prompts) == calls_before  # 假循环未被再次调用


# ---------------------------------------------------------------------------
# H. 运行中发第二条 user：按 steer 注入运行中的回合
# ---------------------------------------------------------------------------


class TestSecondUserAsSteer:
    def test_second_user_message_injected_as_steer(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)

        async def behavior(kw):
            got = None
            try:
                got = await asyncio.wait_for(kw["steer_queue"].get(), timeout=3)
            except asyncio.TimeoutError:
                pass
            await kw["on_text"](f"steer={got}")
            return AgentResult(text_output=f"steer={got}",
                               stop_reason="completed")

        _install_fakes(monkeypatch, behavior)
        sid = "dura-h"
        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({"action": "user", "text": "第一条"})
                # 回合运行中：第二条 user 不开新轮，而是转入 steer 队列
                ws.send_json({"action": "user", "text": "第二条"})
                frames = _collect_until(ws, ("result",))

        deltas = [f["delta"] for f in frames if f["type"] == "text"]
        assert deltas == ["steer=第二条"]


# ---------------------------------------------------------------------------
# I. 跨回合 seq 单调：attach 游标过滤的跨回合前提
# ---------------------------------------------------------------------------


class TestSeqMonotonicAcrossTurns:
    """第二回合的帧 seq 必须续接第一回合，不得归零。

    缺陷背景：seq 原挂在每回合新建的 _TurnHandle 上，第二回合从 1 重来——
    前端 lastSeq 游标停在第一回合末值，断线重连 attach(after=游标) 会把
    整个新回合一帧不剩地滤掉。该缺陷被单回合协议测试集体放过（各测试均
    在全新会话首回合内验证），最终由真实浏览器 E2E 抓出；此处固化回归。
    """

    def test_second_turn_seq_continues_from_first(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        _install_fakes(monkeypatch, _happy_behavior)
        with TestClient(app) as client:
            sid = client.post("/api/chat/sessions",
                              json={"title": "跨回合游标"}).json()["id"]
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws:
                assert ws.receive_json()["type"] == "connected"

                ws.send_json({"action": "user", "text": "第一问"})
                first = _collect_until(ws, ("result",))
                first_seqs = [f["seq"] for f in frames_with_seq(first)]
                assert first_seqs, "第一回合未收到任何带 seq 的帧"
                first_max = max(first_seqs)

                # 同一连接直接开第二回合：游标必须只增不减
                ws.send_json({"action": "user", "text": "第二问"})
                second = _collect_until(ws, ("result",))

        second_seqs = [f["seq"] for f in frames_with_seq(second)]
        assert second_seqs, "第二回合未收到任何带 seq 的帧"
        assert min(second_seqs) > first_max, (
            f"seq 跨回合归零：第一回合最大 {first_max}，第二回合 {second_seqs}"
        )


def frames_with_seq(frames: list[dict]) -> list[dict]:
    return [f for f in frames if isinstance(f.get("seq"), int)]


class TestLiveTailAfterAttach:
    """attach 之后同一回合新产生的帧必须路由到（重）连接的 socket。

    缺陷背景：_emit 曾闭包绑死「发起回合的那条连接」——断连重连后 attach
    只能一次性回放快照，其后产生的直播尾流仍发往尸体 socket，前端按
    「attach 后直播帧继续到达」等待，UI 永久停在「思考中」。修复后发射
    路由按 sid 现查 _SINKS，尾流跟人走。对抗性审查的运行时复现场景固化。
    """

    def test_frames_emitted_after_attach_reach_new_socket(
        self, tmp_path, monkeypatch
    ):
        app = _make_app(tmp_path)
        gate = threading.Event()

        async def behavior(kw):
            await kw["on_text"]("前半")
            # conn2 完成 attach 之后主线程才放行——「后半」必然产生于
            # 回放窗口之外，只能走直播路由
            while not gate.is_set():
                await asyncio.sleep(0.01)
            await kw["on_text"]("后半")
            return AgentResult(text_output="前半后半",
                               stop_reason="completed", turns=1)

        _install_fakes(monkeypatch, behavior)
        sid = "dura-live"

        with TestClient(app) as client:
            with client.websocket_connect(f"/ws/chat?session={sid}") as ws1:
                assert ws1.receive_json()["type"] == "connected"
                ws1.send_json({"action": "user", "text": "长任务"})
                cursor = 0
                for _ in range(100):
                    frame = ws1.receive_json()
                    if frame.get("type") == "text" and frame.get("delta") == "前半":
                        cursor = frame["seq"]
                        break
                assert cursor > 0, "未收到断点前的「前半」帧"
            # conn1 退场；回合照跑、卡在闸门前

            with client.websocket_connect(f"/ws/chat?session={sid}") as ws2:
                assert ws2.receive_json()["type"] == "connected"
                ws2.send_json({"action": "attach", "after": cursor})
                replayed = _collect_until(ws2, ("replay_end",))
                # 游标已含「前半」：回放不得重复发放它
                assert all(
                    f.get("delta") != "前半" for f in replayed if f["type"] == "text"
                ), f"游标后的回放重复了已收帧：{replayed}"

                gate.set()  # 此刻之后的帧只能靠直播路由到达 ws2
                live = _collect_until(ws2, ("result",))

        texts = [f["delta"] for f in replayed + live if f["type"] == "text"]
        assert texts.count("后半") == 1, f"直播尾流丢失或重复：{texts}"
        assert any(f["type"] == "result" for f in live), "终态帧未送达重连方"
        # 回放段 + 直播段合并看，seq 严格递增且无重复——跨源帧序保证
        seqs = [f["seq"] for f in frames_with_seq(replayed + live)]
        assert seqs == sorted(set(seqs)), f"跨源帧序被破坏：{seqs}"


# ---------------------------------------------------------------------------
# J. 扩展字段活过「读→追加→整份写回」循环
# ---------------------------------------------------------------------------


class TestStructuredFieldsSurviveRewrite:
    """attachments / partial 不得被历史读归约剥掉。

    缺陷背景：_read_history 曾把条目投影成裸 {role, content}，而回合收尾
    的 done 条目写走「读→追加→整份写」，等于每回合结束都清洗一次历史——
    user 条目的 attachments 在第一个回合结束后即蒸发。真实浏览器 E2E 抓出。
    """

    def test_attachments_survive_completed_turn(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path)
        uploads = tmp_path / "outputs" / "dura-j" / "uploads"
        uploads.mkdir(parents=True)
        att_file = uploads / "0_0_说明.txt"
        att_file.write_text("x", encoding="utf-8")
        atts = [{"name": "说明.txt", "path": str(att_file)}]

        async def behavior(kw):
            await kw["on_text"]("收到")
            return AgentResult(text_output="收到", stop_reason="completed")

        _install_fakes(monkeypatch, behavior)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/chat?session=dura-j") as ws:
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({"action": "user", "text": "看附件", "attachments": atts})
                frames = _collect_until(ws, ("result",))

        assert any(f["type"] == "result" for f in frames), "回合未完成"
        msgs = _messages(tmp_path, "dura-j")
        assert msgs[0]["role"] == "user"
        # 关键断言：done 条目写回之后，user 条目的 attachments 仍在
        assert msgs[0].get("attachments") == [
            {"name": "说明.txt", "path": str(att_file)}
        ], f"attachments 被历史写回清洗：{msgs[0]}"
        assert msgs[-1]["role"] == "assistant"
