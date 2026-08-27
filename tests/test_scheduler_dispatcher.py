"""Durable queue -> BackgroundTaskHub integration tests."""

import asyncio

from research_assistant.runtime import BackgroundTaskHub, PlatformStore
from research_assistant.runtime import scheduler_dispatcher as dispatcher_module
from research_assistant.runtime.scheduler_dispatcher import (
    _clear_rerun_checkpoints,
    build_scheduler_dispatcher,
)
from research_assistant.workflows import get_workflow_registry


def test_scheduler_dispatcher_launches_and_attaches_task(tmp_path, monkeypatch):
    async def fake_generate_paper(**_kwargs):
        yield {"type": "progress", "stage": "initialization", "message": "ok"}
        yield {"type": "result", "status": "success", "output_dir": str(tmp_path / "writing_outputs")}

    monkeypatch.setattr(dispatcher_module, "generate_paper", fake_generate_paper)
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    hub = BackgroundTaskHub(store)
    _dispatchers, dispatch = build_scheduler_dispatcher(
        store=store, hub=hub, cwd=tmp_path, project=project,
        source_store=None, default_model="test-model",
    )
    job = store.enqueue_job(
        project_id=project["id"], workflow_id="single",
        payload={"query": "验证后台任务"},
    )
    claimed = store.claim_job(worker_id="test")
    assert claimed and claimed["id"] == job["id"]

    asyncio.run(dispatch(claimed))
    row = store.list_jobs(project["id"])[0]
    assert row["task_id"]
    task = store.get_task(row["task_id"])
    assert task and task["status"] == "complete"
    assert store.read_events(row["task_id"])


def test_rerun_clears_target_and_downstream_checkpoints(tmp_path):
    workflow = get_workflow_registry().get_workflow("research_sprint")
    root = tmp_path / "out" / ".ra" / "workflow"
    root.mkdir(parents=True)
    for step in workflow.steps:
        (root / f"{step.id}.json").write_text("{}", encoding="utf-8")
    _clear_rerun_checkpoints(tmp_path / "out", workflow, "evidence")
    assert (root / "scope.json").is_file()
    assert not (root / "evidence.json").exists()
    assert not (root / "action.json").exists()


def test_resource_backpressure_defers_without_consuming_attempt(tmp_path):
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    job = store.enqueue_job(
        project_id=project["id"], workflow_id="single", payload={"model": "shared"},
    )
    claimed = store.claim_job(worker_id="test")
    assert claimed and claimed["attempts"] == 1
    deferred = store.defer_job(job["id"], delay=0.25, reason="provider busy")
    assert deferred and deferred["status"] == "queued"
    assert deferred["attempts"] == 1
    assert deferred["last_error"] == "provider busy"


def test_resource_lease_is_shared_between_store_processes(tmp_path):
    path = tmp_path / ".ra" / "platform.sqlite3"
    first = PlatformStore(path)
    second = PlatformStore(path)
    project = first.ensure_project(tmp_path)
    job = first.enqueue_job(project_id=project["id"], workflow_id="single")
    other = first.enqueue_job(project_id=project["id"], workflow_id="single")
    lease = first.acquire_resource_lease(
        resource_key="provider:model", worker_id="one", job_id=job["id"], max_slots=1,
    )
    assert lease
    assert second.acquire_resource_lease(
        resource_key="provider:model", worker_id="two", job_id=other["id"], max_slots=1,
    ) is None
    assert second.release_resource_lease(lease["id"])
    assert second.acquire_resource_lease(
        resource_key="provider:model", worker_id="two", job_id=other["id"], max_slots=1,
    )


def test_persisted_custom_workflow_gets_generic_dispatcher(tmp_path):
    """项目内持久化的自定义工作流必须能被后台队列执行。

    此前 dispatchers 只含内置 id，引用自定义 id 的作业一律
    「未注册工作流执行器」失败。构建函数应补注册通用 dispatch；
    内置 id 优先，用户把定义存成内置 id 也不会顶掉内置版。
    """
    store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
    project = store.ensure_project(tmp_path)
    hub = BackgroundTaskHub(store)
    store.save_workflow_definition(
        project_id=project["id"], workflow_id="custom_flow",
        definition={
            "title": "自定义流程", "description": "",
            "steps": [{"id": "s1", "title": "第一步", "role": "planner", "prompt": "p"}],
        },
    )
    # 禁用的定义不注册
    store.save_workflow_definition(
        project_id=project["id"], workflow_id="disabled_flow",
        definition={"steps": []}, enabled=False,
    )
    dispatchers, dispatch = build_scheduler_dispatcher(
        store=store, hub=hub, cwd=tmp_path, project=project,
        source_store=None, default_model="test-model",
    )
    builtin = {"single", "paper", "research_sprint", "data_analysis"}
    assert builtin.issubset(dispatchers.keys())
    assert "custom_flow" in dispatchers  # 自定义 id 可查得
    assert callable(dispatchers["custom_flow"])
    # 注册的是通用执行器：dispatch 的持久化回退能解码该定义（不必真跑 LLM）
    workflow = dispatcher_module._persisted_workflow(store, project["id"], "custom_flow")
    assert workflow is not None
    assert [step.id for step in workflow.steps] == ["s1"]
    assert "disabled_flow" not in dispatchers
    # 内置优先：即便把定义存成内置 id，注册表仍只含内置 + 自定义，不覆盖内置项
    store.save_workflow_definition(
        project_id=project["id"], workflow_id="research_sprint",
        definition={"steps": [{"id": "x", "role": "nonexistent_role"}]},
    )
    rebuilt, _ = build_scheduler_dispatcher(
        store=store, hub=hub, cwd=tmp_path, project=project,
        source_store=None, default_model="test-model",
    )
    assert set(rebuilt) == builtin | {"custom_flow"}
