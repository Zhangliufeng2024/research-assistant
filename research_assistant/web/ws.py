"""WebSocket transport for durable background document generation."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..api import generate_paper
from ..config import generate_session_dir_name, resolve_model
from ..core import safe_resolve
from ..kernel.budget import BudgetLimits
from ..workflows import get_workflow_registry
from ..workflows.runner import run_registered_workflow

router = APIRouter()
MAX_QUERY_LENGTH = 10_000
MAX_STEER_LENGTH = 2_000


def _validate_resume_dir(output_folder: object, name: str) -> tuple[Path | None, str]:
    if not name or name in (".", ".."):
        return None, "resume_run 目录名不合法"
    if "/" in name or "\\" in name or ":" in name:
        return None, "resume_run 目录名不能包含路径分隔符"
    if output_folder is None:
        return None, "输出目录不可用，无法续跑"
    root = Path(str(output_folder))
    if not root.is_dir():
        return None, "输出目录不可用，无法续跑"
    run_dir = root / name
    try:
        safe_resolve(run_dir, root)
    except ValueError:
        return None, "路径不合法"
    if not run_dir.is_dir():
        return None, f"运行目录不存在: {name}"
    if not (run_dir / "run.json").is_file():
        return None, f"缺少 run.json，无法续跑: {name}"
    return run_dir, ""


def _read_resume_query(run_dir: Path) -> str:
    try:
        state = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        state = {}
    return str(state.get("query") or "").strip() if isinstance(state, dict) else ""


def _allocate_output_dir(cwd: Path, query: str) -> Path:
    """Allocate a stable run directory before the generator starts.

    Durable task rows must know their artifact root even if the process dies
    before the first progress frame.  The short random suffix only handles
    two launches in the same second; normal UI names remain timestamped.
    """
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


def _validate_task_output_dir(cwd: Path, value: object) -> Path | None:
    """Validate a persisted artifact root before resuming a durable task."""
    if not value:
        return None
    path = Path(str(value)).resolve()
    try:
        safe_resolve(path, cwd)
    except ValueError as exc:
        raise ValueError("任务产物目录不在当前工作区内，无法续跑") from exc
    if not path.is_dir():
        raise ValueError("任务产物目录不存在，无法续跑")
    return path


def _parse_start(websocket: WebSocket, msg: dict) -> dict:
    resume_name = str(msg.get("resume_run") or "").strip()
    output_dir: str | None = None
    multi_agent = bool(msg.get("multi_agent", False))
    if resume_name:
        run_dir, error = _validate_resume_dir(
            getattr(websocket.app.state, "output_folder", None), resume_name,
        )
        if error:
            raise ValueError(error)
        query = _read_resume_query(run_dir) if run_dir is not None else ""
        if not query:
            raise ValueError(f"无法续跑: {resume_name} 的 run.json 缺少 query")
        output_dir = str(run_dir)
        multi_agent = True
    else:
        query = str(msg.get("query") or "").strip()
        if not query:
            raise ValueError("query 不能为空")
        if len(query) > MAX_QUERY_LENGTH:
            raise ValueError(f"query 过长（最大 {MAX_QUERY_LENGTH} 字符）")
    return {
        "query": query, "resume_name": resume_name,
        "output_dir": output_dir, "multi_agent": multi_agent,
    }


@router.websocket("/ws/generate")
async def ws_generate(websocket: WebSocket):
    """Create or observe work; disconnecting only removes the observer."""
    await websocket.accept()
    legacy_mode = not hasattr(websocket.app.state, "task_hub")
    if legacy_mode:
        # Test harnesses and embedders that construct a bare FastAPI app do not
        # run the normal lifespan.  Install the same runtime lazily there.
        from ..runtime import BackgroundTaskHub, PlatformStore
        root = Path(getattr(websocket.app.state, "cwd", Path.cwd()))
        store = PlatformStore(root / ".ra" / "platform.sqlite3")
        websocket.app.state.platform_store = store
        websocket.app.state.project = store.ensure_project(root)
        websocket.app.state.task_hub = BackgroundTaskHub(store)
        websocket.app.state.active_tasks = getattr(websocket.app.state, "active_tasks", {})
    hub = websocket.app.state.task_hub
    task_id = ""
    event_queue: asyncio.Queue | None = None
    pump: asyncio.Task | None = None
    try:
        msg = await websocket.receive_json()
        action = msg.get("action")
        if action == "observe":
            task_id = str(msg.get("task_id") or "").strip()
            task_record = websocket.app.state.platform_store.get_task(task_id)
            if (
                task_record is None
                or task_record.get("project_id") != websocket.app.state.project["id"]
            ):
                raise ValueError("任务不存在")
            event_queue = hub.subscribe(task_id, after=int(msg.get("after") or 0))
            await websocket.send_json({
                "type": "connected", "task_id": task_id, "observing": True,
                "background": True, "status": task_record.get("status"),
            })
        elif action in {"start", "resume_task"}:
            resumed_from: str | None = None
            registry = get_workflow_registry()
            if action == "resume_task":
                resumed_from = str(msg.get("task_id") or "").strip()
                task_record = websocket.app.state.platform_store.get_task(resumed_from)
                if (
                    task_record is None
                    or task_record.get("project_id") != websocket.app.state.project["id"]
                ):
                    raise ValueError("任务不存在")
                if task_record.get("status") not in {
                    "interrupted", "failed", "cancelled"
                }:
                    raise ValueError("只有中断、失败或取消的任务可以续跑")
                query = str(task_record.get("query") or "").strip()
                if not query:
                    raise ValueError("任务缺少 query，无法续跑")
                output_path = _validate_task_output_dir(
                    Path(websocket.app.state.cwd), task_record.get("output_dir")
                )
                output_dir = str(output_path) if output_path is not None else None
                resume_name = output_path.name if output_path is not None else ""
                multi_agent = task_record.get("mode") != "single"
                metadata = task_record.get("metadata") or {}
                workflow_id = str(
                    metadata.get("workflow_id")
                    or ("paper" if task_record.get("mode") == "pipeline" else "single")
                )
            else:
                parsed = _parse_start(websocket, msg)
                query = parsed["query"]
                resume_name = parsed["resume_name"]
                output_dir = parsed["output_dir"]
                multi_agent = parsed["multi_agent"]
                workflow_id = str(msg.get("workflow_id") or ("paper" if multi_agent else "single"))
            if multi_agent:
                try:
                    workflow = registry.get_workflow(workflow_id)
                except KeyError as exc:
                    raise ValueError(str(exc)) from exc
            else:
                workflow = None
                workflow_id = "single"
            cwd = Path(websocket.app.state.cwd)
            if output_dir is None:
                output_dir = str(_allocate_output_dir(cwd, query))
            budget_limits = BudgetLimits(
                max_cost_usd=msg.get("max_cost_usd") or None,
                max_wall_seconds=msg.get("max_wall_seconds") or None,
            )

            async def _runner(handle):
                from ..kernel.approval import QueueApprover

                def _push_approval(request) -> None:
                    handle.approval_request_id = request.request_id
                    task_record = websocket.app.state.platform_store.get_task(handle.task_id) or {}
                    task_metadata = task_record.get("metadata") or {}
                    websocket.app.state.platform_store.create_agent_approval(
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

                approver = QueueApprover(
                    handle.approvals, timeout=120.0, on_request=_push_approval,
                )
                source_store = getattr(websocket.app.state, "source_store", None)
                retrieval_block = (
                    await asyncio.to_thread(source_store.export_context_block, query.split()[:6])
                    if source_store is not None else ""
                )
                project_instructions = str(
                    websocket.app.state.project.get("instructions") or ""
                )
                if workflow_id == "paper":
                    generation = generate_paper(
                        query=query, cwd=str(cwd), model=msg.get("model"),
                        provider=msg.get("provider"), multi_agent=True,
                        data_files=msg.get("data_files"), cancel_event=handle.cancel_event,
                        budget_limits=budget_limits, approver=approver,
                        track_token_usage=True, steer_queue=handle.steers,
                        output_dir=output_dir,
                        project_instructions=project_instructions,
                        retrieval_block=retrieval_block,
                    )
                elif workflow_id == "single":
                    generation = generate_paper(
                        query=query, cwd=str(cwd), model=msg.get("model"),
                        provider=msg.get("provider"), multi_agent=False,
                        data_files=msg.get("data_files"), cancel_event=handle.cancel_event,
                        budget_limits=budget_limits, approver=approver,
                        track_token_usage=True, steer_queue=handle.steers,
                        output_dir=output_dir,
                        project_instructions=project_instructions,
                        retrieval_block=retrieval_block,
                    )
                else:
                    generation = run_registered_workflow(
                        workflow=workflow,
                        query=query,
                        model=resolve_model(msg.get("model")),
                        work_dir=cwd,
                        output_dir=Path(output_dir),
                        provider=msg.get("provider"),
                        cancel_event=handle.cancel_event,
                        budget_limits=budget_limits,
                        approver=approver,
                        steer_queue=handle.steers,
                        project_instructions=project_instructions,
                        retrieval_block=retrieval_block,
                    )
                try:
                    async for update in generation:
                        yield update
                finally:
                    await generation.aclose()
                    websocket.app.state.active_tasks.pop(handle.task_id, None)

            handle = hub.start(
                project_id=websocket.app.state.project["id"], query=query,
                mode=("pipeline" if workflow_id == "paper" else f"workflow:{workflow_id}")
                if multi_agent else "single",
                runner_factory=_runner, output_dir=output_dir,
                metadata={
                    "resume_run": resume_name or None,
                    "resumed_from": resumed_from,
                    "workflow_id": workflow_id,
                },
                steps=(
                    [step.to_task_step() for step in workflow.steps]
                    if workflow is not None else []
                ),
            )
            task_id = handle.task_id
            websocket.app.state.active_tasks[task_id] = {
                "status": "running", "query": query[:100],
                "cancel_event": handle.cancel_event,
                "approvals": handle.approvals, "steers": handle.steers,
            }
            event_queue = hub.subscribe(task_id)
            await websocket.send_json({
                "type": "connected", "task_id": task_id,
                "resumed": resume_name or None,
                "resumed_from": resumed_from,
                "workflow_id": workflow_id,
                "background": True,
            })
        else:
            raise ValueError("Expected action: start, resume_task or observe")

        if event_queue is None:
            raise ValueError("无法订阅任务")

        async def _pump() -> None:
            try:
                while True:
                    reply = await websocket.receive_json()
                    control = reply.get("action")
                    if control == "approval":
                        hub.approve(task_id, bool(reply.get("approved")), str(reply.get("id") or ""))
                    elif control == "steer":
                        message = str(reply.get("message") or "").strip()
                        if not message:
                            await websocket.send_json(
                                {"type": "error", "message": "steer 内容不能为空"}
                            )
                        elif len(message) > MAX_STEER_LENGTH:
                            await websocket.send_json({
                                "type": "error",
                                "message": f"steer 过长(最大 {MAX_STEER_LENGTH} 字符)",
                            })
                        elif hub.steer(task_id, message):
                            await websocket.send_json({"type": "steer_ok"})
                    elif control == "stop":
                        hub.stop(task_id)
            except Exception:
                return

        pump = asyncio.create_task(_pump())
        while True:
            waiter = asyncio.create_task(event_queue.get())
            done, _ = await asyncio.wait(
                {waiter, pump}, return_when=asyncio.FIRST_COMPLETED,
            )
            if pump in done and waiter not in done:
                waiter.cancel()
                break
            frame = waiter.result()
            await websocket.send_json(frame)
            if frame.get("type") == "done":
                break
    except WebSocketDisconnect:
        # Real app sockets are observers; legacy bare-app embedders retain the
        # historical ownership semantics for backwards compatibility.
        if legacy_mode and task_id:
            hub.stop(task_id)
    except Exception as exc:
        try:
            await websocket.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass  # 尽力而为：socket 已坏时错误帧发不出去，不掩盖原始异常
    finally:
        legacy_task = None
        if legacy_mode and task_id:
            hub.stop(task_id)
            legacy_handle = hub.live_task(task_id)
            legacy_task = legacy_handle.task if legacy_handle is not None else None
        if event_queue is not None and task_id:
            hub.unsubscribe(task_id, event_queue)
        if pump is not None:
            pump.cancel()
            await asyncio.gather(pump, return_exceptions=True)
        if legacy_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(legacy_task), timeout=2.0)
            except (TimeoutError, asyncio.CancelledError):
                legacy_task.cancel()
