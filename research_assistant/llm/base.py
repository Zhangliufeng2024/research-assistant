"""Abstract base classes and data models for LLM clients."""

import asyncio
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

DEFAULT_LLM_REQUEST_INTERVAL = 2.0

_last_llm_request_time: float = 0.0


async def _throttle_llm() -> None:
    """Enforce minimum interval between LLM API requests."""
    global _last_llm_request_time
    interval = float(os.getenv("LLM_REQUEST_INTERVAL", DEFAULT_LLM_REQUEST_INTERVAL))
    if interval <= 0:
        return
    now = time.monotonic()
    elapsed = now - _last_llm_request_time
    if elapsed < interval and _last_llm_request_time > 0:
        await asyncio.sleep(interval - elapsed)
    _last_llm_request_time = time.monotonic()


@dataclass
class ToolCall:
    """A tool invocation from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class TokenUsage:
    """Token consumption for a single LLM call."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


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
    ) -> LLMResponse:
        """Send a chat request and return the full response."""

    @abstractmethod
    async def close(self) -> None:
        """Release underlying HTTP resources."""
