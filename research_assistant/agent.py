"""Custom agentic loop — replaces claude-agent-sdk dependency.

Implements a tool-use conversation loop that works with any LLM client
(Anthropic or OpenAI-compatible) and executes tools locally.

Kernel features (all optional, wired via :class:`RunConfig`):
  - hook bus: lifecycle events + PRE_TOOL_USE interception
  - budget guard: token/cost/turn/wall-clock hard caps
  - cancellation: cooperative cancel_event checked between turns and tools
  - activity heartbeat: silence-detection instead of total-duration timeout
  - context management: tool-result externalization + history compaction
"""

import asyncio
import inspect
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Awaitable

from .llm.base import LLMClient, LLMResponse, ToolCall, OnChunkCallback
from .llm.errors import LLMError, HeartbeatTimeoutError
from .kernel.events import AgentEvent, EventKind, HookBus
from .kernel.budget import BudgetGuard, BudgetExceededError
from .kernel.context import externalize_tool_result, maybe_compact
from .tools.registry import ToolRegistry
from .models import TokenUsage
from .constants import TASK_COMPLETE_MARKER, DEFAULT_MAX_CONTINUATIONS
from .retry import (
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
    #: "completed" | "cancelled" | "budget_exceeded" | "max_turns" | "max_continuations"
    stop_reason: str = "completed"


OnTextCallback = Callable[[str], Awaitable[None] | None]
OnToolCallback = Callable[[str, dict[str, Any], str], Awaitable[None] | None]
OnToolStartCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]
OnTurnStartCallback = Callable[[int, float, "TokenUsage"], Awaitable[None] | None]
OnSteerCallback = Callable[[str], Awaitable[None] | None]


@dataclass
class RunConfig:
    """Kernel configuration for a single agent run. All fields optional."""

    max_turns: int = 200
    auto_continue: bool = True
    max_continuations: int = DEFAULT_MAX_CONTINUATIONS
    temperature: float = 0.5
    max_tokens: int = 16384
    #: Hard caps; a fresh guard is built from env (RA_MAX_*) when None.
    budget: Optional[BudgetGuard] = None
    auto_budget: bool = True
    #: Lifecycle hooks; a private bus is created when None.
    hooks: Optional[HookBus] = None
    #: Cooperative cancellation; checked between turns and before each tool.
    cancel_event: Optional[asyncio.Event] = None
    #: Write oversized tool results to .ra/tool_outputs/ instead of the history.
    externalize_outputs: bool = True
    #: Summarize old history when nearing the model's context window.
    compaction: bool = True
    heartbeat_timeout: Optional[float] = None


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


def _supports_on_activity(client: LLMClient) -> bool:
    """True when client.chat accepts an on_activity kwarg.

    Kept dynamic so third-party/mock clients with the base signature keep
    working; the watchdog then degrades to a total-duration timeout.
    """
    try:
        return "on_activity" in inspect.signature(client.chat).parameters
    except (TypeError, ValueError):
        return False


class _ActivityWatchdog:
    """Silence detector for one LLM call.

    Any client ``on_activity`` beat resets the timer. Only when no beat
    arrives for *timeout* seconds is the request cancelled and
    :class:`HeartbeatTimeoutError` raised — a healthy long stream is never
    killed just because it is long.
    """

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self._activity = asyncio.Event()

    def beat(self) -> None:
        self._activity.set()

    async def call(self, coro_factory: Callable[[], Any]) -> LLMResponse:
        task = asyncio.create_task(coro_factory())
        try:
            while True:
                try:
                    return await asyncio.wait_for(asyncio.shield(task), timeout=self.timeout)
                except asyncio.TimeoutError:
                    if self._activity.is_set():
                        self._activity.clear()
                        continue
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
                    raise HeartbeatTimeoutError(self.timeout)
        finally:
            if not task.done():
                task.cancel()


