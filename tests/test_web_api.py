"""Tests for the extended web API (frontend-redesign B1-B8).

Covers: /api/runs history list, /api/runs/{name}/events tail-read,
/api/papers/{name}/export zip download, enhanced /api/status, WS steer
injection, WS resume_run, and steer_queue/usage plumbing through
generate_paper (single) and the pipeline runner.

App construction mirrors test_web_stop.py: bare FastAPI + hand-wired
app.state, avoiding the real lifespan (skill setup).
"""

import asyncio
import io
import json
import platform
import zipfile
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.agent import AgentResult  # noqa: E402
from research_assistant.kernel.budget import BudgetLimits  # noqa: E402
from research_assistant.session.store import SessionStore  # noqa: E402
from research_assistant.web.routes import router as api_router  # noqa: E402
from research_assistant.web.ws import router as ws_router  # noqa: E402
from tests.test_pipeline import _make_fake_agent  # noqa: E402

RUN_STATE = {
    "schema_version": 1,
    "session_id": "x",
    "query": "测试查询",
    "model": "test-model",
    "mode": "pipeline",
    "stage": "assemble",
    "status": "running",
    "stages": {"plan": {"status": "done"}, "assemble": {"status": "running"}},
    "budget": {"cost_usd": 0.42, "total_tokens": 1234, "turns": 9},
    "created_at": 1000.0,
    "updated_at": 2000.0,
}


def _make_app(tmp_path: Path) -> tuple[FastAPI, Path]:
    """Bare app with hand-wired state (no lifespan / skill setup)."""
    out = tmp_path / "writing_outputs"
    out.mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.state.model = "test-model"
    app.state.output_folder = out
    app.state.active_tasks = {}
    return app, out


def _make_ws_app(tmp_path: Path) -> tuple[FastAPI, Path]:
    out = tmp_path / "writing_outputs"
    out.mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    app.include_router(ws_router)
    app.state.cwd = tmp_path
    app.state.model = "test-model"
    app.state.output_folder = out
    app.state.active_tasks = {}
    return app, out


def _make_run(
    out: Path,
    name: str,
    *,
    state: dict | None = None,
    corrupt: bool = False,
    events: list | None = None,
    files: list[tuple[str, object]] | None = None,
) -> Path:
    """Create a paper directory under *out* with optional run state/files."""
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    if corrupt:
        (d / "run.json").write_text("{not json", encoding="utf-8")
    elif state is not None:
        (d / "run.json").write_text(
            json.dumps(state, ensure_ascii=False), encoding="utf-8")
    if events is not None:
        lines = [
            e if isinstance(e, str) else json.dumps(e, ensure_ascii=False)
            for e in events
        ]
        (d / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for rel, content in files or []:
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content if isinstance(content, bytes) else str(content).encode())
    return d


def _events(n: int) -> list[dict]:
    return [{"ts": float(i), "kind": f"k{i}", "data": {"i": i}} for i in range(n)]


# ---------------------------------------------------------------------------
# B1: GET /api/runs
# ---------------------------------------------------------------------------

class TestRunsList:
    def test_run_with_state_merged(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "20260101_000000_fem", state=RUN_STATE)
        client = TestClient(app)

        runs = client.get("/api/runs").json()
        assert len(runs) == 1
        item = runs[0]
        assert item["name"] == "20260101_000000_fem"
        assert item["query"] == "测试查询"
        assert item["mode"] == "pipeline"
        assert item["status"] == "running"
        assert item["stage"] == "assemble"
        assert item["stages"] == {"plan": "done", "assemble": "running"}
        assert item["budget"] == {
            "cost_usd": 0.42, "total_tokens": 1234, "turns": 9}
        assert item["created_at"] == 1000.0
        assert item["updated_at"] == 2000.0
        assert item["paper"]["name"] == "20260101_000000_fem"

    def test_legacy_dir_without_run_json(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "old_paper_dir", files=[("drafts/a.txt", "x")])
        client = TestClient(app)

        runs = client.get("/api/runs").json()
        assert len(runs) == 1
        item = runs[0]
        assert item["status"] == "legacy"
        assert item["stages"] == {}
        assert item["budget"] is None
        assert item["paper"]["name"] == "old_paper_dir"

    def test_corrupt_run_json_tolerated(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "broken", corrupt=True)
        client = TestClient(app)

        runs = client.get("/api/runs").json()
        assert len(runs) == 1
        assert runs[0]["status"] == "legacy"

    def test_sorted_newest_first_and_hidden_skipped(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "20260101_000000_aaa", state=RUN_STATE)
        _make_run(out, "20260202_000000_bbb", state=RUN_STATE)
        _make_run(out, ".hidden", state=RUN_STATE)
        client = TestClient(app)

        runs = client.get("/api/runs").json()
        names = [r["name"] for r in runs]
        assert names == ["20260202_000000_bbb", "20260101_000000_aaa"]

    def test_traversal_name_rejected_by_validator(self, tmp_path):
        from research_assistant.web.routes import _safe_run_dir

        with pytest.raises(ValueError):
            _safe_run_dir(tmp_path, "../escape")
        with pytest.raises(ValueError):
            _safe_run_dir(tmp_path, "a\\b")
        with pytest.raises(ValueError):
            _safe_run_dir(tmp_path, "")

    def test_events_endpoint_rejects_bad_names(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "ok", state=RUN_STATE)
        client = TestClient(app)

        # 冒号在 URL path 段中合法但被校验器拒绝（Windows 盘符/ADS 防御）
        resp = client.get("/api/runs/C:baddir/events")
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# B2: GET /api/runs/{name}/events
# ---------------------------------------------------------------------------

