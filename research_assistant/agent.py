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
import json
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import DEFAULT_MAX_CONTINUATIONS, TASK_COMPLETE_MARKER
from .kernel.approval import ToolApprovalRequest, resolve_approval
from .kernel.budget import BudgetExceededError, BudgetGuard
from .kernel.context import externalize_tool_result, maybe_compact
from .kernel.events import AgentEvent, EventKind, HookBus
from .kernel.guards import repeat_guard_from_env
from .llm.base import LLMClient, LLMResponse, OnChunkCallback
from .llm.errors import HeartbeatTimeoutError, LLMError
from .models import TokenUsage
from .retry import (
    ContextLimitError,
    ModelConfigError,
    _is_context_limit,
    _is_model_error,
    _is_retryable,
    get_heartbeat_timeout,
    get_max_retries,
    get_retry_base_delay,
)
from .tools.registry import ToolRegistry


@dataclass
class AgentResult:
    """Final result from an agent run."""
    success: bool = True
    text_output: str = ""
    files_written: list[str] = field(default_factory=list)
    error: str | None = None
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
    budget: BudgetGuard | None = None
    auto_budget: bool = True
    #: Lifecycle hooks; a private bus is created when None.
    hooks: HookBus | None = None
    #: Cooperative cancellation; checked between turns and before each tool.
    cancel_event: asyncio.Event | None = None
    #: Optional permission policy mounted as a PRE_TOOL_USE hook. When None,
    #: the default is built from RA_PERMISSION_MODE (deny_dangerous | off).
    permission_policy: Any | None = None
    #: Approver for hooks that return HookVerdict(ask=True). Missing approver,
    #: timeout (approval_timeout), or approver error all resolve to deny.
    approver: Any | None = None
    approval_timeout: float = 120.0
    #: Session-log port: object with ``.log(kind, data)``. Mirrors every
    #: model-visible mutation (see docs/protocol.md).
    session_log: Any | None = None
    #: Repeat-call guard: None=from env (default on, limit 3), False=off,
    #: or a guard instance with ``__call__``.
    repeat_guard: Any | None = None
    #: Write oversized tool results to .ra/tool_outputs/ instead of the history.
    externalize_outputs: bool = True
    #: Summarize old history when nearing the model's context window.
    compaction: bool = True
    heartbeat_timeout: float | None = None


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


async def _maybe_await(fn: Callable[..., Any] | None, *args: Any) -> None:
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
                    raise HeartbeatTimeoutError(self.timeout) from None
        finally:
            if not task.done():
                task.cancel()


