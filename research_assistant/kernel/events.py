"""Agent event bus and hook protocol.

The HookBus lets hosts (CLI, web) and built-in policies observe and
influence the agent loop. A ``PRE_TOOL_USE`` handler may return a
``HookVerdict(allowed=False, reason=...)`` to block a tool call; the loop
then feeds ``[DENIED by policy] <reason>`` back to the model as the tool
result instead of executing it.

Example::

    bus = HookBus()

    async def no_rm_rf(event: AgentEvent) -> HookVerdict:
        cmd = event.payload.get("arguments", {}).get("command", "")
        if "rm -rf" in cmd:
            return HookVerdict(allowed=False, reason="destructive command")
        return None

    bus.on(EventKind.PRE_TOOL_USE, no_rm_rf)
"""

from __future__ import annotations

import enum
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class EventKind(str, enum.Enum):
    """Lifecycle events emitted by the agent loop."""

    RUN_START = "run_start"
    TURN_START = "turn_start"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    PRE_TOOL_USE = "pre_tool_use"
    TOOL_START = "tool_start"
    TOOL_END = "tool_end"
    STEER_INJECTED = "steer_injected"
    CONTEXT_COMPACTION = "context_compaction"
    BUDGET_WARNING = "budget_warning"
    BUDGET_EXCEEDED = "budget_exceeded"
    ERROR = "error"
    RUN_END = "run_end"


@dataclass
class AgentEvent:
    """A single observable occurrence inside the agent loop."""

    kind: EventKind
    turn: int = 0
    tool_name: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


@dataclass
class HookVerdict:
    """Decision returned by a PRE_TOOL_USE hook."""

    allowed: bool = True
    reason: str = ""


#: Handlers may be sync or async. Returning a HookVerdict with allowed=False
#: blocks the action; returning None means "no opinion".
HookHandler = Callable[[AgentEvent], "Awaitable[HookVerdict | None] | HookVerdict | None"]


class HookBus:
    """Registry and dispatcher for agent lifecycle hooks."""

    def __init__(self) -> None:
        self._handlers: dict[EventKind, list[HookHandler]] = {}

    def on(self, kind: EventKind, handler: HookHandler) -> None:
        """Register *handler* for *kind*. Multiple handlers run in registration order."""
        self._handlers.setdefault(kind, []).append(handler)

    def off(self, kind: EventKind, handler: HookHandler) -> None:
        """Remove a previously registered handler (no-op if absent)."""
        try:
            self._handlers.get(kind, []).remove(handler)
        except ValueError:
            pass

    async def emit(self, event: AgentEvent) -> HookVerdict:
        """Dispatch *event* to all handlers of its kind.

        Returns the first denying verdict, or an allowing verdict when all
        handlers approve (or have no opinion). Handler exceptions are caught
        and treated as "no opinion" — hooks must never crash the loop.
        """
        for handler in self._handlers.get(event.kind, []):
            try:
                result = handler(event)
                if hasattr(result, "__await__"):
                    result = await result  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001 — hooks are untrusted
                import logging

                logging.getLogger(__name__).warning(
                    "hook %r failed on %s: %s", handler, event.kind.value, exc
                )
                continue
            if isinstance(result, HookVerdict) and not result.allowed:
                return result
        return HookVerdict()
