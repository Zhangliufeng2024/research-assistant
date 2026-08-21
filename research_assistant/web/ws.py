"""WebSocket handler for real-time document generation."""

import asyncio
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..api import generate_paper
from ..kernel.budget import BudgetLimits

router = APIRouter()

MAX_QUERY_LENGTH = 10_000


@router.websocket("/ws/generate")
async def ws_generate(websocket: WebSocket):
    await websocket.accept()

    try:
        msg = await websocket.receive_json()

        if msg.get("action") != "start":
            await websocket.send_json({"type": "error", "message": "Expected action: start"})
            await websocket.close()
            return

        query = msg.get("query", "").strip()
        if not query:
            await websocket.send_json({"type": "error", "message": "query 不能为空"})
            await websocket.close()
            return

        if len(query) > MAX_QUERY_LENGTH:
            await websocket.send_json({"type": "error", "message": f"query 过长（最大 {MAX_QUERY_LENGTH} 字符）"})
            await websocket.close()
            return

        task_id = str(uuid.uuid4())[:8]
        cwd = websocket.app.state.cwd

        cancel_event = asyncio.Event()
        budget_limits = BudgetLimits(
            max_cost_usd=msg.get("max_cost_usd") or None,
            max_wall_seconds=msg.get("max_wall_seconds") or None,
        )
        websocket.app.state.active_tasks[task_id] = {
            "status": "running",
            "query": query[:100],
            "cancel_event": cancel_event,
        }

        await websocket.send_json({"type": "connected", "task_id": task_id})

        try:
            async for update in generate_paper(
                query=query,
                cwd=str(cwd),
                model=msg.get("model"),
                provider=msg.get("provider"),
                multi_agent=msg.get("multi_agent", False),
                data_files=msg.get("data_files"),
                cancel_event=cancel_event,
                budget_limits=budget_limits,
                track_token_usage=True,
            ):
                if cancel_event.is_set():
                    await websocket.send_json({
                        "type": "progress", "stage": "cancelled",
                        "message": "任务已停止",
                    })
                    break
                await websocket.send_json(update)
        finally:
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
