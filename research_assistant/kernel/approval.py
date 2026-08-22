"""Approval round-trip (borrowed from codex ExecApproval / dsh ctx.approval).

A PRE_TOOL_USE hook may return ``HookVerdict(ask=True)``; the loop then asks
the run's *approver* — a callable receiving a :class:`ToolApprovalRequest`
and returning an :class:`ApprovalDecision`. Missing approver, timeout, and
approver errors all resolve to **deny**.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolApprovalRequest:
    """One tool call awaiting a human/policy decision."""

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    turn: int = 0
    reason: str = ""                      # why the hook escalated to ask

    def summary(self, max_args_chars: int = 300) -> str:
        try:
            args_text = repr(self.arguments)
        except Exception:
            args_text = "<unprintable>"
        if len(args_text) > max_args_chars:
            args_text = args_text[:max_args_chars] + "…"
        text = f"{self.tool_name}({args_text})"
        if self.reason:
            text += f" — {self.reason}"
        return text


@dataclass
class ApprovalDecision:
    approved: bool
    note: str = ""


Approver = Callable[[ToolApprovalRequest], "Awaitable[ApprovalDecision] | ApprovalDecision"]


async def resolve_approval(
    approver: Approver | None,
    request: ToolApprovalRequest,
    timeout: float = 120.0,
) -> tuple[bool, str]:
    """Run *approver* for *request*; any failure mode resolves to deny."""
    if approver is None:
        return False, "approval required but no approver is attached"

    try:
        outcome = approver(request)
        if inspect.isawaitable(outcome):
            outcome = await asyncio.wait_for(outcome, timeout=timeout)
    except asyncio.TimeoutError:
        return False, f"approval timed out after {timeout:.0f}s"
    except Exception as exc:  # noqa: BLE001 — approvers are untrusted
        return False, f"approver error: {exc}"

    approved = bool(getattr(outcome, "approved", outcome))
    note = getattr(outcome, "note", "") or ("approved" if approved else "rejected")
    return approved, note


class QueueApprover:
    """Approver that posts the request and waits for an answer on a queue.

    Shared by the CLI (answers typed into the steer channel) and the web UI
    (answers arriving as WebSocket ``{"action": "approval"}`` messages).

    Args:
        queue: asyncio.Queue yielding answer strings; truthy values in
            {"y", "yes", "1", "true"} approve, everything else rejects.
        timeout: seconds to wait before auto-denying.
        on_request: optional sync callback invoked with the request when it
            is posted (used by the web host to push it to the browser).
        printer: optional sync callback for local display of the request.
    """

    _YES = {"y", "yes", "1", "true"}

    def __init__(
        self,
        queue: asyncio.Queue,
        timeout: float = 120.0,
        on_request: Callable[[ToolApprovalRequest], None] | None = None,
        printer: Callable[[str], None] | None = None,
    ) -> None:
        self.queue = queue
        self.timeout = timeout
        self._on_request = on_request
        self._printer = printer

    async def __call__(self, request: ToolApprovalRequest) -> ApprovalDecision:
        if self._printer is not None:
            self._printer(f"审批请求: {request.summary()}")
        if self._on_request is not None:
            self._on_request(request)

        try:
            line = await asyncio.wait_for(self.queue.get(), timeout=self.timeout)
        except asyncio.TimeoutError:
            return ApprovalDecision(False, f"no answer within {self.timeout:.0f}s")

        answer = str(line).strip().lower()
        if answer in self._YES:
            return ApprovalDecision(True)
        return ApprovalDecision(False, f'rejected by answer "{line}"')
