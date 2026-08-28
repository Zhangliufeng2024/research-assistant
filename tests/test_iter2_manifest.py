"""迭代2：产物清单（manifest）+ artifacts 索引检索测试。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from research_assistant.runtime.platform_store import PlatformStore

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.web.chat import router as chat_router  # noqa: E402
from research_assistant.web.routes import router as platform_router  # noqa: E402


@pytest.fixture()
def store(tmp_path: Path) -> PlatformStore:
    s = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    s.ensure_project(tmp_path)
    return s


class TestArtifactsStore:
    def test_replace_and_search(self, store):
        entries = [
            {"path": "artifacts/能耗分析.docx", "name": "能耗分析.docx", "ext": ".docx", "size": 1024, "mtime": time.time()},
            {"path": "figures/f1.png", "name": "f1.png", "ext": ".png", "size": 2048, "mtime": time.time() - 10},
        ]
        assert store.replace_artifacts("s1", entries) == 2
        hits = store.search_artifacts("能耗")
        assert len(hits) == 1
        assert hits[0]["session_id"] == "s1"
        assert hits[0]["name"] == "能耗分析.docx"

    def test_replace_is_idempotent_full_swap(self, store):
        store.replace_artifacts("s1", [{"path": "a.txt", "name": "a.txt", "ext": ".txt", "size": 1, "mtime": 0}])
        store.replace_artifacts("s1", [{"path": "b.txt", "name": "b.txt", "ext": ".txt", "size": 1, "mtime": 0}])
        assert store.search_artifacts("a.txt") == []  # 旧条目被整表替换
        assert len(store.search_artifacts("b.txt")) == 1

    def test_drop_artifacts(self, store):
        store.replace_artifacts("s1", [{"path": "a.txt", "name": "a.txt", "ext": ".txt", "size": 1, "mtime": 0}])
        store.drop_artifacts("s1")
        assert store.search_artifacts("a.txt") == []

    def test_search_no_match_empty(self, store):
        assert store.search_artifacts("不存在的东西xyz") == []


def _make_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router, prefix="/api")
    app.include_router(chat_router)
    app.include_router(platform_router, prefix="/api")
    app.state.cwd = tmp_path
    app.state.model = "test-model"
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.active_tasks = {}
    st = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    app.state.platform_store = st
    app.state.project = st.ensure_project(tmp_path)
    return app


class TestManifestEndpoint:
    def test_manifest_lazy_build_and_index(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        sid = client.post("/api/chat/sessions", json={"title": "测试"}).json()["id"]
        # 会话产物目录塞几个文件
        out_dir = tmp_path / "outputs" / sid / "artifacts"
        out_dir.mkdir(parents=True)
        (out_dir / "报告.docx").write_bytes(b"x" * 100)
        (tmp_path / "outputs" / sid / "draft.md").write_text("draft", encoding="utf-8")

        resp = client.get(f"/api/chat/sessions/{sid}/manifest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        names = {f["name"] for f in data["files"]}
        assert names == {"报告.docx", "draft.md"}
        # manifest.json 落盘（不计入清单本身）
        assert (tmp_path / "outputs" / sid / "manifest.json").exists()
        # artifacts 索引回填 → 统一检索可命中
        search = client.get("/api/search?scope=artifacts&q=报告").json()
        assert len(search["artifacts"]) == 1
        assert search["artifacts"][0]["session_id"] == sid

    def test_manifest_empty_outputs(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        sid = client.post("/api/chat/sessions", json={"title": "t"}).json()["id"]
        resp = client.get(f"/api/chat/sessions/{sid}/manifest")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    def test_manifest_unknown_404(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        assert client.get(
            "/api/chat/sessions/20990101_000000_none_a1b2c3/manifest"
        ).status_code == 404
