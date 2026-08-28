"""Abstract base classes and data models for LLM clients."""

import asyncio
import os
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..constants import DEFAULT_LLM_REQUEST_INTERVAL
from ..models import TokenUsage

OnChunkCallback = Callable[[str], Awaitable[None] | None]


@dataclass
class ToolCall:
    """A tool invocation from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Unified response from an LLM call."""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: TokenUsage = field(default_factory=TokenUsage)


class LLMClient(ABC):
    """Abstract LLM client interface.

    Subclasses implement the wire protocol for a specific API format
    (Anthropic Messages API, OpenAI Chat Completions, etc.) and convert
    responses into the unified ``LLMResponse`` model.

    Rate limiting is handled per-instance via ``_throttle()``, using an
    ``asyncio.Lock`` so concurrent calls from the same client are serialised
    without cross-client interference.
    """

    def __init__(self) -> None:
        self._last_request_time: float = 0.0
        self._throttle_lock: asyncio.Lock = asyncio.Lock()

    async def _throttle(self) -> None:
        """Enforce minimum interval between LLM API requests (per-instance)."""
        async with self._throttle_lock:
            raw = os.getenv("LLM_REQUEST_INTERVAL")
            try:
                interval = float(raw) if raw is not None else DEFAULT_LLM_REQUEST_INTERVAL
            except (ValueError, TypeError):
                interval = DEFAULT_LLM_REQUEST_INTERVAL
            if interval <= 0:
                return
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < interval and self._last_request_time > 0:
                await asyncio.sleep(interval - elapsed)
            self._last_request_time = time.monotonic()

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        *,
        system: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        on_chunk: OnChunkCallback | None = None,
        on_activity: Any | None = None,
        on_thought: OnChunkCallback | None = None,
    ) -> LLMResponse:
        """Send a chat request and return the full response.

        When *on_chunk* is provided, the implementation should use the
        provider's streaming API and call ``on_chunk(text_delta)`` for
        each text fragment as it arrives.  The returned ``LLMResponse``
        still contains the full accumulated content.

        When *on_activity* is provided, the implementation should call it
        (no arguments) on every protocol-level sign of life (each SSE line)
        so callers can distinguish "slow but alive" from "stuck".

        When *on_thought* is provided (R17), reasoning/thinking deltas are
        delivered through it on a separate channel — they must NEVER be
        folded into the accumulated ``content`` (thought 不是正文).
        Implementations without a reasoning channel simply never call it.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release underlying HTTP resources."""
