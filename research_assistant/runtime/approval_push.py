"""平台任务审批请求的持久化 + 广播（工程债：三处 _push_approval 收敛）。"""

from __future__ import annotations

import asyncio
from typing import Any

from ..kernel.approval import ToolApprovalRequest


def push_platform_approval(
    *,
    store: Any,
    hub: Any,
    handle: Any,
    project_id: str,
    task_metadata: dict[str, Any] | None,
    request: ToolApprovalRequest,
) -> None:
    """把一次工具审批请求落库并广播给任务订阅者。

    旧实现（ws.py / scheduler_dispatcher.py）各抄一份：置 ``handle`` 的
    ``approval_request_id``、写 agent_approvals 行、经 hub 发 approval_request
    帧。三份曾漂移（任务元数据字段名、project_id 来源）。本函数是唯一实现，
    两个宿主在 on_request 回调里各调一次。
    """
    handle.approval_request_id = request.request_id
    metadata = task_metadata or {}
    store.create_agent_approval(
        project_id=project_id, task_id=metadata.get("task_id"),
        thread_id=metadata.get("thread_id"), turn_id=metadata.get("turn_id"),
        agent_id=request.agent_id, role=request.agent_role,
        tool_name=request.tool_name, arguments=request.arguments,
        summary=request.summary(), approval_id=request.request_id,
    )
    asyncio.get_running_loop().create_task(hub.publish(handle.task_id, {
        "type": "approval_request", "id": request.request_id or handle.task_id,
        "tool": request.tool_name, "summary": request.summary(),
        "agent_id": getattr(request, "agent_id", ""),
        "role": getattr(request, "agent_role", ""),
    }))
