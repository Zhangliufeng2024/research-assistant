"""统一科研工作空间的迁移、线程、质量和产物审阅契约。"""

import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient

from research_assistant.context import SourceStore
from research_assistant.runtime import PlatformStore
from research_assistant.runtime.analysis import (
    environment_lock,
    runtime_environment,
    schema_changes,
    snapshot_input_files,
)
from research_assistant.runtime.platform_store import PROJECT_OS_VERSION, SCHEMA_VERSION
from research_assistant.web.routes import router


def test_v4_database_migrates_idempotently(tmp_path):
    db = tmp_path / "platform.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta VALUES('schema_version', '4');
            CREATE TABLE projects(
              id TEXT PRIMARY KEY, root TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
              instructions TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL,
              updated_at REAL NOT NULL
            );
            """
        )
    PlatformStore(db)
    PlatformStore(db)
    with sqlite3.connect(db) as conn:
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert meta["schema_version"] == str(SCHEMA_VERSION)
    assert meta["project_os_version"] == str(PROJECT_OS_VERSION)
    assert {"threads", "turns", "agent_items", "agent_runs", "quality_items", "artifact_reviews", "notifications"} <= tables


def test_thread_turn_item_fork_and_archive(tmp_path):
    store = PlatformStore(tmp_path / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    thread = store.create_thread(project_id=project["id"], title="主线程")
    turn = store.create_turn(thread_id=thread["id"], project_id=project["id"], user_input="研究问题")
    item = store.append_agent_item(
        thread_id=thread["id"], project_id=project["id"], turn_id=turn["id"],
        item_type="research_claim", content={"text": "结论"}, role="literature",
    )
    assert item["seq"] == 1
    assert store.list_thread_items(thread["id"])[0]["content"]["text"] == "结论"
    assert store.finish_turn(turn["id"], status="complete")["status"] == "complete"
    fork = store.fork_thread(thread["id"], project_id=project["id"])
    assert fork["parent_thread_id"] == thread["id"]
    assert store.archive_thread(fork["id"], project_id=project["id"])
    assert all(row["id"] != fork["id"] for row in store.list_threads(project["id"]))


def test_quality_artifact_and_project_home_api(tmp_path):
    store = PlatformStore(tmp_path / "platform.sqlite3")
    project = store.ensure_project(tmp_path, "Research OS")
    store.create_quality_item(
        project_id=project["id"], object_type="claim", object_id="c1",
        gate="evidence", severity="warning", message="缺少证据",
    )
    store.review_artifact(
        project_id=project["id"], artifact_path="writing_outputs/a/manuscript.docx",
        status="pending",
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.platform_store = store
    app.state.project = project
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.active_tasks = {}
    client = TestClient(app)

    home = client.get("/api/project/home")
    assert home.status_code == 200
    assert home.json()["project"]["name"] == "Research OS"
    assert home.json()["quality_items"][0]["message"] == "缺少证据"
    assert client.get("/api/artifacts/reviews").json()[0]["status"] == "pending"
    updated = client.post("/api/artifacts/reviews", json={
        "artifact_path": "writing_outputs/a/manuscript.docx",
        "version": 1,
        "status": "accepted",
        "comment": "通过",
    })
    assert updated.status_code == 200
    assert updated.json()["status"] == "accepted"


def test_artifact_gate_blocks_acceptance_and_preserves_metadata(tmp_path):
    store = PlatformStore(tmp_path / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    store.review_artifact(
        project_id=project["id"], artifact_path="draft.md", status="pending", version=1,
        metadata={"quality_gate_status": "failed", "sha256": "abc"},
    )
    try:
        store.review_artifact(project_id=project["id"], artifact_path="draft.md", status="accepted", version=1)
    except ValueError as exc:
        assert "门禁未通过" in str(exc)
    else:
        raise AssertionError("failed quality gates must block acceptance")
    assert store.get_artifact_review(store.list_artifact_reviews(project["id"])[0]["id"], project["id"])["metadata"]["sha256"] == "abc"


def test_reproducible_analysis_run_manifest(tmp_path):
    script = tmp_path / "analysis.py"
    script.write_text("print('ok')", encoding="utf-8")
    store = PlatformStore(tmp_path / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    run = store.create_analysis_run(
        project_id=project["id"], script_path=str(script),
        inputs={"data.csv": "abc123"}, parameters={"seed": 7},
        environment={"python": "3.13"},
    )
    assert len(run["script_sha256"]) == 64
    finished = store.finish_analysis_run(run["id"], status="complete", outputs={"figure": "fig.png"}, stdout="done", exit_code=0)
    assert finished["outputs"]["figure"] == "fig.png"
    assert store.list_analysis_runs(project["id"])[0]["parameters"]["seed"] == 7


def test_runtime_environment_has_deterministic_dependency_lock(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\ndependencies = ["httpx>=0.1"]\n', encoding="utf-8")
    first = environment_lock(tmp_path)
    second = environment_lock(tmp_path)
    assert first["lock_hash"] == second["lock_hash"]
    assert len(first["lock_hash"]) == 64
    runtime = runtime_environment(tmp_path)
    assert runtime["dependency_lock_hash"] == first["lock_hash"]


def test_analysis_input_schema_snapshot_detects_column_and_hash_changes(tmp_path):
    data = tmp_path / "data.csv"
    data.write_text("x,y\n1,2\n", encoding="utf-8")
    before = snapshot_input_files(tmp_path, ["data.csv"])
    data.write_text("x,z\n1,hello\n", encoding="utf-8")
    after = snapshot_input_files(tmp_path, ["data.csv"])
    assert before["files"][0]["sha256"] != after["files"][0]["sha256"]
    changes = schema_changes(before["schemas"], after["schemas"])
    assert changes and changes[0]["path"] == "data.csv"


def test_completed_task_indexes_real_artifact_versions(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    output = tmp_path / "writing_outputs" / "run"
    output.mkdir(parents=True)
    artifact = output / "manuscript.md"
    artifact.write_text("# draft\n", encoding="utf-8")
    records = store.index_task_artifacts(
        project_id=project["id"], output_dir=output,
    )
    assert records[0]["artifact_path"] == "writing_outputs/run/manuscript.md"
    assert records[0]["metadata"]["sha256"]
    assert records[0]["status"] == "pending"
    artifact.write_text("# revised\n", encoding="utf-8")
    records = store.index_task_artifacts(project_id=project["id"], output_dir=output)
    assert records[0]["version"] == 2


def test_artifact_index_imports_gate_failures(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    output = tmp_path / "writing_outputs" / "gated"
    output.mkdir(parents=True)
    (output / "gates_report.json").write_text(
        '{"passed": false, "results": [{"name": "citations", "passed": false, '
        '"severity": "blocking", "failures": ["DOI 未核验"]}]}', encoding="utf-8",
    )
    (output / "draft.md").write_text("draft", encoding="utf-8")
    records = store.index_task_artifacts(project_id=project["id"], output_dir=output)
    assert any(item["metadata"]["quality_gate_status"] == "failed" for item in records)
    risks = store.list_quality_items(project["id"], status="open")
    assert any(item["gate"] == "citations" for item in risks)


def test_scheduler_payload_drops_credentials(tmp_path):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    app.state.platform_store = store
    app.state.project = project
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.active_tasks = {}
    response = TestClient(app).post("/api/scheduler/jobs", json={
        "workflow_id": "paper",
        "payload": {"query": "safe", "api_key": "DO_NOT_PERSIST", "base_url": "https://secret.invalid"},
    })
    assert response.status_code == 200
    assert store.list_jobs(project["id"])[0]["payload"] == {"query": "safe"}


def test_usage_and_notifications_are_project_scoped(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    run = store.create_research_run(project_id=project["id"], workflow_id="paper")
    store.finish_research_run(run["id"], status="complete", outputs={"usage": {"cost_usd": 1.25, "total_tokens": 500, "turns": 2, "elapsed_seconds": 3}})
    note = store.create_notification(project_id=project["id"], kind="task_complete", title="完成", object_type="research_run", object_id=run["id"])
    home = store.project_home(project["id"])
    assert home["usage"]["summary"]["cost_usd"] == 1.25
    assert home["notifications"][0]["id"] == note["id"]
    assert store.mark_notification_read(note["id"], project["id"])
    assert store.list_notifications(project["id"], unread_only=True) == []


def test_agent_approval_inbox_is_persistent_and_project_scoped(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    approval = store.create_agent_approval(
        project_id=project["id"], task_id=None, agent_id="literature", role="文献 Agent",
        tool_name="verify_citations", arguments={"doi": "10.1000/test"}, summary="核验 DOI",
        approval_id="approval-1",
    )
    assert store.list_agent_approvals(project["id"])[0]["arguments"]["doi"] == "10.1000/test"
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.platform_store = store
    app.state.project = project
    app.state.cwd = tmp_path
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.task_hub = None
    client = TestClient(app)
    assert client.get("/api/approvals").json()[0]["id"] == approval["id"]
    assert client.post("/api/approvals/approval-1/resolve", json={"approved": True}).status_code == 409
    assert store.list_agent_approvals(project["id"])[0]["status"] == "pending"


def test_multipart_source_upload_persists_starlette_upload(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.platform_store = store
    app.state.project = project
    app.state.cwd = tmp_path
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.source_store = SourceStore(tmp_path / ".ra" / "sources.sqlite3")
    response = TestClient(app).post("/api/sources/upload", files={"files": ("source.md", b"# source\nanchor", "text/markdown")})
    assert response.status_code == 200
    assert response.json()["sources"][0]["name"] == "source.md"
    assert len(app.state.source_store.list_sources()) == 1


def test_deleted_source_marks_linked_claims_for_review(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    source_store = SourceStore(tmp_path / ".ra" / "sources.sqlite3")
    source_file = tmp_path / "source.md"
    source_file.write_text("evidence", encoding="utf-8")
    source = source_store.ingest_file(source_file)
    claim = store.create_claim(project_id=project["id"], text="可复核结论")
    evidence = store.create_evidence(project_id=project["id"], source_id=source["id"], excerpt="evidence")
    store.link_evidence(project_id=project["id"], claim_id=claim["id"], evidence_id=evidence["id"])
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.platform_store = store
    app.state.project = project
    app.state.source_store = source_store
    response = TestClient(app).delete(f"/api/sources/{source['id']}")
    assert response.status_code == 200
    assert response.json()["impact"]["claims"] == 1
    assert any(item["gate"] == "source_integrity" for item in store.list_quality_items(project["id"]))


def test_task_step_rerun_enqueues_auditable_job(tmp_path):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    task = store.create_task(
        task_id="task-rerun", project_id=project["id"], query="研究问题",
        mode="workflow:research_sprint", output_dir=str(tmp_path / "writing_outputs" / "run"),
        metadata={"workflow_id": "research_sprint"},
    )
    store.create_steps(task["id"], [{"id": "scope", "title": "范围", "depends_on": []}])
    store.update_task(task["id"], status="complete")
    app.state.platform_store = store
    app.state.project = project
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.active_tasks = {}
    response = TestClient(app).post("/api/tasks/task-rerun/steps/scope/rerun")
    assert response.status_code == 200
    assert response.json()["rerun_step"] == "scope"
    assert store.list_jobs(project["id"])[0]["payload"]["rerun_step"] == "scope"
    skipped = TestClient(app).post("/api/tasks/task-rerun/steps/scope/skip")
    assert skipped.status_code == 200
    assert store.list_steps(task["id"])[0]["status"] == "skipped"


def test_task_agents_endpoint_exposes_roster(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    thread = store.create_thread(project_id=project["id"], title="Agent thread")
    task = store.create_task(
        task_id="task-agents", project_id=project["id"], query="研究问题",
        mode="workflow:research_sprint", output_dir=str(tmp_path / "writing_outputs"),
        metadata={"workflow_id": "research_sprint", "thread_id": thread["id"]},
    )
    store.create_steps(task["id"], [{"id": "scope", "title": "问题界定", "depends_on": []}])
    store.update_step(task["id"], "scope", status="running")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.platform_store = store
    app.state.project = project
    app.state.output_folder = tmp_path / "writing_outputs"
    response = TestClient(app).get(f"/api/tasks/{task['id']}/agents")
    assert response.status_code == 200
    assert response.json()["agents"][0]["role"] == "planner"
    assert response.json()["agents"][0]["status"] == "running"
    assert store.list_agent_runs(project["id"], task_id=task["id"])[0]["role"] == ""


def test_project_activity_stream_and_quality_conflict_report(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    task = store.create_task(task_id="activity-task", project_id=project["id"], query="activity", mode="test")
    store.append_event(task["id"], {"type": "status", "message": "started"})
    claim = store.create_claim(project_id=project["id"], text="有冲突的结论")
    support = store.create_evidence(project_id=project["id"], excerpt="support")
    contradiction = store.create_evidence(project_id=project["id"], excerpt="contradiction")
    store.link_evidence(project_id=project["id"], claim_id=claim["id"], evidence_id=support["id"], relation="supports")
    store.link_evidence(project_id=project["id"], claim_id=claim["id"], evidence_id=contradiction["id"], relation="contradicts")
    report = store.research_quality_report(project["id"])
    assert report["claims"]["conflicted"] == 1
    assert report["ready_for_synthesis"] is False
    activity = store.project_activity(project["id"])
    assert any(item["object_id"] == task["id"] for item in activity["items"])
    first = store.project_activity(project["id"], limit=1)
    assert first["items"] and "|" in first["next_cursor"]
    second = store.project_activity(project["id"], cursor=first["next_cursor"], limit=10)
    assert not ({item["id"] for item in first["items"]} & {item["id"] for item in second["items"]})


def test_artifact_inspector_preview_provenance_and_request_changes(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    thread = store.create_thread(project_id=project["id"], title="审阅线程")
    artifact = tmp_path / "writing_outputs" / "draft.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("# draft\n", encoding="utf-8")
    review = store.review_artifact(
        project_id=project["id"], artifact_path="writing_outputs/draft.md",
        status="pending", thread_id=thread["id"], metadata={"sha256": "x", "quality_gate_status": "passed"},
    )
    store.add_provenance_edge(project_id=project["id"], from_type="task", from_id="t1", to_type="artifact_review", to_id=review["id"], relation="produced")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.platform_store = store
    app.state.project = project
    app.state.cwd = tmp_path
    app.state.output_folder = tmp_path / "writing_outputs"
    client = TestClient(app)
    detail = client.get(f"/api/artifacts/reviews/{review['id']}")
    assert detail.status_code == 200
    assert detail.json()["provenance"][0]["relation"] == "produced"
    assert client.get(f"/api/artifacts/reviews/{review['id']}/preview").json()["content"].startswith("# draft")
    requested = client.post(f"/api/artifacts/reviews/{review['id']}/request-changes", json={"comment": "补充限制"})
    assert requested.status_code == 200
    assert requested.json()["review"]["status"] == "needs_changes"
    assert requested.json()["agent_item"]["content"]["comment"] == "补充限制"


def test_analysis_compare_rerun_and_project_package_roundtrip(tmp_path):
    script = tmp_path / "analysis.py"
    script.write_text("print('reproduced')", encoding="utf-8")
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    first = store.create_analysis_run(project_id=project["id"], script_path=str(script), inputs={"x": "1"}, parameters={"seed": 1})
    second = store.create_analysis_run(project_id=project["id"], script_path=str(script), inputs={"x": "2"}, parameters={"seed": 1})
    other_root = tmp_path / "other"
    other_root.mkdir()
    other = store.ensure_project(other_root)
    foreign = store.create_analysis_run(project_id=other["id"], script_path=str(script))
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.platform_store = store
    app.state.project = project
    app.state.cwd = tmp_path
    app.state.output_folder = tmp_path / "writing_outputs"
    app.state.source_store = None
    with TestClient(app) as client:
        compared = client.get(f"/api/analysis/runs/compare?left_id={first['id']}&right_id={second['id']}")
        assert compared.status_code == 200
        assert "inputs" in compared.json()["changes"]
        assert client.get(f"/api/analysis/runs/compare?left_id={first['id']}&right_id={foreign['id']}").status_code == 404
        rerun = client.post(f"/api/analysis/runs/{first['id']}/rerun")
        assert rerun.status_code == 200
        assert rerun.json()["source_run_id"] == first["id"]
        package = client.get("/api/project/export")
        assert package.status_code == 200
        assert b"research_manifest.json" in package.content
        imported = client.post("/api/project/import", content=package.content, headers={"content-type": "application/zip"})
        assert imported.status_code == 200