class TestRunEvents:
    def test_full_tail_default(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "r1", state=RUN_STATE, events=_events(5))
        client = TestClient(app)

        data = client.get("/api/runs/r1/events").json()
        assert data["total"] == 5
        assert [e["kind"] for e in data["events"]] == [
            "k0", "k1", "k2", "k3", "k4"]

    def test_incremental_after(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "r1", state=RUN_STATE, events=_events(5))
        client = TestClient(app)

        data = client.get("/api/runs/r1/events", params={"after": 2}).json()
        assert data["total"] == 5
        assert [e["kind"] for e in data["events"]] == ["k2", "k3", "k4"]

        data = client.get("/api/runs/r1/events", params={"after": 99}).json()
        assert data["total"] == 5
        assert data["events"] == []

    def test_tail_window(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "r1", state=RUN_STATE, events=_events(6))
        client = TestClient(app)

        data = client.get("/api/runs/r1/events", params={"tail": 2}).json()
        assert data["total"] == 6
        assert [e["kind"] for e in data["events"]] == ["k4", "k5"]

    def test_missing_events_file_returns_empty(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "r1", state=RUN_STATE)
        client = TestClient(app)

        data = client.get("/api/runs/r1/events").json()
        assert data == {"total": 0, "events": []}

    def test_bad_lines_skipped(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "r1", state=RUN_STATE, events=[
            '{"ts": 1, "kind": "a", "data": {}}',
            "THIS IS NOT JSON",
            '{"ts": 2, "kind": "b", "data": {}}',
        ])
        client = TestClient(app)

        data = client.get("/api/runs/r1/events").json()
        assert data["total"] == 2
        assert [e["kind"] for e in data["events"]] == ["a", "b"]

    def test_unknown_run_404(self, tmp_path):
        app, _ = _make_app(tmp_path)
        client = TestClient(app)
        assert client.get("/api/runs/ghost/events").status_code == 404


# ---------------------------------------------------------------------------
# B6: GET /api/papers/{name}/export
# ---------------------------------------------------------------------------

class TestPaperExport:
    def test_zip_download_content_and_skips(self, tmp_path):
        app, out = _make_app(tmp_path)
        _make_run(out, "zipme", state=RUN_STATE, files=[
            ("drafts/v1_draft.docx", b"docx-bytes"),
            ("figures/f.png", b"\x89PNG"),
            ("sources/note.md", "hello"),
            (".ra/artifacts/manifest.json", "{}"),
            ("__pycache__/mod.pyc", b"junk"),
        ])
        client = TestClient(app)

        resp = client.get("/api/papers/zipme/export")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert resp.headers["content-disposition"] == \
            'attachment; filename="zipme.zip"'

        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = set(zf.namelist())
        assert "drafts/v1_draft.docx" in names
        assert "figures/f.png" in names
        assert "sources/note.md" in names
        assert zf.read("sources/note.md") == b"hello"
        assert not any(n.startswith(".ra/") for n in names)
        assert not any("__pycache__" in n for n in names)

    def test_export_unknown_paper_404(self, tmp_path):
        app, _ = _make_app(tmp_path)
        client = TestClient(app)
        assert client.get("/api/papers/ghost/export").status_code == 404


