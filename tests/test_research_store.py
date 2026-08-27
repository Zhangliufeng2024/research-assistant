"""科研操作系统研究对象层的持久化契约测试。"""

import time

from research_assistant.runtime import PlatformStore


def test_research_api_round_trip(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from research_assistant.web.routes import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.platform_store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    app.state.project = app.state.platform_store.ensure_project(tmp_path)
    client = TestClient(app)

    item = client.post("/api/research/items", json={"kind": "hypothesis", "title": "H1"})
    assert item.status_code == 200
    claim = client.post("/api/research/claims", json={"text": "结论"}).json()
    evidence = client.post("/api/research/evidence", json={"excerpt": "原文"}).json()
    assert client.post(f"/api/research/claims/{claim['id']}/evidence", json={"evidence_id": evidence["id"]}).status_code == 200
    overview = client.get("/api/research/overview").json()
    assert overview["uncovered_claims"] == 0


def test_research_object_graph_and_overview(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path, "demo")
    pid = project["id"]

    question = store.create_research_item(project_id=pid, kind="question", title="研究问题", body="为什么？")
    assert question["kind"] == "question"
    updated = store.update_research_item(question["id"], status="active")
    assert updated["version"] == 2

    claim = store.create_claim(project_id=pid, text="方法有效", confidence=0.8)
    evidence = store.create_evidence(project_id=pid, source_anchor="paper.pdf:p2", excerpt="结果段落")
    link = store.link_evidence(project_id=pid, claim_id=claim["id"], evidence_id=evidence["id"], strength=0.9)
    assert link["relation"] == "supports"
    assert store.list_claims(pid)[0]["evidence_links"][0]["evidence_id"] == evidence["id"]

    store.create_decision(project_id=pid, title="采用方法 A", rationale="证据更充分")
    run = store.create_research_run(project_id=pid, workflow_id="paper", inputs={"seed": 1})
    finished = store.finish_research_run(run["id"], status="complete", outputs={"artifact": "out.md"})
    assert finished["status"] == "complete"
    edge = store.add_provenance_edge(project_id=pid, from_type="claim", from_id=claim["id"], to_type="evidence", to_id=evidence["id"], relation="supported_by")
    assert edge["from_id"] == claim["id"]

    overview = store.research_overview(pid)
    assert overview["counts"] == {
        "research_items": 1,
        "claims": 1,
        "evidence": 1,
        "decisions": 1,
        "research_runs": 1,
        "provenance_edges": 1,
    }
    assert overview["uncovered_claims"] == 0
    quality = store.research_quality_report(pid)
    assert quality["ready_for_synthesis"] is True


def test_project_isolation_and_invalid_link(tmp_path):
    store = PlatformStore(tmp_path / "platform.sqlite3")
    p1, p2 = store.ensure_project(tmp_path / "a"), store.ensure_project(tmp_path / "b")
    claim = store.create_claim(project_id=p1["id"], text="a")
    evidence = store.create_evidence(project_id=p2["id"], excerpt="b")
    try:
        store.link_evidence(project_id=p1["id"], claim_id=claim["id"], evidence_id=evidence["id"])
    except ValueError:
        pass
    else:
        raise AssertionError("cross-project evidence link must be rejected")


def test_durable_scheduler_queue_retries_and_leases(tmp_path):
    store = PlatformStore(tmp_path / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    job = store.enqueue_job(project_id=project["id"], workflow_id="paper", max_attempts=2)
    claimed = store.claim_job(worker_id="worker-a", lease_seconds=20)
    assert claimed and claimed["id"] == job["id"]
    retry = store.fail_job(job["id"], error="temporary", retry_delay=1)
    assert retry["status"] == "queued" and retry["attempts"] == 1
    time.sleep(1.05)
    claimed = store.claim_job(worker_id="worker-b", lease_seconds=20)
    assert claimed and claimed["attempts"] == 2
    terminal = store.fail_job(job["id"], error="fatal")
    assert terminal["status"] == "failed"


def test_versioned_workflow_and_interval_trigger(tmp_path):
    store = PlatformStore(tmp_path / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    saved = store.save_workflow_definition(project_id=project["id"], workflow_id="custom", definition={"steps": []})
    assert saved["version"] == 1 and saved["definition"] == {"steps": []}
    saved2 = store.save_workflow_definition(project_id=project["id"], workflow_id="custom", definition={"steps": ["a"]})
    assert saved2["version"] == 2
    trigger = store.create_workflow_trigger(project_id=project["id"], workflow_id="custom", interval_seconds=10)
    assert trigger["enabled"] is True
    assert store.release_due_triggers() == 1
    jobs = store.list_jobs(project["id"])
    assert jobs[0]["workflow_id"] == "custom"