async def run_agent(
    prompt: str,
    system_prompt: str,
    llm_client: LLMClient,
    tools: ToolRegistry,
    *,
    config: RunConfig | None = None,
    max_turns: int = 200,
    auto_continue: bool = True,
    max_continuations: int = DEFAULT_MAX_CONTINUATIONS,
    temperature: float = 0.5,
    max_tokens: int = 16384,
    on_text: OnTextCallback | None = None,
    on_tool_use: OnToolCallback | None = None,
    on_tool_start: OnToolStartCallback | None = None,
    on_turn_start: OnTurnStartCallback | None = None,
    steer_queue: asyncio.Queue | None = None,
    on_steer_injected: OnSteerCallback | None = None,
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

    # Mount the permission policy (default from env) unless explicitly off.
    if cfg.permission_policy is not None:
        hooks.on(EventKind.PRE_TOOL_USE, cfg.permission_policy.as_hook)
    else:
        from .tools.permissions import policy_from_env
        default_policy = policy_from_env()
        if default_policy is not None:
            hooks.on(EventKind.PRE_TOOL_USE, default_policy.as_hook)
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

    # --- session-log mirroring ("model-visible is logged") -----------------
    # Every mutation of `messages` goes through the helpers below, which keep
    # a length ledger; before each LLM request we assert the live list length
    # matches the ledger, so an unlogged mutation cannot slip through
    # unnoticed (soft warning — see docs/protocol.md for the contract).
    ledger = {"appended": 0, "deleted": 0}
    session_log = cfg.session_log

    def _slog(kind: str, **data: Any) -> None:
        if session_log is None:
            return
        try:
            session_log.log(kind, data)
        except Exception:
            pass  # telemetry must never break the run

    def _log_append(msg: dict) -> None:
        ledger["appended"] += 1
        seq = ledger["appended"] - ledger["deleted"] - 1
        content = msg.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False, default=str)
        _slog("msg_add", seq=seq, role=msg.get("role", "?"),
              content=str(content)[:20_000],
              tool_calls=bool(msg.get("tool_calls")))

    def _log_delete(n: int) -> None:
        ledger["deleted"] += n

    # Mount the repeat-call guard (env-tunable, on by default).
    if cfg.repeat_guard is not False:
        guard = (cfg.repeat_guard if callable(cfg.repeat_guard)
                 else repeat_guard_from_env())
        if guard is not None:
            hooks.on(EventKind.PRE_TOOL_USE, guard)

    await _emit(EventKind.RUN_START, payload={"prompt_chars": len(prompt)})
    _log_append({"role": "user", "content": prompt})

    # Per-run scratch space for externalized tool outputs.
    artifacts_dir: Path | None = None
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
        if injected:
            _log_append(messages[-1])
        for s in injected:
            await _maybe_await(on_steer_injected, s)
            await _emit(EventKind.STEER_INJECTED, payload={"message": s})
            _slog("steer", message=s[:2000])

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
        expected_len = ledger["appended"] - ledger["deleted"]
        if len(messages) != expected_len:
            await _emit(EventKind.INVARIANT_WARNING, payload={
                "expected": expected_len, "actual": len(messages),
            })
            _slog("invariant_warning", expected=expected_len, actual=len(messages))

        watchdog = _ActivityWatchdog(heartbeat_timeout)

        async def _do_call(watchdog=watchdog, messages=messages) -> LLMResponse:
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
            # RUN_END must fire even when the run dies mid-loop.
            await _emit(EventKind.RUN_END, payload={
                "stop_reason": "error", "turns": n_llm_calls,
            })
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
                messages, compacted, compact_info = await maybe_compact(
                    messages,
                    llm_client=llm_client,
                    model=getattr(llm_client, "model", ""),
                    last_input_tokens=response.usage.input_tokens,
                )
                if compacted:
                    if compact_info:
                        ledger["appended"] += compact_info.get("appended", 0)
                        ledger["deleted"] += compact_info.get("deleted", 0)
                    await _emit(EventKind.CONTEXT_COMPACTION, turn=turn + 1,
                                payload=compact_info or {})
                    _slog("compaction", turn=turn + 1, **(compact_info or {}))
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
            _log_append(assistant_msg)

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
                approved_via_ask = False
                if verdict.ask and verdict.allowed:
                    request = ToolApprovalRequest(
                        tool_name=tc.name, arguments=tc.arguments,
                        turn=turn + 1, reason=verdict.reason,
                    )
                    await _emit(EventKind.APPROVAL_REQUESTED, turn=turn + 1,
                                tool_name=tc.name,
                                payload={"summary": request.summary()})
                    approved, note = await resolve_approval(
                        cfg.approver, request, cfg.approval_timeout,
                    )
                    await _emit(EventKind.APPROVAL_RESOLVED, turn=turn + 1,
                                tool_name=tc.name,
                                payload={"approved": approved, "note": note})
                    _slog("approval", tool=tc.name, approved=approved, note=note)
                    if approved:
                        approved_via_ask = True
                    else:
                        result_text = f"[DENIED by approval] {note or verdict.reason}"
                elif not verdict.allowed:
                    result_text = f"[DENIED by policy] {verdict.reason}"

                if not verdict.allowed or (verdict.ask and not approved_via_ask):
                    pass  # result_text already carries the denial text
                else:
                    await _maybe_await(on_tool_start, tc.name, tc.arguments)
                    await _emit(EventKind.TOOL_START, turn=turn + 1,
                                tool_name=tc.name, payload={"arguments": tc.arguments})
                    _slog("tool_call", tool=tc.name, arguments=tc.arguments)
                    result_text = await tools.execute(tc.name, tc.arguments)
                    raw_result_text = result_text
                    rewrite = await hooks.first_response(AgentEvent(
                        EventKind.TOOL_RESULT_REWRITE, turn=turn + 1,
                        tool_name=tc.name,
                        payload={"arguments": tc.arguments, "result": raw_result_text},
                    ))
                    if isinstance(rewrite, str) and rewrite != raw_result_text:
                        _slog("tool_result_rewrite",
                              chars_before=len(raw_result_text),
                              chars_after=len(rewrite))
                        result_text = rewrite
                    if artifacts_dir is not None:
                        result_text = externalize_tool_result(
                            result_text, tc.name, turn + 1, artifacts_dir,
                        )
                    await _emit(EventKind.TOOL_END, turn=turn + 1,
                                tool_name=tc.name,
                                payload={"result_chars": len(result_text)})
                await _maybe_await(on_tool_use, tc.name, tc.arguments, result_text)

                if tc.name in ("write_file",) and (
                    not result_text.startswith("[DENIED")
                ):
                    fp = tc.arguments.get("file_path", "")
                    if fp:
                        files_written.append(fp)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                    # Providers surface this to the model (Anthropic sets
                    # is_error on the tool_result block).
                    "is_error": result_text.startswith(
                        ("Error:", "[DENIED by policy]", "[DENIED by approval]")),
                })
                _log_append(messages[-1])
            else:
                recent_text_responses.clear()
                continue
            # cancel hit mid-tool-batch
            break

        if response.stop_reason == "max_tokens":
            messages.append({"role": "assistant", "content": response.content})
            _log_append(messages[-1])
            injected = _drain_steer_queue(steer_queue, messages)
            if not injected:
                messages.append({"role": "user", "content": "Continue from where you left off."})
                _log_append(messages[-1])
            else:
                _log_append(messages[-1])
                for s in injected:
                    await _maybe_await(on_steer_injected, s)
                    await _emit(EventKind.STEER_INJECTED, payload={"message": s})
                    _slog("steer", message=s[:2000])
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
                _log_append(messages[-1])
                injected = _drain_steer_queue(steer_queue, messages)
                if not injected:
                    messages.append({"role": "user", "content": "Continue."})
                    _log_append(messages[-1])
                else:
                    _log_append(messages[-1])
                    for s in injected:
                        await _maybe_await(on_steer_injected, s)
                        await _emit(EventKind.STEER_INJECTED, payload={"message": s})
                        _slog("steer", message=s[:2000])
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
    _slog("run_end", stop_reason=stop_reason, turns=n_llm_calls)

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
    on_chunk: OnChunkCallback | None = None,
    extra_kwargs: dict | None = None,
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

            # Typed, non-retryable errors propagate as-is (no re-wrapping,
            # no duplicated messages). Retryable ones fall through below.
            if isinstance(exc, LLMError) and not exc.retryable:
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
    queue: asyncio.Queue | None,
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
