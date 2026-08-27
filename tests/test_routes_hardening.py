"""routes 层加固回归：冻结态复现分流 / SVG 不再 inline / 重 IO 移出事件循环。

App 构造沿用 test_web_api.py 的「裸 FastAPI + 手工接线 state」风格，不触发
真实生命周期。注意：fire-and-forget 后台任务只在 ``with TestClient(...)``
持有的共享事件循环里存活——无上下文时请求结束即销毁 loop，任务不会执行，
因此所有涉及后台复现任务的断言都在上下文内轮询 store 落终态。
"""

import asyncio
import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import research_assistant.web.routes as routes_mod  # noqa: E402
from research_assistant.runtime import PlatformStore  # noqa: E402
from research_assistant.web.routes import router as api_router  # noqa: E402


def _make_app(tmp_path: Path):
    """裸应用：platform_store / project / output_folder 手工接好。"""
    out = tmp_path / "writing_outputs"
    out.mkdir(parents=True, exist_ok=True)
    app = FastAPI()
    app.include_router(api_router, prefix="/api")
    app.state.model = "test-model"
    app.state.output_folder = out
    app.state.cwd = tmp_path
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    app.state.platform_store = store
    app.state.project = project
    return app, out, store, project["id"]


def _spy_loop(monkeypatch: pytest.MonkeyPatch, owner, name) -> list[bool]:
    """包装 ``owner.name``，记录每次调用是否发生在事件循环线程上。

    True = 调用时当前线程有运行中的事件循环（重活仍卡在循环上）；
    经 asyncio.to_thread 下放的工作线程没有 loop，应为 False。
    """
    original = getattr(owner, name)
    flags: list[bool] = []

    def wrapped(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            flags.append(True)
        except RuntimeError:
            flags.append(False)
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, wrapped)
    return flags


def _wait_terminal(store: PlatformStore, project_id: str, run_id: str,
                   timeout: float = 30.0) -> dict:
    """轮询分析运行直到落终态（后台任务跑在 TestClient 的 loop 线程上）。"""
    deadline = time.monotonic() + timeout
    row = None
    while time.monotonic() < deadline:
        rows = store.list_analysis_runs(project_id, limit=500)
        row = next((r for r in rows if r.get("id") == run_id), None)
        if row and row.get("status") in {"complete", "failed"}:
            return row
        time.sleep(0.05)
    raise AssertionError(f"复现运行未在限时内落终态: {row}")


def _make_analysis_run(store: PlatformStore, project_id: str, script: Path) -> dict:
    return store.create_analysis_run(
        project_id=project_id, script_path=str(script),
        inputs={}, parameters={}, environment={},
    )


# ---------------------------------------------------------------------------
# B：SVG 不允许 inline 渲染（SVG 可内嵌 <script>，属 XSS 面）
# ---------------------------------------------------------------------------

class TestSvgNotInline:
    def test_svg_served_as_attachment(self, tmp_path, monkeypatch):
        app, out, _, _ = _make_app(tmp_path)
        run_dir = out / "svg_run"
        run_dir.mkdir(parents=True)
        (run_dir / "fig.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            "<script>alert(1)</script></svg>",
            encoding="utf-8",
        )
        # 固定 mime 解析结果，屏蔽 Windows 注册表差异
        monkeypatch.setattr(
            routes_mod.mimetypes, "guess_type",
            lambda p: ("image/svg+xml", None))
        client = TestClient(app)

        resp = client.get("/api/papers/svg_run/files/fig.svg")

        assert resp.status_code == 200
        disposition = resp.headers["content-disposition"].lower()
        assert disposition.startswith("attachment"), disposition


# ---------------------------------------------------------------------------
# A：分析复现端点冻结态分流（sys.executable 是应用自身 exe，禁止 subprocess）
# ---------------------------------------------------------------------------

