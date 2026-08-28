"""Host-level dispatcher for durable research workflow jobs.

The WebSocket is only an observer/interactive launcher.  This module owns the
same launch contract for durable queue jobs so a browser can disappear without
stopping a scheduled or background run.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from ..api import generate_paper
from ..config import generate_session_dir_name, resolve_model
from ..core import safe_resolve
from ..kernel.approval import QueueApprover
from ..kernel.budget import BudgetLimits
from ..workflows import get_workflow_registry
from ..workflows.runner import run_registered_workflow
from .platform_store import PlatformStore
from .task_hub import BackgroundTaskHub


def _allocate_output_dir(cwd: Path, query: str) -> Path:
    root = cwd / "writing_outputs"
    root.mkdir(parents=True, exist_ok=True)
    base = generate_session_dir_name(query)
    candidate = root / base
    try:
        candidate.mkdir()
    except FileExistsError:
        candidate = root / f"{base}_{uuid.uuid4().hex[:6]}"
        candidate.mkdir()
    return candidate


def _safe_output_dir(cwd: Path, value: object) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if not path.is_absolute():
        path = cwd / path
    path = path.resolve()
    safe_resolve(path, cwd)
    if path.exists() and not path.is_dir():
        raise ValueError("任务产物目录不是目录")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _persisted_workflow(store: PlatformStore, project_id: str, workflow_id: str) -> Any | None:
    """Decode a project-saved workflow using only registered Agent roles."""
    from ..workflows.registry import WorkflowDefinition, WorkflowStep

    rows = store.list_workflow_definitions(project_id, workflow_id=workflow_id, limit=1)
    if not rows:
        return None
    definition = rows[0].get("definition") or {}
    raw_steps = definition.get("steps") if isinstance(definition, dict) else None
    if not isinstance(raw_steps, list):
        return None
    steps: list[WorkflowStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict) or not str(raw.get("id") or "").strip():
            return None
        deps = raw.get("depends_on") or raw.get("dependencies") or []
        if not isinstance(deps, (list, tuple)):
            return None
        steps.append(WorkflowStep(
            id=str(raw["id"]), title=str(raw.get("title") or raw["id"]),
            role=str(raw.get("role") or ""), depends_on=tuple(str(x) for x in deps),
            prompt=str(raw.get("prompt") or ""),
        ))
    workflow = WorkflowDefinition(
        id=workflow_id,
        title=str(definition.get("title") or workflow_id),
        description=str(definition.get("description") or ""),
        steps=tuple(steps),
    )
    workflow.validate(get_workflow_registry().roles)
    return workflow


def _clear_rerun_checkpoints(output_dir: Path, workflow: Any, step_id: str) -> None:
    """Invalidate a node and all descendants while retaining upstream results."""
    known = {step.id for step in workflow.steps}
    if step_id not in known:
        raise ValueError(f"工作流节点不存在: {step_id}")
    descendants = {step_id}
    changed = True
    while changed:
        changed = False
        for step in workflow.steps:
            if step.id not in descendants and any(parent in descendants for parent in step.depends_on):
                descendants.add(step.id)
                changed = True
    checkpoint_root = output_dir / ".ra" / "workflow"
    for current in descendants:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in current)
        (checkpoint_root / f"{safe}.json").unlink(missing_ok=True)


def build_scheduler_dispatcher(*, store: PlatformStore, hub: BackgroundTaskHub,
                               cwd: Path, project: dict[str, Any], source_store: Any,
                               default_model: str) -> tuple[dict[str, Any], Any]:
    """Return built-in workflow dispatchers and the shared dispatch function."""

    async def dispatch(job: dict[str, Any]) -> None:
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        workflow_id = str(job.get("workflow_id") or payload.get("workflow_id") or "").strip()
        registry = get_workflow_registry()
        if workflow_id == "single":
            workflow = None
        else:
            try:
                workflow = registry.get_workflow(workflow_id)
            except KeyError:
                workflow = _persisted_workflow(store, project["id"], workflow_id)
                if workflow is None:
                    raise ValueError(f"未知工作流: {workflow_id}") from None

        query = str(payload.get("query") or f"后台执行：{workflow.title if workflow is not None else '单 Agent 任务'}").strip()
        if not query:
            raise ValueError("后台任务缺少 query")
        output_dir = _safe_output_dir(cwd, payload.get("output_dir"))
        if output_dir is None:
            output_dir = _allocate_output_dir(cwd, query)
        rerun_step = str(payload.get("rerun_step") or "").strip()
        if rerun_step:
            if workflow is None or workflow_id in {"single", "paper"}:
                raise ValueError("当前工作流不支持节点级重跑")
            _clear_rerun_checkpoints(output_dir, workflow, rerun_step)
        model = resolve_model(payload.get("model") or default_model)
        provider = payload.get("provider")
        budget_limits = BudgetLimits(
            max_cost_usd=payload.get("max_cost_usd") or None,
            max_wall_seconds=payload.get("max_wall_seconds") or None,
        )

        async def runner(handle):
            def _push_approval(request) -> None:
                handle.approval_request_id = request.request_id
                task_record = store.get_task(handle.task_id) or {}
                task_metadata = task_record.get("metadata") or {}
                store.create_agent_approval(
                    project_id=handle.project_id, task_id=handle.task_id,
                    thread_id=task_metadata.get("thread_id"), turn_id=task_metadata.get("turn_id"),
                    agent_id=request.agent_id, role=request.agent_role,
                    tool_name=request.tool_name, arguments=request.arguments, summary=request.summary(),
                    approval_id=request.request_id,
                )
                asyncio.get_running_loop().create_task(hub.publish(handle.task_id, {
                    "type": "approval_request", "id": request.request_id or handle.task_id,
                    "tool": request.tool_name, "summary": request.summary(),
                    "agent_id": getattr(request, "agent_id", ""),
                    "role": getattr(request, "agent_role", ""),
                }))

            approver = QueueApprover(handle.approvals, timeout=120.0, on_request=_push_approval)
            retrieval_block = ""
            if source_store is not None:
                retrieval_block = await asyncio.to_thread(
                    source_store.export_context_block, query.split()[:6],
                )
            instructions = str(project.get("instructions") or "")
            if workflow_id == "paper":
                generation = generate_paper(
                    query=query, cwd=str(cwd), model=payload.get("model"),
                    provider=provider, multi_agent=True,
                    data_files=payload.get("data_files") if isinstance(payload.get("data_files"), list) else None,
                    cancel_event=handle.cancel_event, budget_limits=budget_limits,
                    approver=approver, track_token_usage=True, steer_queue=handle.steers,
                    output_dir=str(output_dir), project_instructions=instructions,
                    retrieval_block=retrieval_block,
                )
            elif workflow_id == "single":
                generation = generate_paper(
                    query=query, cwd=str(cwd), model=payload.get("model"),
                    provider=provider, multi_agent=False,
                    data_files=payload.get("data_files") if isinstance(payload.get("data_files"), list) else None,
                    cancel_event=handle.cancel_event, budget_limits=budget_limits,
                    approver=approver, track_token_usage=True, steer_queue=handle.steers,
                    output_dir=str(output_dir), project_instructions=instructions,
                    retrieval_block=retrieval_block,
                )
            else:
                generation = run_registered_workflow(
                    workflow=workflow, query=query, model=model, work_dir=cwd,
                    output_dir=output_dir, provider=provider,
                    cancel_event=handle.cancel_event, budget_limits=budget_limits,
                    approver=approver, steer_queue=handle.steers,
                    project_instructions=instructions, retrieval_block=retrieval_block,
                )
            try:
                async for update in generation:
                    yield update
            finally:
                await generation.aclose()

        handle = hub.start(
            project_id=project["id"], query=query,
            mode="pipeline" if workflow_id == "paper" else ("single" if workflow_id == "single" else f"workflow:{workflow_id}"),
            runner_factory=runner, output_dir=str(output_dir),
            metadata={"workflow_id": workflow_id, "scheduler_job_id": job.get("id"), "background": True},
            steps=[step.to_task_step() for step in workflow.steps] if workflow is not None else [],
            source_session_id=str(payload.get("source_session_id") or "") or None,
        )
        await asyncio.to_thread(store.attach_job_task, str(job["id"]), handle.task_id)
        if handle.task is not None:
            await handle.task
        if handle.status != "complete":
            raise RuntimeError(f"后台工作流 {workflow_id} {handle.status}: {store.get_task(handle.task_id) or {}}")

    dispatchers = {workflow_id: dispatch for workflow_id in ["single", *registry_ids(get_workflow_registry())]}
    # 项目内持久化的自定义工作流补注册同一个通用 dispatch：否则后台队列里
    # 引用自定义 id 的作业会因「未注册工作流执行器」直接失败。dispatch 内部
    # 会经 _persisted_workflow 加载最新版本定义并走 run_registered_workflow
    # 执行路径。取舍：内置 id 一律优先 —— 即使用户把定义存成内置 id，仍按
    # 内置版执行，避免「所存非所跑」的静默覆盖；禁用(enabled=0)的定义不注册。
    builtin_ids = set(dispatchers)
    seen: set[str] = set()
    for row in store.list_workflow_definitions(project["id"], limit=1000):
        wf_id = str(row.get("id") or "").strip()
        if not wf_id or wf_id in builtin_ids or wf_id in seen or not row.get("enabled"):
            continue
        seen.add(wf_id)
        dispatchers[wf_id] = dispatch
    return dispatchers, dispatch


def registry_ids(registry: Any) -> list[str]:
    return sorted(str(item["id"]) for item in registry.list_workflows())
