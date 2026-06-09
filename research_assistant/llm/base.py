"""Abstract base classes and data models for LLM clients."""

import asyncio
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..models import TokenUsage
from ..constants import DEFAULT_LLM_REQUEST_INTERVAL

_last_llm_request_time: float = 0.0


async def _throttle_llm() -> None:
    """Enforce minimum interval between LLM API requests."""
    global _last_llm_request_time
    raw = os.getenv("LLM_REQUEST_INTERVAL")
    try:
        interval = float(raw) if raw is not None else DEFAULT_LLM_REQUEST_INTERVAL
    except (ValueError, TypeError):
        interval = DEFAULT_LLM_REQUEST_INTERVAL
    if interval <= 0:
        return
    now = time.monotonic()
    elapsed = now - _last_llm_request_time
    if elapsed < interval and _last_llm_request_time > 0:
        await asyncio.sleep(interval - elapsed)
    _last_llm_request_time = time.monotonic()


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
    """

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        *,
        system: str = "",
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 16384,
        on_chunk: Optional[OnChunkCallback] = None,
    ) -> LLMResponse:
        """Send a chat request and return the full response.

        When *on_chunk* is provided, the implementation should use the
        provider's streaming API and call ``on_chunk(text_delta)`` for
        each text fragment as it arrives.  The returned ``LLMResponse``
        still contains the full accumulated content.
        """

    @abstractmethod
    async def close(self) -> None:
        """Release underlying HTTP resources."""
