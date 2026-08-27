"""Executor for declarative, non-paper research workflows."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from ..agent import AgentResult, RunConfig, run_agent
from ..core import atomic_write_text, execution_contract_addendum
from ..kernel.budget import BudgetExceededError, BudgetGuard, BudgetLimits
from ..kernel.events import EventKind, HookBus, HookVerdict
from ..llm.factory import create_llm_client
from ..tools.registry import ToolRegistry
from .registry import (
    WorkflowDefinition,
    WorkflowStep,
    get_workflow_registry,
    resolve_role_model,
)
from .supervisor import AgentSupervisor, AgentTaskSpec


def _progress(step: WorkflowStep, message: str, status: str = "running") -> dict[str, Any]:
    return {
        "type": "progress",
        "stage": step.id,
        "message": message,
        "details": {"step_id": step.id, "status": status, "role": step.role},
    }


def _state_path(output_dir: Path, step_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in step_id)
    return output_dir / ".ra" / "workflow" / f"{safe}.json"


def _query_fingerprint(query: str) -> str:
    """查询指纹（缺陷 H2）：同一 output_dir 换查询时旧 checkpoint 不再复用。"""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _load_checkpoint(path: Path, query_hash: str) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        stored = data.get("query_hash")
        if stored is not None and stored != query_hash:
            # 查询已变：旧 checkpoint 的答案与新任务无关，视为待跑。
            return None
        if data.get("status") == "complete" and isinstance(data.get("text"), str):
            return data["text"]
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    return None


def _aggregate_step_usage(top: BudgetGuard, snapshot: dict[str, Any]) -> None:
    """把单个节点的用量聚合进顶层预算（缺陷 H1）。

    此前顶层 BudgetGuard 从未被喂入用量——每节点只有独立 step_budget，
    全局帽形同虚设。这里直接累加 state 字段并采用节点快照里按角色模型
    价格算出的 cost_usd（比用顶层价格表重算更准）；不走 record()，因为
    那会把整个节点记成一「轮」，破坏顶层轮次上限的语义。调度在事件循环
    内串行进行，无需持锁。
    """
    state = top.state
    state.input_tokens += int(snapshot.get("input_tokens", 0))
    state.output_tokens += int(snapshot.get("output_tokens", 0))
    state.cache_creation_tokens += int(snapshot.get("cache_creation_tokens", 0))
    state.cache_read_tokens += int(snapshot.get("cache_read_tokens", 0))
    state.turns += int(snapshot.get("turns", 0))
    state.cost_usd += float(snapshot.get("cost_usd", 0.0))


async def _run_step(
    step: WorkflowStep,
    role_prompt: str,
    *,
    query: str,
    context: str,
    model: str,
    work_dir: Path,
    output_dir: Path,
    api_key: str | None,
    base_url: str | None,
    provider: str | None,
    budget: BudgetGuard,
    hooks: HookBus,
    cancel_event: asyncio.Event | None,
    approver: Any | None,
    steer_queue: asyncio.Queue | None,
    max_continuations: int,
    allowed_tools: tuple[str, ...] = (),
    approval_tools: tuple[str, ...] = (),
) -> AgentResult:
    client = create_llm_client(
        api_key=api_key, base_url=base_url, model=model, provider=provider,
    )
    prompt = (
        f"研究任务：{query}\n\n"
        f"当前工作流节点：{step.title}\n"
        f"节点要求：{step.prompt or '完成该节点并留下可审计的研究记录。'}\n\n"
        f"上游节点结果（可能为空）：\n{context[-12_000:]}"
    )
    system = (
        f"{role_prompt}\n\n"
        "你属于一个可恢复的科研工作流。结论必须区分事实、推断和不确定性；"
        "优先使用工作区工具保存可复现产物。\n"
        f"工作流产物目录：{output_dir}\n"
        f"{execution_contract_addendum()}"
    )
    step_hooks = hooks.fork()
    if approval_tools:
        async def _require_role_approval(event: Any) -> HookVerdict | None:
            if event.tool_name in approval_tools:
                return HookVerdict(allowed=True, ask=True, reason="该 Agent 角色要求人工审批")
            return None
        step_hooks.on(EventKind.PRE_TOOL_USE, _require_role_approval)
    try:
        result = await run_agent(
            prompt=prompt,
            system_prompt=system,
            llm_client=client,
            tools=ToolRegistry(
                work_dir=str(work_dir), write_anchor=str(output_dir),
                allowed_tools=allowed_tools or None,
            ),
            config=RunConfig(
                budget=budget,
                hooks=step_hooks,
                cancel_event=cancel_event,
                approver=approver,
                max_continuations=max_continuations,
                session_log=None,
                agent_id=step.id,
                agent_role=step.role,
            ),
            steer_queue=steer_queue,
        )
        result.budget_snapshot = budget.snapshot()
        return result
    finally:
        await client.close()


async def run_registered_workflow(
    workflow: WorkflowDefinition,
    query: str,
    model: str,
    work_dir: Path,
    output_dir: Path,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    provider: str | None = None,
    cancel_event: asyncio.Event | None = None,
    budget_limits: BudgetLimits | None = None,
    approver: Any | None = None,
    steer_queue: asyncio.Queue | None = None,
    project_instructions: str = "",
    retrieval_block: str = "",
) -> AsyncGenerator[dict[str, Any], None]:
    """Execute any declarative workflow with parallel ready nodes.

    Completed node checkpoints are JSON records under the durable output root;
    restarting the task therefore skips nodes that already produced a result.
    The paper workflow deliberately uses its specialized executor instead.
    """
    registry = get_workflow_registry()
    workflow.validate(registry.roles)
    output_dir.mkdir(parents=True, exist_ok=True)
    budget = BudgetGuard(limits=budget_limits or BudgetLimits.from_env(), model=model)
    hooks = HookBus()
    completed: dict[str, str] = {}
    pending = {step.id: step for step in workflow.steps}
    project_context = (
        f"\n\n项目长期指令：\n{project_instructions.strip()}"
        if project_instructions.strip() else ""
    )
    retrieval_context = f"\n\n{retrieval_block.strip()}" if retrieval_block.strip() else ""
    try:
        concurrency = int(os.getenv("RA_AGENT_CONCURRENCY", "4"))
    except ValueError:
        concurrency = 4
    supervisor_events: list[dict[str, Any]] = []
    supervisor = AgentSupervisor(max_concurrency=concurrency, event_sink=supervisor_events.append)

    # Restore node-level checkpoints before scheduling new work.
    query_hash = _query_fingerprint(query)
    for step in workflow.steps:
        text = _load_checkpoint(_state_path(output_dir, step.id), query_hash)
        if text is not None:
            completed[step.id] = text
            pending.pop(step.id, None)
            yield _progress(step, f"已恢复节点：{step.title}", "resumed")

    while pending:
        if cancel_event is not None and cancel_event.is_set():
            yield {"type": "progress", "stage": "cancelled", "message": "工作流已取消"}
            return
        # 全局预算闸门（缺陷 H1）：上一波聚合后的用量若已触顶，终止而不是
        # 继续调度烧钱。check() 硬 breach 抛 BudgetExceededError。
        try:
            budget.check()
        except BudgetExceededError as exc:
            yield {
                "type": "result", "status": "failed", "workflow_id": workflow.id,
                "error": f"全局预算超限：{exc.report}",
            }
            return
        ready = [
            step for step in pending.values()
            if all(parent in completed for parent in step.depends_on)
        ]
        if not ready:
            raise RuntimeError(f"workflow {workflow.id} cannot make progress; dependency cycle or missing node")
        for step in ready:
            yield _progress(step, f"开始：{step.title}")

        async def execute(step: WorkflowStep) -> tuple[WorkflowStep, AgentResult, float]:
            started = time.monotonic()
            upstream = "\n\n".join(
                f"[{parent}]\n{completed[parent]}" for parent in step.depends_on
            )
            if step.id == "evidence":
                upstream += retrieval_context
            role = registry.get_role(step.role)
            step_model = resolve_role_model(model, role.model_tier)
            step_budget = BudgetGuard(limits=role.budget_limits(budget_limits), model=step_model)
            result = await _run_step(
                step,
                role.system_prompt + project_context,
                query=query,
                context=upstream,
                model=step_model,
                work_dir=work_dir,
                output_dir=output_dir,
                api_key=api_key,
                base_url=base_url,
                provider=provider,
                budget=step_budget,
                hooks=hooks,
                cancel_event=cancel_event,
                approver=approver,
                steer_queue=steer_queue,
                max_continuations=role.max_continuations,
                allowed_tools=role.tool_allowlist,
                approval_tools=role.approval_tools,
            )
            return step, result, time.monotonic() - started

        specs = [AgentTaskSpec(
            step.id, step.role, tuple(step.depends_on),
            metadata={"workflow_id": workflow.id, "title": step.title},
            timeout_seconds=step.timeout_seconds,
        ) for step in ready]
        ready_by_id = {step.id: step for step in ready}
        async def execute_spec(spec: AgentTaskSpec, ready_steps: dict[str, WorkflowStep] = ready_by_id) -> Any:
            return await execute(ready_steps[spec.id])

        results = await supervisor.run_ready(specs, execute_spec, cancel_event=cancel_event)
        for event in supervisor_events:
            yield event
        supervisor_events.clear()
        result_by_id = {item.task_id: item for item in results}
        for step in ready:
            agent_result = result_by_id[step.id]
            if agent_result.status == "cancelled":
                yield _progress(step, f"{step.title} 已取消", "cancelled")
                yield {"type": "progress", "stage": "cancelled", "message": "工作流已取消"}
                return
            if agent_result.status == "failed":
                yield _progress(step, agent_result.error or f"{step.title} 失败", "failed")
                yield {
                    "type": "result", "status": "failed", "workflow_id": workflow.id,
                    "failed_step": step.id, "error": agent_result.error or "agent failed",
                }
                return
            step, result, elapsed = await _normalize_supervised_result(step, agent_result)
            if not result.success:
                yield _progress(step, result.error or f"{step.title} 失败", "failed")
                yield {
                    "type": "result", "status": "failed", "workflow_id": workflow.id,
                    "failed_step": step.id, "error": result.error or "agent failed",
                }
                return
            text = result.text_output.strip()
            completed[step.id] = text
            pending.pop(step.id, None)
            # 缺陷 H1：把该节点的真实用量聚合进顶层预算，供下一波的闸门检查。
            _aggregate_step_usage(budget, result.budget_snapshot or {})
            state = {
                "status": "complete", "workflow_id": workflow.id,
                "step_id": step.id, "role": step.role, "text": text,
                "seconds": round(elapsed, 3), "updated_at": time.time(),
                "query_hash": query_hash,
            }
            atomic_write_text(
                _state_path(output_dir, step.id),
                json.dumps(state, ensure_ascii=False, indent=2),
            )
            yield _progress(step, f"完成：{step.title}", "done")
            if text:
                yield {"type": "text", "content": f"[{step.title}]\n{text}\n"}
            yield {"type": "usage", "budget": result.budget_snapshot or budget.snapshot(), "agent_id": step.id, "role": step.role}

    yield {
        "type": "result", "status": "success", "workflow_id": workflow.id,
        "output_dir": str(output_dir), "steps": list(completed),
    }


async def _normalize_supervised_result(step: WorkflowStep, result: Any) -> tuple[WorkflowStep, AgentResult, float]:
    """Keep the runner's historical tuple contract behind the supervisor."""
    _step, agent_result, elapsed = result.value
    return _step, agent_result, float(elapsed)