# ---------------------------------------------------------------------------
# B7: GET /api/status 增强
# ---------------------------------------------------------------------------

class TestStatusEnhanced:
    def test_new_fields_present(self, tmp_path):
        app, out = _make_app(tmp_path)
        client = TestClient(app)

        data = client.get("/api/status").json()
        for key in ("model", "output_folder", "active_tasks", "provider",
                    "base_url_host", "approval_mode", "permission_mode",
                    "repeat_limit", "pipeline", "auto_continue", "version",
                    "python"):
            assert key in data, f"missing status field: {key}"
        assert data["python"] == platform.python_version()
        assert isinstance(data["repeat_limit"], int)

    def test_env_values_reported_and_url_sanitized(self, tmp_path, monkeypatch):
        monkeypatch.setenv("RA_APPROVAL_MODE", "interactive")
        monkeypatch.delenv("RA_PERMISSION_MODE", raising=False)
        monkeypatch.setenv("RA_REPEAT_TOOL_LIMIT", "7")
        monkeypatch.delenv("RA_PIPELINE", raising=False)
        monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1?api_key=secret")
        app, _ = _make_app(tmp_path)
        client = TestClient(app)

        resp = client.get("/api/status")
        data = resp.json()
        assert data["approval_mode"] == "interactive"
        assert data["permission_mode"] == "deny_dangerous"
        assert data["repeat_limit"] == 7
        assert data["pipeline"] is True
        assert data["base_url_host"] == "api.example.com"
        assert "secret" not in resp.text

    def test_provider_detected_without_leaking_key(self, tmp_path, monkeypatch):
        import research_assistant.web.routes as routes_mod

        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setattr(
            routes_mod, "get_api_key", lambda key=None: "sk-ant-abc123")
        app, _ = _make_app(tmp_path)
        client = TestClient(app)
        assert client.get("/api/status").json()["provider"] == "anthropic"

        monkeypatch.setattr(
            routes_mod, "get_api_key", lambda key=None: "sk-other-key")
        assert client.get("/api/status").json()["provider"] == "openai"


# ---------------------------------------------------------------------------
# B4: WS steer 注入
# ---------------------------------------------------------------------------

class TestWsSteer:
    def test_steer_delivered_to_generation(self, tmp_path, monkeypatch):
        app, _ = _make_ws_app(tmp_path)
        captured: dict = {}
        steered: list = []

        async def fake_generate(**kwargs):
            captured.update(kwargs)
            q = kwargs.get("steer_queue")
            if q is not None:
                try:
                    steered.append(await asyncio.wait_for(q.get(), timeout=10))
                except asyncio.TimeoutError:
                    pass
            yield {"type": "progress", "stage": "initialization", "message": "w"}

        monkeypatch.setattr("research_assistant.web.ws.generate_paper", fake_generate)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/generate") as ws:
                ws.send_json({"action": "start", "query": "写论文"})
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({"action": "steer", "message": "改为英文"})
                msgs = []
                while True:
                    m = ws.receive_json()
                    msgs.append(m)
                    if m["type"] == "done":
                        break
        assert not any(m["type"] == "error" for m in msgs), msgs
        assert {"type": "steer_ok"} in msgs
        assert steered == ["改为英文"]
        assert captured.get("steer_queue") is not None

    def test_oversize_steer_rejected(self, tmp_path, monkeypatch):
        app, _ = _make_ws_app(tmp_path)
        captured: dict = {}

        async def fake_generate(**kwargs):
            captured.update(kwargs)
            # 留出事件循环窗口，让 pump 有机会处理客户端消息（内存发送不真正挂起）
            await asyncio.sleep(0.05)
            yield {"type": "progress", "stage": "initialization", "message": "w"}
            await asyncio.sleep(0.05)

        monkeypatch.setattr("research_assistant.web.ws.generate_paper", fake_generate)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/generate") as ws:
                ws.send_json({"action": "start", "query": "q"})
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({"action": "steer", "message": "长" * 3000})
                msgs = []
                while True:
                    m = ws.receive_json()
                    msgs.append(m)
                    if m["type"] == "done":
                        break
        assert any(
            m["type"] == "error" and "过长" in m["message"] for m in msgs), msgs
        assert captured["steer_queue"].empty()

    def test_empty_steer_rejected(self, tmp_path, monkeypatch):
        app, _ = _make_ws_app(tmp_path)
        captured: dict = {}

        async def fake_generate(**kwargs):
            captured.update(kwargs)
            await asyncio.sleep(0.05)
            yield {"type": "progress", "stage": "initialization", "message": "w"}
            await asyncio.sleep(0.05)

        monkeypatch.setattr("research_assistant.web.ws.generate_paper", fake_generate)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/generate") as ws:
                ws.send_json({"action": "start", "query": "q"})
                assert ws.receive_json()["type"] == "connected"
                ws.send_json({"action": "steer", "message": "   "})
                msgs = []
                while True:
                    m = ws.receive_json()
                    msgs.append(m)
                    if m["type"] == "done":
                        break
        assert any(m["type"] == "error" for m in msgs), msgs


