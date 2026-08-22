"""Small built-in guard hooks (borrowed from dsh guard/ family).

Guards are ordinary PRE_TOOL_USE handlers; the kernel mounts them by default
so runaway behaviour is stopped without any host configuration.
"""

from __future__ import annotations

import hashlib
import json
import os

from .events import AgentEvent, HookVerdict


def _canonical_key(tool_name: str, arguments: dict) -> str:
    try:
        payload = json.dumps(arguments, sort_keys=True, ensure_ascii=False,
                             default=str)
    except (TypeError, ValueError):
        payload = repr(arguments)
    return hashlib.sha256(f"{tool_name}\n{payload}".encode()).hexdigest()


class RepeatToolCallGuard:
    """Deny the Nth *consecutive identical* tool call (dsh repeat-tool-reminder).

    "Identical" means same tool name + same canonical arguments. Any different
    call resets the counter — varying the approach is all we ask for.
    """

    def __init__(self, limit: int = 3) -> None:
        self.limit = max(int(limit), 1)
        self._last_key: str | None = None
        self._count = 0

    def reset(self) -> None:
        self._last_key = None
        self._count = 0

    async def __call__(self, event: AgentEvent) -> HookVerdict | None:
        key = _canonical_key(event.tool_name, event.payload.get("arguments", {}))
        if key == self._last_key:
            self._count += 1
        else:
            self._last_key = key
            self._count = 1

        if self._count >= self.limit:
            n, limit = self._count, self.limit
            # Allow every 4th identical call through so a genuinely-idempotent
            # retry loop can make progress instead of dead-locking.
            if n % (limit + 1) == 0:
                return None
            return HookVerdict(
                allowed=False,
                reason=(
                    f"identical {event.tool_name} call repeated {n} times "
                    f"(guard limit {limit}). Inspect the previous result and "
                    "change your approach — vary the arguments or use a "
                    "different tool."
                ),
            )
        return None


def repeat_guard_from_env() -> RepeatToolCallGuard | None:
    """Build the guard from RA_REPEAT_TOOL_LIMIT (0 disables). Default 3."""
    raw = os.getenv("RA_REPEAT_TOOL_LIMIT", "3").strip()
    try:
        limit = int(raw)
    except ValueError:
        limit = 3
    if limit <= 0:
        return None
    return RepeatToolCallGuard(limit=limit)
