"""Custom agentic loop — replaces claude-agent-sdk dependency.

Implements a tool-use conversation loop that works with any LLM client
(Anthropic or OpenAI-compatible) and executes tools locally.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Awaitable

from .llm.base import LLMClient, LLMResponse, ToolCall, OnChunkCallback
from .tools.registry import ToolRegistry
from .models import TokenUsage
from .constants import TASK_COMPLETE_MARKER, DEFAULT_MAX_CONTINUATIONS
from .retry import (
    HeartbeatTimeoutError,
    ContextLimitError,
    ModelConfigError,
    _is_context_limit,
    _is_model_error,
    _is_retryable,
    get_max_retries,
    get_retry_base_delay,
    get_heartbeat_timeout,
)


@dataclass
class AgentResult:
    """Final result from an agent run."""
    success: bool = True
    text_output: str = ""
    files_written: list[str] = field(default_factory=list)
    error: Optional[str] = None
    duration_seconds: float = 0.0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    turns: int = 0


OnTextCallback = Callable[[str], Awaitable[None] | None]
OnToolCallback = Callable[[str, dict[str, Any], str], Awaitable[None] | None]
OnToolStartCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]
OnTurnStartCallback = Callable[[int, float, "TokenUsage"], Awaitable[None] | None]
OnSteerCallback = Callable[[str], Awaitable[None] | None]


def _is_completion_loop(recent_texts: list[str]) -> bool:
    """Detect if the LLM is stuck repeating similar completion messages.

    Compares the last two text-only responses (no tool calls) using
    word-level Jaccard similarity.  A score above 0.6 means the model
    is almost certainly saying the same thing again.
    """
    if len(recent_texts) < 2:
        return False
    a, b = recent_texts[-2], recent_texts[-1]
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return False
    jaccard = len(words_a & words_b) / len(words_a | words_b)
    return jaccard > 0.6


async def _maybe_await(fn: Optional[Callable[..., Any]], *args: Any) -> None:
    if fn is None:
        return
    result = fn(*args)
    if asyncio.iscoroutine(result):
        await result


async def _llm_call_with_timeout(
    client: LLMClient,
    messages: list[dict],
    system: str,
    tools: list[dict] | None,
    temperature: float,
    max_tokens: int,
    heartbeat_timeout: float,
    on_chunk: Optional[OnChunkCallback] = None,
) -> LLMResponse:
    """Call the LLM with a heartbeat timeout."""
    coro = client.chat(
        messages,
        system=system,
        tools=tools,
        temperature=temperature,
        max_tokens=max_tokens,
        on_chunk=on_chunk,
    )
    try:
        return await asyncio.wait_for(coro, timeout=heartbeat_timeout)
    except asyncio.TimeoutError:
        raise HeartbeatTimeoutError(heartbeat_timeout)


async def run_agent(
    prompt: str,
    system_prompt: str,
    llm_client: LLMClient,
    tools: ToolRegistry,
    *,
    max_turns: int = 200,
    auto_continue: bool = True,
    max_continuations: int = DEFAULT_MAX_CONTINUATIONS,
    temperature: float = 0.5,
    max_tokens: int = 16384,
    on_text: Optional[OnTextCallback] = None,
    on_tool_use: Optional[OnToolCallback] = None,
    on_tool_start: Optional[OnToolStartCallback] = None,
    on_turn_start: Optional[OnTurnStartCallback] = None,
    steer_queue: Optional[asyncio.Queue] = None,
    on_steer_injected: Optional[OnSteerCallback] = None,
) -> AgentResult:
    """Run an agentic conversation loop to completion.

    The agent sends messages to the LLM, executes tool calls locally,
    feeds results back, and continues until the LLM stops or limits
    are reached.

    Args:
        prompt: The user's initial request.
        system_prompt: System instructions for the LLM.
        llm_client: The LLM client to use.
        tools: Tool registry for executing tool calls.
        max_turns: Maximum number of LLM call rounds.
        auto_continue: If True, send "Continue." when the LLM stops naturally.
        max_continuations: Max auto-continue attempts.
        temperature: LLM temperature.
        max_tokens: Max tokens per LLM response.
        on_text: Callback for streaming text output.
        on_tool_use: Callback(tool_name, arguments, result) after tool execution.
        on_tool_start: Callback(tool_name, arguments) before tool execution.
        on_turn_start: Callback(turn, elapsed, usage) at start of each LLM call.
        steer_queue: asyncio.Queue for mid-execution user messages.
        on_steer_injected: Callback(message) when a steer is consumed.

    Returns:
        AgentResult with collected output and metadata.
    """
    start_time = time.time()
    messages: list[dict] = [{"role": "user", "content": prompt}]
    tool_schemas = tools.get_schemas()

    collected_text = ""
    files_written: list[str] = []
    total_usage = TokenUsage()
    continuation_count = 0
    max_retries = get_max_retries()
    base_delay = get_retry_base_delay()
    heartbeat_timeout = get_heartbeat_timeout()
    recent_text_responses: list[str] = []

    streaming = on_text is not None

    for turn in range(max_turns):
        injected = _drain_steer_queue(steer_queue, messages)
        for s in injected:
            await _maybe_await(on_steer_injected, s)

        await _maybe_await(
            on_turn_start, turn + 1, time.time() - start_time, total_usage,
        )

        response = await _llm_call_with_retry(
            llm_client, messages, system_prompt, tool_schemas,
            temperature, max_tokens, heartbeat_timeout, max_retries, base_delay,
            on_chunk=on_text if streaming else None,
        )

        _accumulate_usage(total_usage, response)

        if response.content:
            collected_text += response.content
            if not streaming:
                await _maybe_await(on_text, response.content)

        if response.tool_calls:
            assistant_msg: dict[str, Any] = {"role": "assistant", "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in response.tool_calls
            ]}
            if response.content:
                assistant_msg["content"] = response.content
            messages.append(assistant_msg)

            for tc in response.tool_calls:
                await _maybe_await(on_tool_start, tc.name, tc.arguments)
                result_text = await tools.execute(tc.name, tc.arguments)
                await _maybe_await(on_tool_use, tc.name, tc.arguments, result_text)

                if tc.name in ("write_file",):
                    fp = tc.arguments.get("file_path", "")
                    if fp:
                        files_written.append(fp)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                })
            recent_text_responses.clear()
            continue

        if response.stop_reason == "max_tokens":
            messages.append({"role": "assistant", "content": response.content})
            injected = _drain_steer_queue(steer_queue, messages)
            if not injected:
                messages.append({"role": "user", "content": "Continue from where you left off."})
            else:
                for s in injected:
                    await _maybe_await(on_steer_injected, s)
            continuation_count += 1
            if continuation_count >= max_continuations:
                break
            continue

        if response.stop_reason == "end_turn":
            if TASK_COMPLETE_MARKER in (response.content or ""):
                break

            if response.content and not response.tool_calls:
                recent_text_responses.append(response.content.strip())
                if len(recent_text_responses) > 5:
                    recent_text_responses.pop(0)

            if _is_completion_loop(recent_text_responses):
                break

            if auto_continue and continuation_count < max_continuations:
                messages.append({"role": "assistant", "content": response.content})
                injected = _drain_steer_queue(steer_queue, messages)
                if not injected:
                    messages.append({"role": "user", "content": "Continue."})
                else:
                    for s in injected:
                        await _maybe_await(on_steer_injected, s)
                continuation_count += 1
                continue
            else:
                break

        break

    duration = time.time() - start_time
    return AgentResult(
        success=True,
        text_output=collected_text,
        files_written=files_written,
        duration_seconds=duration,
        token_usage=total_usage,
        turns=turn + 1,
    )


async def _llm_call_with_retry(
    client: LLMClient,
    messages: list[dict],
    system: str,
    tools: list[dict] | None,
    temperature: float,
    max_tokens: int,
    heartbeat_timeout: float,
    max_retries: int,
    base_delay: float,
    on_chunk: Optional[OnChunkCallback] = None,
) -> LLMResponse:
    """Call the LLM with retry on transient errors and heartbeat timeout."""
    last_exc: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            return await _llm_call_with_timeout(
                client, messages, system, tools,
                temperature, max_tokens, heartbeat_timeout,
                on_chunk=on_chunk,
            )
        except BaseException as exc:
            last_exc = exc

            if _is_context_limit(exc):
                raise ContextLimitError(exc) from exc
            if _is_model_error(exc):
                raise ModelConfigError(exc) from exc

            retryable = _is_retryable(exc) or isinstance(exc, HeartbeatTimeoutError)
            if not retryable or attempt >= max_retries:
                raise

            delay = base_delay * (2 ** attempt)
            await asyncio.sleep(delay)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Unexpected: retry loop exited without result or exception")


def _accumulate_usage(total: TokenUsage, response: LLMResponse) -> None:
    """Add response token usage to running total."""
    total.input_tokens += response.usage.input_tokens
    total.output_tokens += response.usage.output_tokens
    total.cache_creation_input_tokens += response.usage.cache_creation_input_tokens
    total.cache_read_input_tokens += response.usage.cache_read_input_tokens


def _drain_steer_queue(
    queue: Optional[asyncio.Queue],
    messages: list[dict],
) -> list[str]:
    """Drain pending steer messages and inject as a single user message.

    Returns the list of raw steer strings that were injected.
    """
    if queue is None:
        return []

    steers: list[str] = []
    while True:
        try:
            steers.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break

    if steers:
        combined = "\n".join(f"[USER STEER]: {s}" for s in steers)
        messages.append({"role": "user", "content": combined})

    return steers