# ---------------------------------------------------------------------------
# B3: WS resume_run 断点续跑
# ---------------------------------------------------------------------------

class TestWsResume:
    def test_resume_reuses_dir_and_forces_multi_agent(self, tmp_path, monkeypatch):
        app, out = _make_ws_app(tmp_path)
        run_dir = _make_run(out, "20260101_000000_fem")
        SessionStore.create(run_dir, query="续跑查询", model="m", mode="pipeline")

        captured: dict = {}

        async def fake_generate(**kwargs):
            captured.update(kwargs)
            yield {"type": "progress", "stage": "initialization", "message": "w"}

        monkeypatch.setattr("research_assistant.web.ws.generate_paper", fake_generate)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/generate") as ws:
                ws.send_json({"action": "start", "resume_run": "20260101_000000_fem"})
                hello = ws.receive_json()
                assert hello["type"] == "connected"
                assert hello["resumed"] == "20260101_000000_fem"
                msgs = []
                while True:
                    m = ws.receive_json()
                    msgs.append(m)
                    if m["type"] in ("done", "error"):
                        break
        assert msgs[-1]["type"] == "done", msgs
        assert captured["multi_agent"] is True
        assert captured["output_dir"] == str(run_dir)
        assert captured["query"] == "续跑查询"

    def test_resume_unknown_dir_errors(self, tmp_path, monkeypatch):
        app, _ = _make_ws_app(tmp_path)

        async def fake_generate(**kwargs):  # pragma: no cover - 不应被调用
            raise AssertionError("generate_paper must not run")
            yield {}

        monkeypatch.setattr("research_assistant.web.ws.generate_paper", fake_generate)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/generate") as ws:
                ws.send_json({"action": "start", "resume_run": "ghost"})
                assert ws.receive_json()["type"] == "error"

    def test_resume_legacy_without_query_rejected(self, tmp_path, monkeypatch):
        app, out = _make_ws_app(tmp_path)
        _make_run(out, "legacy_run",
                  state={"mode": "pipeline", "status": "complete"})

        started: list = []

        async def fake_generate(**kwargs):
            started.append(True)  # pragma: no cover - 不应被调用
            yield {}

        monkeypatch.setattr("research_assistant.web.ws.generate_paper", fake_generate)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/generate") as ws:
                ws.send_json({"action": "start", "resume_run": "legacy_run"})
                err = ws.receive_json()
        assert err["type"] == "error"
        assert "query" in err["message"]
        assert started == []

    def test_resume_traversal_rejected(self, tmp_path, monkeypatch):
        app, out = _make_ws_app(tmp_path)
        _make_run(out, "victim", state=RUN_STATE)

        async def fake_generate(**kwargs):  # pragma: no cover - 不应被调用
            raise AssertionError("generate_paper must not run")
            yield {}

        monkeypatch.setattr("research_assistant.web.ws.generate_paper", fake_generate)
        with TestClient(app) as client:
            with client.websocket_connect("/ws/generate") as ws:
                ws.send_json({"action": "start", "resume_run": "../victim"})
                assert ws.receive_json()["type"] == "error"


# ---------------------------------------------------------------------------
# B4/B5: generate_paper 与 runner 的透传
# ---------------------------------------------------------------------------