class TestAnalysisRerunFrozenDispatch:
    def test_dev_mode_still_uses_subprocess(self, tmp_path, monkeypatch):
        """dev 态回归不变：真实子进程执行脚本，退出码/stdout 照旧入库。"""
        app, out, store, pid = _make_app(tmp_path)
        script = tmp_path / "analysis.py"
        script.write_text("print('repro-dev-ok')\n", encoding="utf-8")
        original = _make_analysis_run(store, pid, script)

        async def _must_not(*, script, cwd, env, timeout):  # pragma: no cover
            raise AssertionError("开发态不得进入冻结适配层")

        monkeypatch.setattr(routes_mod, "_run_reproduce_script_frozen", _must_not)

        with TestClient(app) as client:
            resp = client.post(f"/api/analysis/runs/{original['id']}/rerun")
            assert resp.status_code == 200, resp.text
            fresh_id = resp.json()["run"]["id"]
            row = _wait_terminal(store, pid, fresh_id)

        assert row["status"] == "complete"
        assert row["exit_code"] == 0
        assert "repro-dev-ok" in (row.get("stdout_preview") or "")

    def test_frozen_mode_routes_through_adapter_without_subprocess(
            self, tmp_path, monkeypatch):
        """冻结态：走 frozen 执行适配层，绝不 subprocess 启动应用自身。"""
        app, out, store, pid = _make_app(tmp_path)
        script = tmp_path / "analysis.py"
        script.write_text("print('must-not-run')\n", encoding="utf-8")
        original = _make_analysis_run(store, pid, script)

        calls: list[dict] = []

        async def fake_frozen(*, script, cwd, env, timeout):
            calls.append({"script": Path(script), "cwd": Path(cwd),
                          "env": dict(env), "timeout": timeout})
            return SimpleNamespace(returncode=0, stdout="froze-ok\n", stderr="")

        monkeypatch.setattr(routes_mod, "_is_frozen", lambda: True)
        monkeypatch.setattr(routes_mod, "_run_reproduce_script_frozen", fake_frozen)

        def _no_subprocess(*args, **kwargs):  # pragma: no cover
            raise AssertionError("冻结态禁止 subprocess.run 启动 sys.executable")

        monkeypatch.setattr(routes_mod.subprocess, "run", _no_subprocess)

        with TestClient(app) as client:
            resp = client.post(f"/api/analysis/runs/{original['id']}/rerun")
            assert resp.status_code == 200, resp.text
            fresh_id = resp.json()["run"]["id"]
            row = _wait_terminal(store, pid, fresh_id)

        assert len(calls) == 1
        assert calls[0]["script"].name == "analysis.py"
        assert calls[0]["cwd"] == tmp_path.resolve()
        assert calls[0]["env"].get("RA_ANALYSIS_RUN_ID") == fresh_id
        assert "RA_ANALYSIS_OUTPUT_DIR" in calls[0]["env"]
        assert calls[0]["timeout"] == 3600
        assert row["status"] == "complete"
        assert row["exit_code"] == 0
        assert "froze-ok" in (row.get("stdout_preview") or "")


