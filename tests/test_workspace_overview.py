"""计划项 3.6：GET /api/research/overview 只读统一视图契约。

断言聚合字段与真实落库/落盘数据一致；端点必须保持只读——
不触发会话清退、不新增任何写入路径。
"""

import json
import sqlite3
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_assistant.runtime import PlatformStore
from research_assistant.web.routes import router


def _make_app(tmp_path):
    store = PlatformStore(tmp_path / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.platform_store = store
    app.state.project = project
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.active_tasks = {}
    app.state.cwd = tmp_path
    return TestClient(app), store, project


def _make_session(tmp_path: str, name: str, query: str, turns: int = 1) -> None:
    """在 .ra/sessions 下落一个最小会话目录（run.json + history.json）。"""
    run_dir = tmp_path / ".ra" / "sessions" / name
    run_dir.mkdir(parents=True)
    now = time.time()
    (run_dir / "run.json").write_text(
        json.dumps({"query": query, "created_at": now, "updated_at": now}),
        encoding="utf-8",
    )
    messages = [
        {"role": "user", "content": f"{query} 第{i}问"} for i in range(turns)
    ]
    (run_dir / "history.json").write_text(
        json.dumps({"schema_version": 1, "messages": messages}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_overview_empty_workspace(tmp_path):
    client, _store, _project = _make_app(tmp_path)
    resp = client.get("/api/research/overview")
    assert resp.status_code == 200
    data = resp.json()
    # 原 research_overview 键保持
    assert data["counts"] == {
        "research_items": 0, "claims": 0, "evidence": 0,
        "decisions": 0, "research_runs": 0, "provenance_edges": 0,
    }
    assert data["uncovered_claims"] == 0
    # 工作区快照
    assert data["sessions"] == {"total": 0, "recent": []}
    assert data["tasks"] == {"total": 0, "by_status": {}, "recent": []}
    assert data["jobs"] == {"total": 0, "by_status": {}, "recent": []}
    assert data["artifacts"] == {"total": 0, "sessions": 0, "by_ext": {}}
    assert data["recent_events"] == []


def test_overview_sessions_match_disk(tmp_path):
    client, _store, _project = _make_app(tmp_path)
    _make_session(tmp_path, "20260101_000000_旧会话", "旧问题")
    _make_session(tmp_path, "20260801_000000_新会话", "新问题", turns=2)
    (tmp_path / ".ra" / "sessions" / ".stray").mkdir(parents=True)  # 杂散目录不计

    data = client.get("/api/research/overview").json()
    assert data["sessions"]["total"] == 2
    recent = data["sessions"]["recent"]
    # 按更新时间倒序，新会话在前（同名秒级 mtime 可能并列，按 id 兜底断言内容）
    ids = [s["id"] for s in recent]
    assert set(ids) == {"20260101_000000_旧会话", "20260801_000000_新会话"}
    new_item = next(s for s in recent if s["id"] == "20260801_000000_新会话")
    assert new_item["title"] == "新问题"
    assert new_item["turns"] == 2
    assert new_item["last_message"].startswith("新问题 第")


def test_overview_task_and_job_counts_match_db(tmp_path):
    client, store, project = _make_app(tmp_path)
    store.create_task(task_id="t1", project_id=project["id"], query="任务一", mode="chat")
    store.create_task(task_id="t2", project_id=project["id"], query="任务二", mode="pipeline")
    store.update_task("t1", status="running")
    store.enqueue_job(project_id=project["id"], workflow_id="wf-a")
    store.enqueue_job(project_id=project["id"], workflow_id="wf-b")
    store.enqueue_job(project_id=project["id"], workflow_id="wf-c")

    data = client.get("/api/research/overview").json()
    assert data["tasks"]["total"] == 2
    assert data["tasks"]["by_status"] == {"running": 1, "queued": 1}
    assert {t["id"] for t in data["tasks"]["recent"]} == {"t1", "t2"}
    assert data["jobs"]["total"] == 3
    assert data["jobs"]["by_status"] == {"queued": 3}
    assert {j["workflow_id"] for j in data["jobs"]["recent"]} == {"wf-a", "wf-b", "wf-c"}


def test_overview_artifacts_match_table(tmp_path):
    client, store, project = _make_app(tmp_path)
    docx = tmp_path / "out.docx"
    docx.write_bytes(b"docx")
    png = tmp_path / "fig.png"
    png.write_bytes(b"png")
    assert store.upsert_artifact("sess-a", docx, workspace=tmp_path)
    assert store.upsert_artifact("sess-a", png, workspace=tmp_path)

    data = client.get("/api/research/overview").json()
    assert data["artifacts"]["total"] == 2
    assert data["artifacts"]["sessions"] == 1
    assert data["artifacts"]["by_ext"] == {".docx": 1, ".png": 1}
    # 与 SQLite 落库数据逐行核对
    with sqlite3.connect(tmp_path / "platform.sqlite3") as conn:
        rows = conn.execute("SELECT COUNT(*), COUNT(DISTINCT session_id) FROM artifacts").fetchone()
    assert (data["artifacts"]["total"], data["artifacts"]["sessions"]) == tuple(rows)


def test_overview_recent_events_decoded_and_ordered(tmp_path):
    client, store, project = _make_app(tmp_path)
    store.create_task(task_id="t1", project_id=project["id"], query="任务", mode="chat")
    store.append_event("t1", {"type": "stage", "payload": {"stage": "plan"}})
    time.sleep(0.01)
    store.append_event("t1", {"type": "stage", "payload": {"stage": "research"}})

    data = client.get("/api/research/overview").json()
    events = data["recent_events"]
    assert len(events) == 2
    assert events[0]["type"] == "stage"
    # append_event 将整个 payload dict 落库，自定义字段在 payload["payload"]
    assert events[0]["payload"]["payload"]["stage"] == "research"  # 最近事件在前
    assert events[1]["payload"]["payload"]["stage"] == "plan"
    assert events[0]["ts"] >= events[1]["ts"]


def test_overview_is_read_only(tmp_path):
    """同一工作区连续两次调用，落库数据不得有任何变化。"""
    client, store, project = _make_app(tmp_path)
    store.create_task(task_id="t1", project_id=project["id"], query="任务", mode="chat")
    _make_session(tmp_path, "20260801_000000_会话", "问题")
    with sqlite3.connect(tmp_path / "platform.sqlite3") as conn:
        before = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()

    first = client.get("/api/research/overview").json()
    second = client.get("/api/research/overview").json()
    assert first == second
    with sqlite3.connect(tmp_path / "platform.sqlite3") as conn:
        after = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    assert before == after
