"""Tests for R8 runtime workspace switch (POST /api/workspace/root).

切换通过 app.state 落地，不改变进程 CWD。全局配置目录经 isolated_appdata
重定向到 tmp，防止读写真实 %APPDATA%。
"""

import os
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.web.workspace import (  # noqa: E402
    router as workspace_router,
)


@pytest.fixture()
def client(tmp_path, monkeypatch, isolated_appdata):
    monkeypatch.chdir(tmp_path)
    app = FastAPI()
    app.include_router(workspace_router, prefix="/api")
    app.state.cwd = tmp_path.resolve()
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.active_tasks = {}
    yield TestClient(app)


def _switch(client: TestClient, path: str):
    return client.post("/api/workspace/root", json={"path": path})


class TestSwitchRoot:
    def test_switch_roundtrip(self, tmp_path, client):
        target = tmp_path / "workspace_b"
        target.mkdir()

        resp = _switch(client, str(target))

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert Path(body["root"]) == target.resolve()
        # 输出目录随新根创建；state 同步刷新
        assert (target / "writing_outputs").is_dir()
        assert client.app.state.output_folder == target / "writing_outputs"
        assert client.app.state.cwd == target.resolve()
        assert Path(os.getcwd()) == tmp_path.resolve()  # 进程级 CWD 不受影响
        # 名片端点跟随新根
        card = client.get("/api/workspace").json()
        assert Path(card["root"]) == target.resolve()
        assert card["name"] == "workspace_b"

    def test_same_root_reports_unchanged(self, tmp_path, client):
        resp = _switch(client, str(tmp_path))
        assert resp.status_code == 200
        assert resp.json()["unchanged"] is True

    def test_empty_path_422(self, client):
        assert _switch(client, "   ").status_code == 422

    def test_relative_path_422(self, tmp_path, client):
        assert _switch(client, "relative/dir").status_code == 422

    def test_missing_dir_404(self, tmp_path, client):
        ghost = tmp_path / "ghost"
        assert _switch(client, str(ghost)).status_code == 404

    def test_running_generate_task_blocks_409(self, tmp_path, client):
        other = tmp_path / "elsewhere"
        other.mkdir()
        client.app.state.active_tasks["abc123"] = {"status": "running"}
        resp = _switch(client, str(other))
        assert resp.status_code == 409
        assert Path(os.getcwd()) == tmp_path.resolve()  # 未被切换

    def test_stopping_generate_task_blocks_too(self, tmp_path, client):
        other = tmp_path / "elsewhere2"
        other.mkdir()
        client.app.state.active_tasks["abc123"] = {"status": "stopping"}
        assert _switch(client, str(other)).status_code == 409

    def test_idle_chat_connection_does_not_block(self, tmp_path, client):
        # 会话连接持有旧工作区的绝对路径 ToolRegistry，跨根安全：
        # chat:* 条目不应阻止切换。
        other = tmp_path / "chat_ok"
        other.mkdir()
        client.app.state.active_tasks["chat:s1"] = {"status": "running"}
        resp = _switch(client, str(other))
        assert resp.status_code == 200
        assert Path(resp.json()["root"]) == other.resolve()
