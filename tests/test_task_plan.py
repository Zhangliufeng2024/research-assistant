import asyncio
import sqlite3

from research_assistant.runtime import PlatformStore


def test_task_steps_persist_status_and_dependencies(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    store.create_task(task_id="t1", project_id=project["id"], query="q", mode="pipeline")
    store.create_steps("t1", [
        {"id": "plan", "title": "Plan"},
        {"id": "write", "title": "Write", "depends_on": ["plan"]},
    ])
    store.update_step("t1", "plan", status="running")
    store.update_step("t1", "plan", status="done")
    assert [(s["id"], s["status"], s["depends_on"]) for s in store.list_steps("t1")] == [
        ("plan", "done", []), ("write", "pending", ["plan"])
    ]


def test_platform_store_migrates_project_instructions_column(tmp_path):
    db = tmp_path / ".ra" / "platform.sqlite3"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE projects (id TEXT PRIMARY KEY, root TEXT NOT NULL UNIQUE, "
            "name TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL)"
        )
    store = PlatformStore(db)
    project = store.ensure_project(tmp_path)
    assert project["instructions"] == ""
    assert store.update_project_instructions(project["id"], instructions="规范") is not None


def test_parallel_branches_close_when_assembly_starts(tmp_path):
    from research_assistant.runtime.task_hub import _advance_steps

    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    store.create_task(task_id="t2", project_id=project["id"], query="q", mode="pipeline")
    store.create_steps("t2", [
        {"id": "plan", "title": "Plan"},
        {"id": "research", "title": "Research"},
        {"id": "figures", "title": "Figures"},
        {"id": "assemble", "title": "Assemble"},
    ])
    store.update_step("t2", "research", status="running")
    store.update_step("t2", "figures", status="running")
    _advance_steps(store, "t2", "assemble")
    statuses = {step["id"]: step["status"] for step in store.list_steps("t2")}
    assert statuses == {"plan": "pending", "research": "done", "figures": "done", "assemble": "pending"}


def test_task_metrics_include_events_and_elapsed_steps(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    store.create_task(task_id="t3", project_id=project["id"], query="q", mode="pipeline")
    store.create_steps("t3", [{"id": "plan", "title": "Plan"}])
    store.update_step("t3", "plan", status="running")
    store.append_event("t3", {"type": "progress", "stage": "planning"})
    store.update_step("t3", "plan", status="done")
    metrics = store.task_metrics("t3")
    assert metrics and metrics["event_count"] == 1
    assert metrics["steps"][0]["seconds"] is not None


def test_task_metrics_uses_dag_critical_path_for_parallel_nodes(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    store.create_task(task_id="t4", project_id=project["id"], query="q", mode="pipeline")
    store.create_steps("t4", [
        {"id": "plan", "title": "Plan"},
        {"id": "research", "title": "Research", "depends_on": ["plan"]},
        {"id": "figures", "title": "Figures", "depends_on": ["plan"]},
        {"id": "assemble", "title": "Assemble", "depends_on": ["research", "figures"]},
    ])
    # Use deterministic timestamps to make the expected longest path clear.
    with sqlite3.connect(store.path) as conn:
        conn.execute("UPDATE task_steps SET started_at=0, finished_at=1 WHERE task_id='t4'")
        conn.execute("UPDATE task_steps SET started_at=0, finished_at=2 WHERE task_id='t4' AND id='research'")
        conn.execute("UPDATE task_steps SET started_at=0, finished_at=3 WHERE task_id='t4' AND id='figures'")
        conn.execute("UPDATE task_steps SET started_at=0, finished_at=4 WHERE task_id='t4' AND id='assemble'")
    metrics = store.task_metrics("t4")
    assert metrics and metrics["critical_path_seconds"] == 8.0


def test_task_hub_persists_frames_without_changing_sequence(tmp_path):
    from research_assistant.runtime.task_hub import BackgroundTaskHub

    async def run():
        store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
        project = store.ensure_project(tmp_path)
        hub = BackgroundTaskHub(store)
        async def empty_runner(_):
            if False:
                yield {}

        handle = hub.start(project_id=project["id"], query="q", mode="single", runner_factory=empty_runner)
        # The runner is not started for this persistence-only assertion.
        handle.task.cancel()
        first = await hub.publish(handle.task_id, {"type": "progress", "stage": "planning"})
        second = await hub.publish(handle.task_id, {"type": "progress", "stage": "planning"})
        assert [item["seq"] for item in store.read_events(handle.task_id)] == [1, 2]
        assert first is None and second is None

    asyncio.run(run())