async def run_agent(
    prompt: str,
    system_prompt: str,
    llm_client: LLMClient,
    tools: ToolRegistry,
    *,
    config: Optional[RunConfig] = None,
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

    Args:
        prompt: The user's initial request.
        system_prompt: System instructions for the LLM.
        llm_client: The LLM client to use.
        tools: Tool registry for executing tool calls.
        config: Kernel configuration. When given, supersedes the individual
            legacy keyword arguments below.
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
        AgentResult with collected output, metadata, and stop_reason.
    """
    if config is not None:
        cfg = config
    else:
        cfg = RunConfig(
            max_turns=max_turns,
            auto_continue=auto_continue,
            max_continuations=max_continuations,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    hooks = cfg.hooks if cfg.hooks is not None else HookBus()
    if cfg.budget is not None:
        budget = cfg.budget
    elif cfg.auto_budget:
        budget = BudgetGuard(model=getattr(llm_client, "model", ""))
    else:
        budget = None
    heartbeat_timeout = (
        cfg.heartbeat_timeout
        if cfg.heartbeat_timeout is not None
        else get_heartbeat_timeout()
    )

    start_time = time.time()
    messages: list[dict] = [{"role": "user", "content": prompt}]
    tool_schemas = tools.get_schemas()

    collected_text = ""
    files_written: list[str] = []
    total_usage = TokenUsage()
    n_llm_calls = 0
    continuation_count = 0
    max_retries = get_max_retries()
    base_delay = get_retry_base_delay()
    recent_text_responses: list[str] = []

    streaming = on_text is not None
    stop_reason = "completed"

    async def _emit(kind: EventKind, **kw: Any) -> Any:
        return await hooks.emit(AgentEvent(kind, **kw))

    await _emit(EventKind.RUN_START, payload={"prompt_chars": len(prompt)})

    # Per-run scratch space for externalized tool outputs.
    artifacts_dir: Optional[Path] = None
    if cfg.externalize_outputs:
        work_dir = getattr(tools, "work_dir", None)
        if work_dir:
            artifacts_dir = Path(work_dir) / ".ra" / "tool_outputs"

    use_activity = _supports_on_activity(llm_client)

    turn = -1
    for turn in range(cfg.max_turns):
        # --- cooperative cancellation -------------------------------------
        if cfg.cancel_event is not None and cfg.cancel_event.is_set():
            stop_reason = "cancelled"
            break

        injected = _drain_steer_queue(steer_queue, messages)
        for s in injected:
            await _maybe_await(on_steer_injected, s)
            await _emit(EventKind.STEER_INJECTED, payload={"message": s})

        await _maybe_await(
            on_turn_start, turn + 1, time.time() - start_time, total_usage,
        )
        await _emit(EventKind.TURN_START, turn=turn + 1)

        # --- budget gate ---------------------------------------------------
        if budget is not None:
            try:
                verdict = budget.check()
                for w in verdict.warnings:
                    await _emit(EventKind.BUDGET_WARNING, payload={"message": w})
            except BudgetExceededError as exc:
                await _emit(EventKind.BUDGET_EXCEEDED, payload={"report": exc.report})
                stop_reason = "budget_exceeded"
                collected_text += f"\n[BUDGET EXCEEDED] {exc.report}\n"
                break

        # --- LLM call ------------------------------------------------------
        watchdog = _ActivityWatchdog(heartbeat_timeout)

        async def _do_call() -> LLMResponse:
            kwargs: dict[str, Any] = {}
            if use_activity:
                kwargs["on_activity"] = watchdog.beat
            return await _llm_call_with_retry(
                llm_client, messages, system_prompt, tool_schemas,
                cfg.temperature, cfg.max_tokens, heartbeat_timeout,
                max_retries, base_delay,
                on_chunk=on_text if streaming else None,
                extra_kwargs=kwargs,
            )

        await _emit(EventKind.LLM_REQUEST, turn=turn + 1,
                    payload={"messages": len(messages)})
        try:
            response = await watchdog.call(_do_call)
        except BudgetExceededError:
            raise
        except Exception as exc:
            await _emit(EventKind.ERROR, payload={"error": str(exc)})
            raise

        _accumulate_usage(total_usage, response)
        n_llm_calls += 1
        if budget is not None:
            budget.record(response)
        await _emit(EventKind.LLM_RESPONSE, turn=turn + 1, payload={
            "stop_reason": response.stop_reason,
            "tool_calls": len(response.tool_calls),
            "input_tokens": response.usage.input_tokens,
        })

        # --- context compaction (after measuring real usage) ---------------
        if cfg.compaction:
            try:
                messages, compacted = await maybe_compact(
                    messages,
                    llm_client=llm_client,
                    model=getattr(llm_client, "model", ""),
                    last_input_tokens=response.usage.input_tokens,
                )
                if compacted:
                    await _emit(EventKind.CONTEXT_COMPACTION, turn=turn + 1)
            except Exception:
                pass  # compaction is best-effort; never kill a healthy run

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
                if cfg.cancel_event is not None and cfg.cancel_event.is_set():
                    stop_reason = "cancelled"
                    break

                verdict = await _emit(
                    EventKind.PRE_TOOL_USE,
                    turn=turn + 1,
                    tool_name=tc.name,
                    payload={"arguments": tc.arguments},
                )
                if not verdict.allowed:
                    result_text = f"[DENIED by policy] {verdict.reason}"
                else:
                    await _maybe_await(on_tool_start, tc.name, tc.arguments)
                    await _emit(EventKind.TOOL_START, turn=turn + 1,
                                tool_name=tc.name, payload={"arguments": tc.arguments})
                    result_text = await tools.execute(tc.name, tc.arguments)
                    if artifacts_dir is not None:
                        result_text = externalize_tool_result(
                            result_text, tc.name, turn + 1, artifacts_dir,
                        )
                    await _emit(EventKind.TOOL_END, turn=turn + 1,
                                tool_name=tc.name,
                                payload={"result_chars": len(result_text)})
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
            else:
                recent_text_responses.clear()
                continue
            # cancel hit mid-tool-batch
            break

        if response.stop_reason == "max_tokens":
            messages.append({"role": "assistant", "content": response.content})
            injected = _drain_steer_queue(steer_queue, messages)
            if not injected:
                messages.append({"role": "user", "content": "Continue from where you left off."})
            else:
                for s in injected:
                    await _maybe_await(on_steer_injected, s)
                    await _emit(EventKind.STEER_INJECTED, payload={"message": s})
            continuation_count += 1
            if continuation_count >= cfg.max_continuations:
                stop_reason = "max_continuations"
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

            if cfg.auto_continue and continuation_count < cfg.max_continuations:
                messages.append({"role": "assistant", "content": response.content})
                injected = _drain_steer_queue(steer_queue, messages)
                if not injected:
                    messages.append({"role": "user", "content": "Continue."})
                else:
                    for s in injected:
                        await _maybe_await(on_steer_injected, s)
                        await _emit(EventKind.STEER_INJECTED, payload={"message": s})
                continuation_count += 1
                continue
            else:
                break

        break
    else:
        stop_reason = "max_turns"

    await _emit(EventKind.RUN_END, payload={
        "stop_reason": stop_reason,
        "turns": n_llm_calls,
    })

    duration = time.time() - start_time
    return AgentResult(
        success=True,
        text_output=collected_text,
        files_written=files_written,
        duration_seconds=duration,
        token_usage=total_usage,
        turns=n_llm_calls,
        stop_reason=stop_reason,
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
    extra_kwargs: Optional[dict] = None,
) -> LLMResponse:
    """Call the LLM with retry on transient errors and a silence watchdog."""
    last_exc: BaseException | None = None
    extra_kwargs = extra_kwargs or {}

    for attempt in range(max_retries + 1):
        try:
            return await client.chat(
                messages,
                system=system,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                on_chunk=on_chunk,
                **extra_kwargs,
            )
        except Exception as exc:
            last_exc = exc

            # Structured errors carry their own verdict.
            if isinstance(exc, LLMError) and not exc.retryable:
                if isinstance(exc, ContextLimitError) or _is_context_limit(exc):
                    raise
                if isinstance(exc, ModelConfigError) or _is_model_error(exc):
                    raise
                raise

            if _is_context_limit(exc):
                raise ContextLimitError(exc) from exc
            if _is_model_error(exc):
                raise ModelConfigError(exc) from exc

            retryable = _is_retryable(exc) or isinstance(exc, HeartbeatTimeoutError)
            if not retryable or attempt >= max_retries:
                raise

            delay = base_delay * (2 ** attempt)
            if getattr(exc, "retry_after", None):
                delay = max(delay, float(exc.retry_after))
            # Add ±25 % jitter to prevent concurrent agents thundering-herd on retry.
            delay *= 0.75 + random.random() * 0.5
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