class TestSteerPlumbing:
    async def test_single_mode_passes_steer_queue_and_usage_frames(
            self, tmp_path, monkeypatch):
        import research_assistant.api as api_mod

        captured: dict = {}

        class FakeAgent:
            def __call__(self, *args, **kwargs):
                captured.update(kwargs)
                return self._run()

            async def _run(self):
                return AgentResult(text_output="done")

        monkeypatch.setattr(api_mod, "setup_claude_skills", lambda *a, **k: None)
        monkeypatch.setattr(api_mod, "run_agent", FakeAgent())
        out_dir = tmp_path / "writing_outputs" / "paper"
        out_dir.mkdir(parents=True)
        monkeypatch.setattr(api_mod, "_find_most_recent_output",
                            lambda folder, start: out_dir)

        q = asyncio.Queue()
        updates = [u async for u in api_mod.generate_paper(
            query="q", cwd=str(tmp_path), api_key="k",
            budget_limits=BudgetLimits(max_turns=100), steer_queue=q,
        )]

        assert captured.get("steer_queue") is q
        usage = [u for u in updates if u.get("type") == "usage"]
        assert usage, "single 模式应推送至少一帧 usage"
        assert all(isinstance(u.get("budget"), dict) for u in usage)
        assert all("cost_usd" in u["budget"] for u in usage)
        assert updates[-1].get("type") == "result"

    async def test_run_stage_agent_forwards_steer_queue(self, tmp_path, monkeypatch):
        import research_assistant.pipeline.runner as runner_mod
        from research_assistant.kernel.budget import BudgetGuard
        from research_assistant.kernel.events import HookBus

        captured: dict = {}

        async def fake_run_agent(**kwargs):
            captured.update(kwargs)
            return AgentResult(stop_reason="completed")

        monkeypatch.setattr(runner_mod, "run_agent", fake_run_agent)
        q = asyncio.Queue()
        await runner_mod._run_stage_agent(
            "plan", "p", "s",
            model="m", work_dir=tmp_path, api_key="k", base_url=None,
            provider=None, budget=BudgetGuard(model="m"), hooks=HookBus(),
            cancel_event=None, steer_queue=q,
        )
        assert captured["steer_queue"] is q

    async def test_pipeline_shares_queue_and_streams_usage(
            self, tmp_path, monkeypatch):
        """假 agent 全流程：每个阶段都收到同一个 steer_queue 且有 usage 帧。"""
        calls: list = []
        seen_queues: list = []

        async def recording_fake(*args, **kwargs):
            seen_queues.append(kwargs.get("steer_queue"))
            return await base_fake(*args, **kwargs)

        base_fake = _make_fake_agent(calls, {})
        monkeypatch.setattr(
            "research_assistant.pipeline.runner._run_stage_agent", recording_fake)

        import research_assistant.gates as gates_pkg
        from research_assistant.gates import GateResult

        class StubCitationGate(gates_pkg.CitationGate):
            async def run(self, context):
                return GateResult(name="citations", passed=True,
                                  details={"stubbed": True})

        monkeypatch.setattr(gates_pkg, "CitationGate", StubCitationGate)

        from research_assistant.pipeline.runner import run_pipeline

        q = asyncio.Queue()
        updates = []
        async for u in run_pipeline(
            query="write a fem paper", model="test-model",
            work_dir=tmp_path, output_dir=tmp_path / "writing_outputs" / "run",
            steer_queue=q,
        ):
            updates.append(u)

        assert calls, "pipeline 应至少运行一个阶段"
        assert seen_queues and all(sq is q for sq in seen_queues)
        usage = [u for u in updates if u.get("type") == "usage"]
        assert usage, "pipeline 模式应推送至少一帧 usage"
        assert all(isinstance(u.get("budget"), dict) for u in usage)
        assert any(u.get("type") == "result" for u in updates)


class TestSingleAgentWriteAnchor:
    """R12 P2/B5：单代理模式的写入归巢——write_anchor=paper 输出目录。"""

    async def test_single_mode_threads_paper_dir_as_anchor(
            self, tmp_path, monkeypatch):
        import research_assistant.api as api_mod

        captured: dict = {}

        class FakeAgent:
            def __call__(self, *args, **kwargs):
                captured.update(kwargs)
                return self._run()

            async def _run(self):
                return AgentResult(text_output="done")

        monkeypatch.setattr(api_mod, "setup_claude_skills", lambda *a, **k: None)
        monkeypatch.setattr(api_mod, "run_agent", FakeAgent())
        out_dir = tmp_path / "writing_outputs" / "paper"
        out_dir.mkdir(parents=True)

        updates = [u async for u in api_mod.generate_paper(
            query="q", cwd=str(tmp_path), api_key="k",
            output_dir=str(out_dir),
        )]

        assert updates[-1].get("type") == "result"
        tools = captured["tools"]
        assert tools.write_anchor == str(out_dir)
        assert tools.work_dir == str(tmp_path)  # sandbox 围栏仍是工作区根
