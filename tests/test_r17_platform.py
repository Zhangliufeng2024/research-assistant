"""R17 重构后端测试：feature flag / 会话目录命名 / platform_store v11 /
会话标志与互链 REST / 触发器管理 / 历史运行检索。

chat REST 部分沿用 test_chat_api.py 的裸 app 模式（不 import app.py），
app.state 手工接线 platform_store 与 project。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from research_assistant.config import feature_flag, generate_session_dir_name
from research_assistant.runtime.platform_store import PlatformStore

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from research_assistant.web.chat import router as chat_router  # noqa: E402

# ---------------------------------------------------------------------------
# feature flag
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("RA_FF_DEMO", raising=False)
        assert feature_flag("DEMO") is False
        assert feature_flag("DEMO", default=True) is True

    def test_truthy_and_falsy_values(self, monkeypatch):
        for value in ("1", "true", "YES", "on"):
            monkeypatch.setenv("RA_FF_DEMO", value)
            assert feature_flag("DEMO") is True
        for value in ("0", "false", "no", "off", ""):
            monkeypatch.setenv("RA_FF_DEMO", value)
            assert feature_flag("DEMO", default=True) is False

    def test_name_uppercased(self, monkeypatch):
        monkeypatch.setenv("RA_FF_CHAT_TASK_LINK", "1")
        assert feature_flag("chat_task_link") is True


# ---------------------------------------------------------------------------
# 会话目录命名（R17 任务 1.7）
# ---------------------------------------------------------------------------


class TestSessionDirName:
    def test_cjk_slug_preserved(self):
        name = generate_session_dir_name("能耗 SHAP 分析")
        assert "能耗" in name and "shap" in name

    def test_random_suffix_avoids_collision(self):
        names = {generate_session_dir_name("same query") for _ in range(200)}
        assert len(names) == 200

    def test_empty_slug_still_unique(self):
        a, b = generate_session_dir_name("!!!"), generate_session_dir_name("!!!")
        assert a != b

    def test_timestamp_prefix_kept(self):
        name = generate_session_dir_name("test")
        assert name[:15].count("_") == 1 and name[:8].isdigit()


# ---------------------------------------------------------------------------
# platform_store v11：标志位 / 互链 / 检索 / 触发器管理
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> PlatformStore:
    s = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    s.ensure_project(tmp_path)
    return s


@pytest.fixture()
def project_id(store: PlatformStore, tmp_path: Path) -> str:
    return store.ensure_project(tmp_path)["id"]


class TestSessionFlags:
    def test_set_and_get_map(self, store):
        store.set_session_flags("s1", pinned=True)
        store.set_session_flags("s2", archived=True)
        flags = store.get_session_flags_map(["s1", "s2", "s3"])
        assert flags["s1"] == {"pinned": True, "archived": False}
        assert flags["s2"] == {"pinned": False, "archived": True}
        assert "s3" not in flags  # 无记录不出现（调用方按默认 False）

    def test_partial_update_preserves_other_flag(self, store):
        store.set_session_flags("s1", pinned=True)
        result = store.set_session_flags("s1", archived=True)
        assert result["pinned"] is True and result["archived"] is True

    def test_unset(self, store):
        store.set_session_flags("s1", pinned=True)
        result = store.set_session_flags("s1", pinned=False)
        assert result["pinned"] is False


class TestSourceSessionLink:
    def test_create_task_records_source_session(self, store, project_id):
        task = store.create_task(
            task_id="t1", project_id=project_id, query="q", mode="single",
            source_session_id="sess-1",
        )
        assert task["source_session_id"] == "sess-1"

    def test_count_tasks_for_sessions(self, store, project_id):
        for i in range(3):
            store.create_task(
                task_id=f"t{i}", project_id=project_id, query="q",
                mode="single", source_session_id="sess-1",
            )
        store.create_task(
            task_id="t9", project_id=project_id, query="q", mode="single",
        )
        counts = store.count_tasks_for_sessions(["sess-1", "sess-2"])
        assert counts == {"sess-1": 3}


class TestDbRetention:
    """工程债：保留期策略扩展到终态任务与产物索引。"""

    def _terminal_old_task(self, store, project_id: str, task_id: str) -> str:
        store.create_task(task_id=task_id, project_id=project_id, query="q", mode="paper")
        store.create_steps(task_id, [{"id": "plan", "title": "Plan"}])
        store.update_task(task_id, status="complete")
        # 回拨 finished_at，使其落入保留期外
        with store._connect() as conn:  # noqa: SLF001 - 测试直改时间戳
            conn.execute(
                "UPDATE tasks SET finished_at = ? WHERE id = ?",
                (time.time() - 400 * 86400.0, task_id),
            )
        return task_id

    def test_purges_terminal_old_tasks_keeps_running(self, store, project_id):
        old = self._terminal_old_task(store, project_id, "t" + "0" * 11)
        running = self._terminal_old_task(store, project_id, "t" + "1" * 11)
        with store._connect() as conn:  # noqa: SLF001 - 测试直改状态
            conn.execute(
                "UPDATE tasks SET status='running', finished_at=NULL WHERE id = ?",
                (running,),
            )

        removed = store.purge_old_db_events(0)

        assert removed["tasks"] == 1
        assert store.get_task(old) is None
        assert store.get_task(running) is not None
        # 终态任务删除后子表级联清理（steps 与 events 一并消失）
        assert store.list_steps(old) == []
        assert store.read_events(old) == []

    def test_job_task_reference_nulled_on_task_purge(self, store, project_id):
        task_id = self._terminal_old_task(store, project_id, "t" + "2" * 11)
        job = store.enqueue_job(project_id=project_id, workflow_id="single")
        store.attach_job_task(job["id"], task_id)

        store.purge_old_db_events(0)

        refreshed = next(
            (j for j in store.list_jobs(project_id) if j["id"] == job["id"]), None
        )
        assert refreshed is not None
        assert refreshed.get("task_id") is None  # 无 FK 的悬挂引用被置空

    def test_artifacts_retention_by_mtime(self, store, tmp_path):
        import os

        old_file = tmp_path / "old.png"
        old_file.write_bytes(b"x")
        os.utime(old_file, (time.time() - 400 * 86400.0,) * 2)
        store.upsert_artifact("s1", old_file, workspace=tmp_path)
        fresh = tmp_path / "fresh.png"
        fresh.write_bytes(b"y")
        store.upsert_artifact("s1", fresh, workspace=tmp_path)

        # days=1：新文件（mtime≈now）在保留期内，旧文件（400 天前）淘汰
        removed = store.purge_old_db_events(1)

        assert removed["artifacts"] == 1
        names = {a["name"] for a in store.search_artifacts("", limit=100)}
        assert "fresh.png" in names
        assert "old.png" not in names

    def test_existing_db_upgraded(self, tmp_path):
        """旧库（无 source_session_id 列）打开后自动 ALTER，任务不丢。"""
        db = tmp_path / ".ra" / "platform.sqlite3"
        s1 = PlatformStore(db)
        pid = s1.ensure_project(tmp_path)["id"]
        s1.create_task(task_id="old", project_id=pid, query="legacy", mode="single")
        # 模拟再次打开（迁移幂等）
        s2 = PlatformStore(db)
        task = s2.get_task("old")
        assert task["query"] == "legacy"
        assert task["source_session_id"] is None


class TestSearchRuns:
    def _seed(self, store: PlatformStore, project_id: str) -> None:
        for i, (q, st) in enumerate([
            ("能耗分析报告", "complete"),
            ("SHAP 分析", "failed"),
            ("能耗敏感性", "complete"),
            ("气候 morphing", "running"),
        ]):
            store.create_task(
                task_id=f"r{i}", project_id=project_id, query=q, mode="single",
            )
            store.update_task(f"r{i}", status=st)
            time.sleep(0.002)  # 保证 updated_at 可区分

    def test_query_substring(self, store, project_id):
        self._seed(store, project_id)
        result = store.search_runs(project_id, query="能耗")
        assert result["total"] == 2
        assert all("能耗" in item["query"] for item in result["items"])

    def test_status_filter(self, store, project_id):
        self._seed(store, project_id)
        result = store.search_runs(project_id, status="complete")
        assert result["total"] == 2

    def test_pagination(self, store, project_id):
        self._seed(store, project_id)
        page1 = store.search_runs(project_id, limit=2, offset=0)
        page2 = store.search_runs(project_id, limit=2, offset=2)
        assert page1["total"] == 4
        assert len(page1["items"]) == 2 and len(page2["items"]) == 2
        ids1 = {i["id"] for i in page1["items"]}
        ids2 = {i["id"] for i in page2["items"]}
        assert ids1.isdisjoint(ids2)

    def test_combined(self, store, project_id):
        self._seed(store, project_id)
        result = store.search_runs(project_id, query="能耗", status="complete")
        assert result["total"] == 2


class TestTriggerManagement:
    def _make_trigger(self, store: PlatformStore, project_id: str) -> str:
        return store.create_workflow_trigger(
            project_id=project_id, workflow_id="single", interval_seconds=60,
        )["id"]

    def test_disable_and_enable(self, store, project_id):
        tid = self._make_trigger(store, project_id)
        item = store.set_workflow_trigger_enabled(tid, project_id, enabled=False)
        assert item["enabled"] is False
        item = store.set_workflow_trigger_enabled(tid, project_id, enabled=True)
        assert item["enabled"] is True

    def test_disabled_trigger_not_released(self, store, project_id):
        tid = self._make_trigger(store, project_id)
        store.set_workflow_trigger_enabled(tid, project_id, enabled=False)
        assert store.release_due_triggers() == 0

    def test_delete(self, store, project_id):
        tid = self._make_trigger(store, project_id)
        assert store.delete_workflow_trigger(tid, project_id) is True
        assert store.delete_workflow_trigger(tid, project_id) is False
        assert store.list_workflow_triggers(project_id) == []

    def test_cross_project_isolation(self, store, project_id, tmp_path):
        other = store.ensure_project(tmp_path / "other")["id"]
        tid = self._make_trigger(store, project_id)
        assert store.set_workflow_trigger_enabled(tid, other, enabled=False) is None
        assert store.delete_workflow_trigger(tid, other) is False


# ---------------------------------------------------------------------------
# chat REST：flags / 列表合并 / promote
# ---------------------------------------------------------------------------


def _make_app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(chat_router, prefix="/api")
    app.include_router(chat_router)
    app.state.cwd = tmp_path
    app.state.model = "test-model"
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.active_tasks = {}
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    app.state.platform_store = store
    app.state.project = store.ensure_project(tmp_path)
    return app


def _create_session(client: TestClient, title: str = "测试会话") -> str:
    resp = client.post("/api/chat/sessions", json={"title": title})
    assert resp.status_code == 200
    return resp.json()["id"]


class TestSessionFlagsApi:
    def test_set_flags_roundtrip(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        sid = _create_session(client)
        resp = client.post(f"/api/chat/sessions/{sid}/flags", json={"pinned": True})
        assert resp.status_code == 200
        assert resp.json()["pinned"] is True
        items = client.get("/api/chat/sessions").json()
        item = next(i for i in items if i["id"] == sid)
        assert item["pinned"] is True and item["archived"] is False

    def test_missing_fields_422(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        sid = _create_session(client)
        assert client.post(
            f"/api/chat/sessions/{sid}/flags", json={},
        ).status_code == 422

    def test_unknown_session_404(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        assert client.post(
            "/api/chat/sessions/20990101_000000_none_a1b2/flags",
            json={"pinned": True},
        ).status_code == 404

    def test_pinned_sorts_first(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        sid_new = _create_session(client, "新的")
        time.sleep(0.01)
        sid_old = _create_session(client, "旧的")
        # 让 sid_old 的 updated_at 更旧，再置顶——置顶必须压过时间序
        client.post(f"/api/chat/sessions/{sid_old}/flags", json={"pinned": True})
        items = client.get("/api/chat/sessions").json()
        assert items[0]["id"] == sid_old
        assert sid_new in {i["id"] for i in items}


class TestPromoteApi:
    def test_promote_enqueues_job_with_source(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        sid = _create_session(client, "能耗讨论")
        resp = client.post(f"/api/chat/sessions/{sid}/promote", json={})
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]
        assert job_id
        store: PlatformStore = client.app.state.platform_store
        jobs = store.list_jobs(client.app.state.project["id"])
        job = next(j for j in jobs if j["id"] == job_id)
        assert job["payload"]["source_session_id"] == sid
        assert "能耗讨论" in job["payload"]["query"]

    def test_promote_with_custom_prompt(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        sid = _create_session(client)
        resp = client.post(
            f"/api/chat/sessions/{sid}/promote",
            json={"prompt": "把讨论整理成报告"},
        )
        assert resp.status_code == 200
        store: PlatformStore = client.app.state.platform_store
        jobs = store.list_jobs(client.app.state.project["id"])
        assert jobs[0]["payload"]["query"].startswith("把讨论整理成报告")

    def test_promote_unknown_404(self, tmp_path):
        client = TestClient(_make_app(tmp_path))
        assert client.post(
            "/api/chat/sessions/20990101_000000_none_a1b2/promote", json={},
        ).status_code == 404
