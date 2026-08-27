"""Reusable Agent supervisor primitives.

The specialized paper pipeline remains authoritative for manuscript quality,
while this layer provides a common execution contract for generic workflows:
bounded parallelism, lifecycle events, failure isolation and cooperative
cancellation.  A host can persist emitted events as Thread Agent Items.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentTaskSpec:
    id: str
    role: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    metadata: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None


@dataclass
class AgentTaskResult:
    task_id: str
    role: str
    status: str
    value: Any = None
    error: str = ""
    seconds: float = 0.0


class AgentSupervisor:
    """Run independent Agent tasks with bounded concurrency and observability."""

    def __init__(self, *, max_concurrency: int = 4,
                 event_sink: Callable[[dict[str, Any]], Any] | None = None) -> None:
        self.max_concurrency = max(1, min(int(max_concurrency), 32))
        self.event_sink = event_sink

    async def _emit(self, event: dict[str, Any]) -> None:
        if self.event_sink is None:
            return
        result = self.event_sink(event)
        if isinstance(result, Awaitable):
            await result

    async def run_ready(
        self,
        specs: Iterable[AgentTaskSpec],
        execute: Callable[[AgentTaskSpec], Awaitable[Any]],
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> list[AgentTaskResult]:
        specs = list(specs)
        if not specs:
            return []
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def one(spec: AgentTaskSpec) -> AgentTaskResult:
            if cancel_event is not None and cancel_event.is_set():
                return AgentTaskResult(spec.id, spec.role, "cancelled")
            started = time.monotonic()
            await self._emit({"type": "agent_status", "agent_id": spec.id, "role": spec.role, "status": "queued"})
            async with semaphore:
                if cancel_event is not None and cancel_event.is_set():
                    return AgentTaskResult(spec.id, spec.role, "cancelled")
                await self._emit({"type": "agent_status", "agent_id": spec.id, "role": spec.role, "status": "running"})
                try:
                    operation = execute(spec)
                    if spec.timeout_seconds is not None and spec.timeout_seconds > 0:
                        value = await asyncio.wait_for(operation, timeout=spec.timeout_seconds)
                    else:
                        value = await operation
                except asyncio.TimeoutError:
                    elapsed = time.monotonic() - started
                    message = f"Agent 超时（>{spec.timeout_seconds:g}s）"
                    await self._emit({"type": "agent_status", "agent_id": spec.id, "role": spec.role, "status": "failed", "error": message, "timeout_seconds": spec.timeout_seconds})
                    return AgentTaskResult(spec.id, spec.role, "failed", error=message, seconds=elapsed)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - preserve per-Agent failure
                    elapsed = time.monotonic() - started
                    await self._emit({"type": "agent_status", "agent_id": spec.id, "role": spec.role, "status": "failed", "error": str(exc)})
                    return AgentTaskResult(spec.id, spec.role, "failed", error=str(exc), seconds=elapsed)
                elapsed = time.monotonic() - started
                await self._emit({"type": "agent_status", "agent_id": spec.id, "role": spec.role, "status": "complete", "seconds": round(elapsed, 3)})
                return AgentTaskResult(spec.id, spec.role, "complete", value=value, seconds=elapsed)

        return await asyncio.gather(*(one(spec) for spec in specs))