class TestReproduceScriptDispatcher:
    def test_dev_branch_uses_sys_executable_with_silent_window(
            self, tmp_path, monkeypatch):
        """dev 分支契约：仍用 sys.executable + timeout + CREATE_NO_WINDOW。"""
        script = tmp_path / "noop.py"
        script.write_text("pass\n", encoding="utf-8")
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            captured.update(kwargs)
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        monkeypatch.setattr(routes_mod.subprocess, "run", fake_run)

        result = asyncio.run(routes_mod._run_reproduce_script(
            script=script, cwd=tmp_path, env={"A": "1"}, timeout=7))

        assert captured["cmd"][0] == sys.executable
        assert str(script) in captured["cmd"][1]
        assert captured["timeout"] == 7
        # Windows 静默防终端闪现；非 Windows 平台 getattr 回退为 0
        assert captured["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
        assert result.returncode == 0
        assert result.stdout == "ok"


class TestFrozenAdapterRealExec:
    """真跑 frozen_exec 执行器（spawn 子进程）验证薄适配层语义。"""

    def test_env_injection_and_zero_exit(self, tmp_path):
        script = tmp_path / "analysis.py"
        script.write_text(
            "import os\nprint('RUN', os.environ['RA_ANALYSIS_RUN_ID'])\n",
            encoding="utf-8")
        result = asyncio.run(routes_mod._run_reproduce_script_frozen(
            script=script, cwd=tmp_path,
            env={"RA_ANALYSIS_RUN_ID": "abc123"}, timeout=120))
        assert result.returncode == 0
        assert result.stderr == ""
        assert "RUN abc123" in result.stdout
        # 退出码标记文件必须清理干净
        assert not list(tmp_path.glob("_ra_repro_exit_*"))

    def test_system_exit_code_propagates(self, tmp_path):
        script = tmp_path / "exiter.py"
        script.write_text(
            "import sys\nprint('before')\nsys.exit(3)\n", encoding="utf-8")
        result = asyncio.run(routes_mod._run_reproduce_script_frozen(
            script=script, cwd=tmp_path, env={}, timeout=120))
        assert result.returncode == 3
        assert "before" in result.stdout

    def test_uncaught_exception_maps_to_exit_1(self, tmp_path):
        script = tmp_path / "crash.py"
        script.write_text("raise RuntimeError('kaboom-analysis')\n", encoding="utf-8")
        result = asyncio.run(routes_mod._run_reproduce_script_frozen(
            script=script, cwd=tmp_path, env={}, timeout=120))
        assert result.returncode == 1
        assert "kaboom-analysis" in result.stdout  # traceback 合并在输出里

    def test_timeout_maps_to_negative_exit(self, tmp_path, monkeypatch):
        """执行器超时被杀、退出码标记未落盘 → 对齐 dev 失败口径 exit=-1。"""

        async def fake_inprocess(code, timeout=120, cwd=".", workspace_root=None):
            assert timeout == 5
            return ""

        monkeypatch.setattr(
            "research_assistant.tools.frozen_exec.run_python_inprocess",
            fake_inprocess)
        script = tmp_path / "slow.py"
        script.write_text("pass\n", encoding="utf-8")
        result = asyncio.run(routes_mod._run_reproduce_script_frozen(
            script=script, cwd=tmp_path, env={}, timeout=5))
        assert result.returncode == -1


# ---------------------------------------------------------------------------
# C：async 端点内的同步重 IO 必须移出事件循环（to_thread），且响应契约不变
# ---------------------------------------------------------------------------

class TestHeavyIoOffEventLoop:
    def test_list_papers_off_loop_and_contract(self, tmp_path, monkeypatch):
        app, out, _, _ = _make_app(tmp_path)
        d = out / "20260101_000000_alpha"
        (d / "drafts").mkdir(parents=True)
        (d / "drafts" / "note.txt").write_text("x", encoding="utf-8")
        flags = _spy_loop(monkeypatch, routes_mod, "_paper_summary")
        client = TestClient(app)

        data = client.get("/api/papers").json()

        assert isinstance(data, list) and data
        assert data[0]["name"] == "20260101_000000_alpha"
        assert {"name", "topic", "status", "title", "word_count"} <= set(data[0])
        assert flags and all(not f for f in flags), \
            f"_paper_summary 仍跑在事件循环线程: {flags}"

    def test_export_project_off_loop_and_contract(self, tmp_path, monkeypatch):
        app, out, store, pid = _make_app(tmp_path)
        (tmp_path / "notes.md").write_text("workspace 文件", encoding="utf-8")
        flags = _spy_loop(monkeypatch, routes_mod.zipfile, "ZipFile")
        client = TestClient(app)

        resp = client.get("/api/project/export")

        assert resp.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert "research_manifest.json" in names
        assert "workspace/notes.md" in names
        assert flags and all(not f for f in flags), \
            f"zip 打包仍跑在事件循环线程: {flags}"

    def test_export_paper_zip_off_loop_and_contract(self, tmp_path, monkeypatch):
        app, out, _, _ = _make_app(tmp_path)
        d = out / "zipline"
        figs = d / "figures"
        figs.mkdir(parents=True)
        (figs / "f.png").write_bytes(b"\x89PNG")
        flags = _spy_loop(monkeypatch, routes_mod.zipfile, "ZipFile")
        client = TestClient(app)

        resp = client.get("/api/papers/zipline/export")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        assert "figures/f.png" in zf.namelist()
        assert flags and all(not f for f in flags), \
            f"zip 打包仍跑在事件循环线程: {flags}"

    def test_run_events_parse_off_loop_and_contract(self, tmp_path, monkeypatch):
        app, out, _, _ = _make_app(tmp_path)
        d = out / "evtrun"
        d.mkdir(parents=True)
        lines = [
            json.dumps({"ts": float(i), "kind": f"k{i}", "data": {}})
            for i in range(4)
        ]
        (d / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        flags = _spy_loop(monkeypatch, routes_mod.json, "loads")
        client = TestClient(app)

        data = client.get("/api/runs/evtrun/events").json()

        assert data["total"] == 4
        assert [e["kind"] for e in data["events"]] == ["k0", "k1", "k2", "k3"]
        assert flags and all(not f for f in flags), \
            f"events 解析仍跑在事件循环线程: {flags}"

    def test_delete_paper_rmtree_off_loop_and_contract(self, tmp_path, monkeypatch):
        app, out, _, _ = _make_app(tmp_path)
        d = out / "goner"
        d.mkdir(parents=True)
        (d / "a.txt").write_text("x", encoding="utf-8")
        flags = _spy_loop(monkeypatch, routes_mod.shutil, "rmtree")
        client = TestClient(app)

        resp = client.delete("/api/papers/goner")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert not d.exists()
        assert flags and all(not f for f in flags), \
            f"目录删除仍跑在事件循环线程: {flags}"
