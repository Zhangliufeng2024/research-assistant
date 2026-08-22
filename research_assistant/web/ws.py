"""WebSocket handler for real-time document generation."""

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..api import generate_paper
from ..core import safe_resolve
from ..kernel.budget import BudgetLimits

router = APIRouter()

MAX_QUERY_LENGTH = 10_000
MAX_STEER_LENGTH = 2_000


def _validate_resume_dir(output_folder: object, name: str) -> tuple[Path | None, str]:
    """Validate a ``resume_run`` directory name; returns ``(run_dir, error)``.

    The name must not contain path separators, must resolve inside
    *output_folder*, exist, and contain a ``run.json``.
    """
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
    """Tolerantly read the original query from a run's run.json."""
    try:
        state = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        state = {}
    if not isinstance(state, dict):
        return ""
    return str(state.get("query") or "").strip()


@router.websocket("/ws/generate")
async def ws_generate(websocket: WebSocket):
    await websocket.accept()

    cancel_event = asyncio.Event()  # 提前定义：任何阶段的断连兜底都要用到
    try:
        msg = await websocket.receive_json()

        if msg.get("action") != "start":
            await websocket.send_json({"type": "error", "message": "Expected action: start"})
            await websocket.close()
            return

        # B3 断点续跑：resume_run 指向既有 paper 目录时，query 从 run.json 恢复，
        # 生成强制走多代理（pipeline 靠 ArtifactStore 自动跳过已完成阶段）。
        resume_name = str(msg.get("resume_run") or "").strip()
        output_dir_arg: str | None = None
        multi_agent = bool(msg.get("multi_agent", False))
        query = ""

        if resume_name:
            run_dir, err = _validate_resume_dir(
                getattr(websocket.app.state, "output_folder", None), resume_name,
            )
            if err:
                await websocket.send_json({"type": "error", "message": err})
                await websocket.close()
                return
            resumed_query = _read_resume_query(run_dir)
            if not resumed_query:
                await websocket.send_json({
                    "type": "error",
                    "message": f"无法续跑: {resume_name} 的 run.json 缺少 query",
                })
                await websocket.close()
                return
            query = resumed_query
            output_dir_arg = str(run_dir)
            multi_agent = True
        else:
            query = msg.get("query", "").strip()
            if not query:
                await websocket.send_json({"type": "error", "message": "query 不能为空"})
                await websocket.close()
                return

            if len(query) > MAX_QUERY_LENGTH:
                await websocket.send_json(
                    {"type": "error", "message": f"query 过长（最大 {MAX_QUERY_LENGTH} 字符）"})
                await websocket.close()
                return

        task_id = str(uuid.uuid4())[:8]
        cwd = websocket.app.state.cwd

        cancel_event = asyncio.Event()
        approval_queue: asyncio.Queue = asyncio.Queue()
        steer_queue: asyncio.Queue = asyncio.Queue()
        budget_limits = BudgetLimits(
            max_cost_usd=msg.get("max_cost_usd") or None,
            max_wall_seconds=msg.get("max_wall_seconds") or None,
        )

        from ..kernel.approval import QueueApprover

        def _push_approval(request) -> None:
            asyncio.get_running_loop().create_task(websocket.send_json({
                "type": "approval_request",
                "id": task_id,
                "tool": request.tool_name,
                "summary": request.summary(),
            }))

        approver = QueueApprover(approval_queue, timeout=120.0,
                                 on_request=_push_approval)

        websocket.app.state.active_tasks[task_id] = {
            "status": "running",
            "query": query[:100],
            "cancel_event": cancel_event,
            "approvals": approval_queue,
            "steers": steer_queue,
        }

        await websocket.send_json({
            "type": "connected", "task_id": task_id,
            "resumed": resume_name or None,
        })

        async def _pump() -> None:
            """Route client messages (approvals / steers) while generation runs."""
            try:
                while True:
                    reply = await websocket.receive_json()
                    action = reply.get("action")
                    if action == "approval":
                        await approval_queue.put(reply.get("approved"))
                    elif action == "steer":
                        message = str(reply.get("message") or "").strip()
                        if not message:
                            await websocket.send_json(
                                {"type": "error", "message": "steer 内容不能为空"})
                        elif len(message) > MAX_STEER_LENGTH:
                            await websocket.send_json(
                                {"type": "error",
                                 "message": f"steer 过长(最大 {MAX_STEER_LENGTH} 字符)"})
                        else:
                            steer_queue.put_nowait(message)
                            await websocket.send_json({"type": "steer_ok"})
            except Exception:
                cancel_event.set()
                approval_queue.put_nowait(None)  # unblock a pending approver

        pump = asyncio.create_task(_pump())
        try:
            async for update in generate_paper(
                query=query,
                cwd=str(cwd),
                model=msg.get("model"),
                provider=msg.get("provider"),
                multi_agent=multi_agent,
                data_files=msg.get("data_files"),
                cancel_event=cancel_event,
                budget_limits=budget_limits,
                approver=approver,
                track_token_usage=True,
                steer_queue=steer_queue,
                output_dir=output_dir_arg,
            ):
                if cancel_event.is_set():
                    try:
                        await websocket.send_json({
                            "type": "progress", "stage": "cancelled",
                            "message": "任务已停止",
                        })
                    except Exception:
                        pass
                    break
                try:
                    await websocket.send_json(update)
                except Exception:
                    break
        finally:
            pump.cancel()
            websocket.app.state.active_tasks.pop(task_id, None)

        await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        # Client gone — make sure the underlying generation stops burning tokens.
        cancel_event.set()
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
