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
import logging
import random
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import DEFAULT_MAX_CONTINUATIONS, STEER_PREFIX, TASK_COMPLETE_MARKER
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
    get_attempt_wall_timeout,
    get_first_byte_timeout,
    get_heartbeat_timeout,
    get_max_retries,
    get_retry_base_delay,
)
from .tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


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
    budget_snapshot: dict[str, Any] = field(default_factory=dict)
    #: 子代理身份（P1 统一：orchestrator 曾自建一份字段不同的 AgentResult，
    #: 现收敛到内核这一份；单代理/CLI 不使用这两个字段，保持默认空串）。
    agent_id: str = ""
    agent_role: str = ""


OnTextCallback = Callable[[str], Awaitable[None] | None]
OnToolCallback = Callable[[str, dict[str, Any], str], Awaitable[None] | None]
OnToolStartCallback = Callable[[str, dict[str, Any]], Awaitable[None] | None]
OnTurnStartCallback = Callable[[int, float, "TokenUsage"], Awaitable[None] | None]
OnSteerCallback = Callable[[str], Awaitable[None] | None]


def _conservative_request_token_estimate(
    messages: list[dict], system: str, tools: list[dict] | None,
) -> int:
    """Upper-bound ordinary UTF-8 tokenizer usage for budget reservation.

    Tokenizers may merge bytes but do not normally create more tokens than
    the UTF-8 payload has bytes.  Reserving the serialized byte count keeps a
    shared hard cap safe without coupling the kernel to one provider tokenizer.
    """
    payload = json.dumps(
        {"system": system, "messages": messages, "tools": tools or []},
        ensure_ascii=False, default=str,
    )
    return max(1, len(payload.encode("utf-8")))


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
    #: Model-visible conversation prefix restored by the kernel before the
    #: current user prompt.  These messages are included in the audit ledger.
    initial_messages: list[dict] = field(default_factory=list)
    agent_id: str = ""
    agent_role: str = ""


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
    """Silence detector for one LLM call（R9 重构：两阶段 + 墙钟兜底）.

    - **首字节阶段**（尚无任何 ``on_activity`` 心跳）：连接+TLS+请求排队期间
      没有可续期的心跳，用 *first_byte_timeout* 短窗快失败——旧实现要等满
      静默窗口（300s）才报错，用户面对永久「思考中」；
    - **静默阶段**（已有心跳）：连续 *timeout* 秒无心跳才判死——健康长流不误杀；
    - **墙钟兜底**：单次调用总时长超 *wall_timeout* 即终止。防住「网关每
      <300s 滴一行 keepalive 无限续期」的唯一真·无限挂起路径。
    """

    def __init__(
        self,
        timeout: float,
        first_byte_timeout: float | None = None,
        wall_timeout: float | None = None,
    ) -> None:
        self.timeout = timeout
        self.first_byte_timeout = (
            first_byte_timeout if first_byte_timeout is not None else timeout
        )
        self.wall_timeout = wall_timeout  # None = 不限（保持旧行为）
        self._activity = asyncio.Event()

    def beat(self) -> None:
        self._activity.set()

    @staticmethod
    async def _swallow(task: "asyncio.Task[Any]") -> None:
        # 尽力而为清理：等待已取消的内层任务收尾，其异常（多为 CancelledError）
        # 已由调用方按超时/取消语义另行上报，无需在此重复。
        task.cancel()
        try:
            await task
        except BaseException:  # noqa: BLE001 — 取消路径专用兜底
            pass

    async def call(self, coro_factory: Callable[[], Any]) -> LLMResponse:
        # 每次尝试独立计量：同一重试循环里上一尝试残留的心跳标记不得为
        # 本次首字节窗「续命」（否则流式中断后的重试首字节窗 60s 退化为
        # 静默大窗 300s，快失败语义失效）。
        self._activity.clear()
        task = asyncio.create_task(coro_factory())
        started = time.time()
        ever_beaten = False
        try:
            while True:
                window = self.timeout if ever_beaten else self.first_byte_timeout
                try:
                    return await asyncio.wait_for(asyncio.shield(task), timeout=window)
                except asyncio.TimeoutError:
                    if self._activity.is_set():
                        self._activity.clear()
                        ever_beaten = True
                        # 心跳在续期也要服从墙钟：keepalive 滴流不能无限续命
                        if (
                            self.wall_timeout is not None
                            and time.time() - started >= self.wall_timeout
                        ):
                            await self._swallow(task)
                            raise HeartbeatTimeoutError(
                                self.wall_timeout, phase="总时长"
                            ) from None
                        continue
                    await self._swallow(task)
                    raise HeartbeatTimeoutError(
                        window,
                        phase="" if ever_beaten else "首字节",
                    ) from None
                except asyncio.CancelledError:
                    # 外部（停止/断连）取消：连带杀掉内层请求后原样上抛
                    if not task.done():
                        await self._swallow(task)
                    raise
        finally:
            if not task.done():
                task.cancel()


class _TurnCancelled(Exception):
    """用户停止 / 连接断开打断在途 LLM 调用（run_agent 转为 cancelled 停止）。"""


async def _cancelable(coro: Any, cancel_event: asyncio.Event | None) -> LLMResponse:
    """让一次完整 LLM 调用（含重试退避）可被 cancel_event 立即打断。

    旧实现里 cancel_event 只在轮次/工具边界检查——若进程阻塞在流读取或重试
    sleep 中，点「停止」毫无作用（R9 反馈的体感即「只能干等」）。这里把
    等待与 cancel_event.wait() 做成赛跑，先到者赢；被取消路径连内层 httpx
    流一起终止（watchdog 的 finally 会收尾内层任务）。
    """
    if cancel_event is None:
        return await coro
    runner = asyncio.ensure_future(coro)
    waiter = asyncio.ensure_future(cancel_event.wait())
    try:
        done, _ = await asyncio.wait({runner, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if runner in done:
            return runner.result()
        raise _TurnCancelled()
    finally:
        waiter.cancel()
        if not runner.done():
            runner.cancel()
            try:
                await runner
            except BaseException:
                # 尽力而为清理：内层请求已随 cancel_event 终止，
                # 真实原因以 _TurnCancelled 路径为准，这里只等收尾。
                pass


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
    on_thought: OnTextCallback | None = None,
    on_tool_use: OnToolCallback | None = None,
    on_tool_start: OnToolStartCallback | None = None,
    on_turn_start: OnTurnStartCallback | None = None,
    steer_queue: asyncio.Queue | None = None,
    on_steer_injected: OnSteerCallback | None = None,
) -> AgentResult:
    """Run an agentic conversation loop to completion.

    A+ 阶段 3 / A-1 拆分后的编排壳：本函数只保留**顺序决策**（回合循环、
    各阶段衔接、终止判定），可变的运行状态显式化为 :class:`_RunState`，
    运行环境为 :class:`_RunEnv`，各阶段（预算门 / LLM 调用 / 压缩 / 工具批 /
    steer 注入）各自成模块级函数。所有错误都以 ``Error …`` 语义经
    ``AgentResult``/异常上抛路径返回，行为与拆分前逐分支等价。

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
        on_thought: Callback for streaming reasoning/thinking deltas (R17).
            Delivered on a separate channel; never part of the reply text.
        on_tool_use: Callback(tool_name, arguments, result) after tool execution.
        on_tool_start: Callback(tool_name, arguments) before tool execution.
        on_turn_start: Callback(turn, elapsed, usage) at start of each LLM call.
        steer_queue: asyncio.Queue for mid-execution user messages.
        on_steer_injected: Callback(message) when a steer is consumed.

    Returns:
        AgentResult with collected output, metadata, and stop_reason.
    """
    env, state = _prepare_run(
        prompt=prompt, system_prompt=system_prompt, llm_client=llm_client,
        tools=tools, config=config, max_turns=max_turns,
        auto_continue=auto_continue, max_continuations=max_continuations,
        temperature=temperature, max_tokens=max_tokens,
        on_text=on_text, on_thought=on_thought, on_tool_use=on_tool_use,
        on_tool_start=on_tool_start, on_turn_start=on_turn_start,
        steer_queue=steer_queue, on_steer_injected=on_steer_injected,
    )
    cfg = env.cfg
    mirror = state.mirror
    start_time = time.time()

    async def _emit(kind: EventKind, **kw: Any) -> Any:
        return await env.hooks.emit(AgentEvent(kind, **kw))

    # --- RUN_START + 历史镜像入账（原 setup 段尾部，需 await 故留在编排壳） ---
    await _emit(EventKind.RUN_START, payload={"prompt_chars": len(prompt)})
    for restored in state.messages[:-1]:
        mirror.log_append(restored, origin="history")
    mirror.log_append(state.messages[-1], origin="current")

    async def _supervised_chat(
        *,
        messages: list[dict],
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> LLMResponse:
        """带完整监督的单次 chat 调用，注入给压缩摘要（kernel/context）。

        复用主链路同一套设施——_ActivityWatchdog 两阶段看门狗（活动标记在
        每尝试入口自清）、_llm_call_with_retry 指数退避重试、_cancelable 停止
        打断（_TurnCancelled 语义与主链路一致）——不自建第二套监督。
        """
        watchdog = _ActivityWatchdog(
            env.heartbeat_timeout,
            # 显式配置的静默窗若小于首字节默认值，则以其为准（不放宽调用方契约）
            first_byte_timeout=min(env.heartbeat_timeout, get_first_byte_timeout()),
            wall_timeout=get_attempt_wall_timeout(),
        )
        kwargs: dict[str, Any] = (
            {"on_activity": watchdog.beat} if env.use_activity else {}
        )
        return await _cancelable(
            _llm_call_with_retry(
                llm_client, messages, system, None,
                temperature, max_tokens, env.heartbeat_timeout,
                env.max_retries, env.base_delay,
                extra_kwargs=kwargs,
                watchdog=watchdog,
            ),
            cfg.cancel_event,
        )
    env.supervised_chat = _supervised_chat

    turn = -1
    for turn in range(cfg.max_turns):
        # --- cooperative cancellation -------------------------------------
        if cfg.cancel_event is not None and cfg.cancel_event.is_set():
            state.stop_reason = "cancelled"
            break

        await _drain_steer_and_announce(env, state)

        await _maybe_await(
            env.on_turn_start, turn + 1, time.time() - start_time,
            state.total_usage,
        )
        await _emit(EventKind.TURN_START, turn=turn + 1)

        # --- budget gate ---------------------------------------------------
        reservation, request_max_tokens, blocked = await _reserve_budget(
            env, state, turn,
        )
        if blocked:
            break

        # --- LLM call ------------------------------------------------------
        try:
            response = await _call_llm_turn(
                env, state, turn, request_max_tokens, reservation,
            )
        except _TurnCancelled:
            state.stop_reason = "cancelled"
            break
        # BudgetExceededError / Exception / BaseException 的清理与事件已在
        # _call_llm_turn 内完成（归还预留 + RUN_END），这里原样上抛。

        # --- context compaction (after measuring real usage) ---------------
        if await _compact_if_needed(env, state, turn, response):
            break

        if response.content:
            state.collected_text += response.content
            if not env.streaming:
                await _maybe_await(env.on_text, response.content)

        if response.tool_calls:
            if await _execute_tool_batch(env, state, turn, response):
                # cancel hit mid-tool-batch
                break
            state.recent_text_responses.clear()
            continue

        if response.stop_reason == "max_tokens":
            await _append_continuation(
                env, state, content=response.content,
                nudge="Continue from where you left off.",
            )
            if state.continuation_count >= cfg.max_continuations:
                state.stop_reason = "max_continuations"
                break
            continue

        if response.stop_reason == "end_turn":
            if TASK_COMPLETE_MARKER in (response.content or ""):
                break

            if response.content and not response.tool_calls:
                state.recent_text_responses.append(response.content.strip())
                if len(state.recent_text_responses) > 5:
                    state.recent_text_responses.pop(0)

            if _is_completion_loop(state.recent_text_responses):
                break

            if cfg.auto_continue and state.continuation_count < cfg.max_continuations:
                await _append_continuation(
                    env, state, content=response.content, nudge="Continue.",
                )
                continue
            break

        break
    else:
        state.stop_reason = "max_turns"

    await _emit(EventKind.RUN_END, payload={
        "stop_reason": state.stop_reason,
        "turns": state.n_llm_calls,
    })
    mirror.slog("run_end", stop_reason=state.stop_reason, turns=state.n_llm_calls)

    duration = time.time() - start_time
    return AgentResult(
        success=True,
        text_output=state.collected_text,
        files_written=state.files_written,
        duration_seconds=duration,
        token_usage=state.total_usage,
        turns=state.n_llm_calls,
        stop_reason=state.stop_reason,
    )


class _SessionMirror:
    """会话日志镜像（"model-visible is logged"）。

    `messages` 的每次变更都经由本类，维护一个长度账本；每次 LLM 请求前
    断言真实列表长度与账本一致，未入账的变更无法悄然溜过（软告警——
    契约见 docs/protocol.md）。A+ 3.1 从 run_agent 内嵌三元组闭包显式化。
    """

    def __init__(self, session_log: Any) -> None:
        self.session_log = session_log
        self.appended = 0
        self.deleted = 0

    @property
    def expected_len(self) -> int:
        return self.appended - self.deleted

    def slog(self, kind: str, **data: Any) -> None:
        if self.session_log is None:
            return
        try:
            self.session_log.log(kind, data)
        except Exception:
            pass  # telemetry must never break the run

    def log_append(self, msg: dict, *, origin: str = "current") -> None:
        self.appended += 1
        seq = self.appended - self.deleted - 1
        content = msg.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False, default=str)
        self.slog("msg_add", seq=seq, role=msg.get("role", "?"),
                  content=str(content)[:20_000],
                  tool_calls=bool(msg.get("tool_calls")), origin=origin)

    def log_delete(self, n: int) -> None:
        self.deleted += n


@dataclass
class _RunState:
    """run_agent 回合循环的可变状态（A+ 3.1：从 556 行闭包里显式化）。"""

    messages: list[dict]
    mirror: _SessionMirror
    collected_text: str = ""
    files_written: list[str] = field(default_factory=list)
    total_usage: TokenUsage = field(default_factory=TokenUsage)
    n_llm_calls: int = 0
    continuation_count: int = 0
    recent_text_responses: list[str] = field(default_factory=list)
    stop_reason: str = "completed"


@dataclass
class _RunEnv:
    """run_agent 的运行环境（回调 / 基础设施；一次构建，循环内只读）。"""

    cfg: RunConfig
    hooks: HookBus
    tools: ToolRegistry
    llm_client: LLMClient
    budget: BudgetGuard | None
    heartbeat_timeout: float
    max_retries: int
    base_delay: float
    tool_schemas: list[dict]
    system_prompt: str
    artifacts_dir: Path | None
    use_activity: bool
    streaming: bool
    steer_queue: asyncio.Queue | None
    on_text: OnTextCallback | None
    on_thought: OnTextCallback | None
    on_tool_use: OnToolCallback | None
    on_tool_start: OnToolStartCallback | None
    on_turn_start: OnTurnStartCallback | None
    on_steer_injected: OnSteerCallback | None
    #: 压缩摘要用的受监督 chat；由 run_agent 在闭包内赋值（依赖本地设施）。
    supervised_chat: Callable[..., Any] | None = None

    async def emit(self, kind: EventKind, **kw: Any) -> Any:
        """统一事件出口：各阶段函数经此发事件（原 _emit 闭包的显式化）。"""
        return await self.hooks.emit(AgentEvent(kind, **kw))


def _prepare_run(
    *,
    prompt: str,
    system_prompt: str,
    llm_client: LLMClient,
    tools: ToolRegistry,
    config: RunConfig | None,
    max_turns: int,
    auto_continue: bool,
    max_continuations: int,
    temperature: float,
    max_tokens: int,
    on_text: OnTextCallback | None,
    on_thought: OnTextCallback | None,
    on_tool_use: OnToolCallback | None,
    on_tool_start: OnToolStartCallback | None,
    on_turn_start: OnTurnStartCallback | None,
    steer_queue: asyncio.Queue | None,
    on_steer_injected: OnSteerCallback | None,
) -> tuple[_RunEnv, _RunState]:
    """装配运行环境与初始状态（原 run_agent 的 323-427 行 setup 段）。"""
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

    # A supplied bus contains host observers.  Fork it before mounting
    # per-run permission and repeat-call guards so parallel agents do not
    # mutate one another's handler lists or share guard state.
    hooks = cfg.hooks.fork() if cfg.hooks is not None else HookBus()

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

    messages: list[dict] = [dict(message) for message in cfg.initial_messages]
    messages.append({"role": "user", "content": prompt})
    tool_schemas = tools.get_schemas()

    mirror = _SessionMirror(cfg.session_log)

    # Mount the repeat-call guard (env-tunable, on by default).
    if cfg.repeat_guard is not False:
        guard = (cfg.repeat_guard if callable(cfg.repeat_guard)
                 else repeat_guard_from_env())
        if guard is not None:
            hooks.on(EventKind.PRE_TOOL_USE, guard)

    # Per-run scratch space for externalized tool outputs.
    artifacts_dir: Path | None = None
    if cfg.externalize_outputs:
        work_dir = getattr(tools, "work_dir", None)
        if work_dir:
            artifacts_dir = Path(work_dir) / ".ra" / "tool_outputs"

    env = _RunEnv(
        cfg=cfg, hooks=hooks, tools=tools, llm_client=llm_client,
        budget=budget, heartbeat_timeout=heartbeat_timeout,
        max_retries=get_max_retries(), base_delay=get_retry_base_delay(),
        tool_schemas=tool_schemas, system_prompt=system_prompt,
        artifacts_dir=artifacts_dir,
        use_activity=_supports_on_activity(llm_client),
        streaming=on_text is not None,
        steer_queue=steer_queue,
        on_text=on_text, on_thought=on_thought, on_tool_use=on_tool_use,
        on_tool_start=on_tool_start, on_turn_start=on_turn_start,
        on_steer_injected=on_steer_injected,
    )
    state = _RunState(messages=messages, mirror=mirror)
    return env, state


async def _drain_steer_and_announce(env: _RunEnv, state: _RunState) -> list[str]:
    """回合开始处消费 steer 队列并广播（原回合开头段，三处重复中第一处）。"""
    injected = _drain_steer_queue(env.steer_queue, state.messages)
    if injected:
        state.mirror.log_append(state.messages[-1])
    for s in injected:
        await _maybe_await(env.on_steer_injected, s)
        await env.emit(EventKind.STEER_INJECTED, payload={"message": s})
        state.mirror.slog("steer", message=s[:2000])
    return injected


async def _append_continuation(
    env: _RunEnv, state: _RunState, *, content: str, nudge: str,
) -> None:
    """max_tokens 续跑与 auto_continue 共用（原两处近乎相同的块）：
    追加 assistant 消息 → 注入 steer 或追加续跑提示 → 计数。"""
    state.messages.append({"role": "assistant", "content": content})
    state.mirror.log_append(state.messages[-1])
    injected = _drain_steer_queue(env.steer_queue, state.messages)
    if not injected:
        state.messages.append({"role": "user", "content": nudge})
        state.mirror.log_append(state.messages[-1])
    else:
        state.mirror.log_append(state.messages[-1])
        for s in injected:
            await _maybe_await(env.on_steer_injected, s)
            await env.emit(EventKind.STEER_INJECTED, payload={"message": s})
            state.mirror.slog("steer", message=s[:2000])
    state.continuation_count += 1


async def _reserve_budget(
    env: _RunEnv, state: _RunState, turn: int,
) -> tuple[Any, int, bool]:
    """预算门（原 budget gate 段）。

    Returns:
        ``(reservation, request_max_tokens, blocked)``；``blocked=True``
        表示预算已超限（事件已发、stop_reason 已置、文本已附），调用方
        应立即终止运行。
    """
    if env.budget is None:
        return None, env.cfg.max_tokens, False
    try:
        reservation = env.budget.reserve(
            max_output_tokens=env.cfg.max_tokens,
            estimated_input_tokens=_conservative_request_token_estimate(
                state.messages, env.system_prompt, env.tool_schemas,
            ),
        )
    except BudgetExceededError as exc:
        await env.emit(EventKind.BUDGET_EXCEEDED, payload={"report": exc.report})
        state.stop_reason = "budget_exceeded"
        state.collected_text += f"\n[BUDGET EXCEEDED] {exc.report}\n"
        return None, env.cfg.max_tokens, True
    for w in reservation.warnings:
        await env.emit(EventKind.BUDGET_WARNING, payload={"message": w})
    return reservation, reservation.max_output_tokens, False


async def _call_llm_turn(
    env: _RunEnv, state: _RunState, turn: int,
    request_max_tokens: int, reservation: Any,
) -> LLMResponse:
    """单次 LLM 调用 + 用量入账 + 计时事件（原 LLM call + accounting 段）。

    失败路径在本函数内完成清理（归还预算预留、补发 RUN_END）后**原样上抛**；
    调用方只负责把异常映射为 ``stop_reason``/终止（_TurnCancelled → cancelled，
    BudgetExceededError 与其余异常照原语义上抛）。
    """
    mirror = state.mirror
    expected_len = mirror.expected_len
    if len(state.messages) != expected_len:
        await env.emit(EventKind.INVARIANT_WARNING, payload={
            "expected": expected_len, "actual": len(state.messages),
        })
        mirror.slog("invariant_warning", expected=expected_len,
                    actual=len(state.messages))

    watchdog = _ActivityWatchdog(
        env.heartbeat_timeout,
        # 显式配置的静默窗若小于首字节默认值，则以其为准（不放宽调用方契约）
        first_byte_timeout=min(env.heartbeat_timeout, get_first_byte_timeout()),
        wall_timeout=get_attempt_wall_timeout(),
    )

    llm_started = time.monotonic()
    call_first_chunk_at: float | None = None

    async def _stream_chunk(chunk: str) -> None:
        nonlocal call_first_chunk_at
        if call_first_chunk_at is None:
            call_first_chunk_at = time.monotonic()
        await _maybe_await(env.on_text, chunk)

    async def _stream_thought(chunk: str) -> None:
        # R17：思考增量直通，不进重试发布追踪（thought 无需重发标注，
        # 也绝不混入 reply 正文）。
        await _maybe_await(env.on_thought, chunk)

    async def _do_call() -> LLMResponse:
        kwargs: dict[str, Any] = {}
        if env.use_activity:
            kwargs["on_activity"] = watchdog.beat
        if env.on_thought is not None:
            kwargs["on_thought"] = _stream_thought
        # watchdog 传入重试循环内部：监督每次尝试（R9，见函数 docstring）
        return await _llm_call_with_retry(
            env.llm_client, state.messages, env.system_prompt, env.tool_schemas,
            env.cfg.temperature, request_max_tokens, env.heartbeat_timeout,
            env.max_retries, env.base_delay,
            on_chunk=_stream_chunk if env.streaming else None,
            extra_kwargs=kwargs,
            watchdog=watchdog,
        )

    await env.emit(EventKind.LLM_REQUEST, turn=turn + 1,
                   payload={"messages": len(state.messages)})
    try:
        # _cancelable：停止/断连可立即打断在途调用（含尝试间退避期）
        response = await _cancelable(_do_call(), env.cfg.cancel_event)
    except _TurnCancelled:
        if reservation is not None:
            env.budget.release(reservation)
        raise
    except BudgetExceededError:
        if reservation is not None:
            env.budget.release(reservation)
        raise
    except Exception as exc:
        if reservation is not None:
            env.budget.release(reservation)
        await env.emit(EventKind.ERROR, payload={"error": str(exc)})
        # RUN_END must fire even when the run dies mid-loop.
        await env.emit(EventKind.RUN_END, payload={
            "stop_reason": "error", "turns": state.n_llm_calls,
        })
        raise
    except BaseException:
        # 缺陷 A：asyncio.CancelledError 是 BaseException，旧实现直接穿堂——
        # supervisor.wait_for 超时、断连兜底 task.cancel() 后预算预留永久
        # 滞留 BudgetGuard、RUN_END 缺失。这里先归还预留（同步方法），再
        # 尽力补发 RUN_END(cancelled) 让前端收尾，最后原样上抛取消。
        if reservation is not None:
            env.budget.release(reservation)
        try:
            await env.emit(EventKind.RUN_END, payload={
                "stop_reason": "cancelled", "turns": state.n_llm_calls,
            })
        except BaseException:
            pass  # 取消路径上的收尾尽力而为；原始异常优先上抛
        raise

    _accumulate_usage(state.total_usage, response)
    state.n_llm_calls += 1
    if env.budget is not None:
        if reservation is not None:
            env.budget.commit(reservation, response)
        else:
            env.budget.record(response)
    await env.emit(EventKind.LLM_RESPONSE, turn=turn + 1, payload={
        "stop_reason": response.stop_reason,
        "tool_calls": len(response.tool_calls),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "elapsed_seconds": round(time.monotonic() - llm_started, 3),
        "first_chunk_seconds": (
            round(call_first_chunk_at - llm_started, 3)
            if call_first_chunk_at is not None
            else None
        ),
    })
    mirror.slog(
        "llm_timing", turn=turn + 1,
        elapsed_seconds=round(time.monotonic() - llm_started, 3),
        first_chunk_seconds=(
            round(call_first_chunk_at - llm_started, 3)
            if call_first_chunk_at is not None
            else None
        ),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return response


async def _compact_if_needed(
    env: _RunEnv, state: _RunState, turn: int, response: LLMResponse,
) -> bool:
    """上下文压缩（原 compaction 段）。返回 True = 因取消终止运行。"""
    if not env.cfg.compaction:
        return False
    try:
        state.messages, compacted, compact_info = await maybe_compact(
            state.messages,
            llm_client=env.llm_client,
            model=getattr(env.llm_client, "model", ""),
            last_input_tokens=response.usage.input_tokens,
            # 压缩用的摘要调用同样计入预算计量（缺陷 I）
            budget=env.budget,
            # 摘要调用复用主链路监督（看门狗/取消/重试）——否则挂死的
            # 摘要请求既不会被击杀也不会被「停止」打断（永久思考中）
            supervised_chat=env.supervised_chat,
        )
        if compacted:
            if compact_info:
                state.mirror.appended += compact_info.get("appended", 0)
                state.mirror.deleted += compact_info.get("deleted", 0)
            await env.emit(EventKind.CONTEXT_COMPACTION, turn=turn + 1,
                           payload=compact_info or {})
            state.mirror.slog("compaction", turn=turn + 1, **(compact_info or {}))
        return False
    except _TurnCancelled:
        # 用户停止打断挂死中的摘要：取消不得被下面的「尽力而为」降级
        # 吞成照常继续——普通异常才允许降级，取消语义与主链路一致。
        state.stop_reason = "cancelled"
        return True
    except Exception as exc:
        # 压缩是尽力而为：失败不杀健康的运行，但静默吞掉会让
        # 「上下文为何爆掉」无从排查（缺陷 I）。
        logger.warning("上下文压缩失败: %s", exc)
        return False


async def _execute_tool_batch(
    env: _RunEnv, state: _RunState, turn: int, response: LLMResponse,
) -> bool:
    """执行本回合的整批工具调用（原 tool batch 段，最大的单一分块）。

    Returns:
        True = 批中途命中取消（调用方应终止运行）；
        False = 全部执行完毕（调用方进入下一回合）。
    """
    mirror = state.mirror
    assistant_msg: dict[str, Any] = {"role": "assistant", "tool_calls": [
        {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
        for tc in response.tool_calls
    ]}
    if response.content:
        assistant_msg["content"] = response.content
    state.messages.append(assistant_msg)
    mirror.log_append(assistant_msg)

    for tc in response.tool_calls:
        if env.cfg.cancel_event is not None and env.cfg.cancel_event.is_set():
            state.stop_reason = "cancelled"
            return True

        verdict = await env.emit(
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
                agent_id=env.cfg.agent_id, agent_role=env.cfg.agent_role,
                request_id=uuid.uuid4().hex,
            )
            await env.emit(EventKind.APPROVAL_REQUESTED, turn=turn + 1,
                           tool_name=tc.name,
                           payload={"summary": request.summary(),
                                    "agent_id": env.cfg.agent_id,
                                    "role": env.cfg.agent_role})
            approved, note = await resolve_approval(
                env.cfg.approver, request, env.cfg.approval_timeout,
            )
            await env.emit(EventKind.APPROVAL_RESOLVED, turn=turn + 1,
                           tool_name=tc.name,
                           payload={"approved": approved, "note": note,
                                    "agent_id": env.cfg.agent_id,
                                    "role": env.cfg.agent_role})
            mirror.slog("approval", tool=tc.name, approved=approved, note=note)
            if approved:
                approved_via_ask = True
            else:
                result_text = f"[DENIED by approval] {note or verdict.reason}"
        elif not verdict.allowed:
            result_text = f"[DENIED by policy] {verdict.reason}"

        if not verdict.allowed or (verdict.ask and not approved_via_ask):
            pass  # result_text already carries the denial text
        else:
            await _maybe_await(env.on_tool_start, tc.name, tc.arguments)
            await env.emit(EventKind.TOOL_START, turn=turn + 1,
                           tool_name=tc.name,
                           payload={"arguments": tc.arguments})
            mirror.slog("tool_call", tool=tc.name, arguments=tc.arguments)
            tool_started = time.monotonic()
            result_text = await env.tools.execute(tc.name, tc.arguments)
            tool_elapsed = round(time.monotonic() - tool_started, 3)
            raw_result_text = result_text
            rewrite = await env.hooks.first_response(AgentEvent(
                EventKind.TOOL_RESULT_REWRITE, turn=turn + 1,
                tool_name=tc.name,
                payload={"arguments": tc.arguments, "result": raw_result_text},
            ))
            if isinstance(rewrite, str) and rewrite != raw_result_text:
                mirror.slog("tool_result_rewrite",
                            chars_before=len(raw_result_text),
                            chars_after=len(rewrite))
                result_text = rewrite
            if env.artifacts_dir is not None:
                result_text = externalize_tool_result(
                    result_text, tc.name, turn + 1, env.artifacts_dir,
                )
            await env.emit(EventKind.TOOL_END, turn=turn + 1,
                           tool_name=tc.name,
                           payload={
                               "result_chars": len(result_text),
                               "elapsed_seconds": tool_elapsed,
                           })
            mirror.slog(
                "tool_timing", tool=tc.name, turn=turn + 1,
                elapsed_seconds=tool_elapsed,
                result_chars=len(result_text),
            )
        await _maybe_await(env.on_tool_use, tc.name, tc.arguments, result_text)

        if tc.name in ("write_file",) and (
            not result_text.startswith("[DENIED")
        ):
            fp = tc.arguments.get("file_path", "")
            if fp:
                state.files_written.append(fp)

        state.messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": result_text,
            # Providers surface this to the model (Anthropic sets
            # is_error on the tool_result block).
            # 修复（工程债）：工具层实际返回的前缀是 "Error executing …" /
            # "Error reading …" / "Error writing …" 等，旧判定只认 "Error:"
            # 导致 Anthropic 侧工具失败不标 is_error、模型把报错当正常结果
            # 继续推理。统一按 "Error" 前缀 + DENIED 标记判定（工具契约：
            # 一切错误回执都以 Error 开头，见 tools/registry.py、file_ops.py）。
            "is_error": result_text.startswith(
                ("Error", "[DENIED by policy]", "[DENIED by approval]")),
        })
        mirror.log_append(state.messages[-1])
    return False


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
    watchdog: "_ActivityWatchdog | None" = None,
) -> LLMResponse:
    """Call the LLM with retry on transient errors and a silence watchdog.

    R9：*watchdog* 监督**每次尝试**（而非整个重试循环）——否则心跳超时异常
    会从循环外一击穿、绕过全部重试（retryable 形同虚设）。每次尝试都获得
    完整的首字节窗口 / 静默窗口与墙钟。

    R12.x 流式直通：on_chunk 实时透传给调用方，不再缓冲到整次调用成功后
    回放（旧行为让 UI 全程看不到正文）。若某次尝试已发布过正文后才失败，
    下一次尝试开始前先补一条「生成中断，正在自动重试」标注——诚实告知，
    避免两段文本无解释地拼接；首块之前的失败（连接 / 429 / 首字节超时等
    最常见场景）依旧无痕重试。
    """
    last_exc: BaseException | None = None
    extra_kwargs = extra_kwargs or {}

    for attempt in range(max_retries + 1):
        # 记录本次尝试是否已经向调用方发布过流式 chunk（外部可见、不可回滚）。
        published = [False]

        def _tracked_chunk(text: str, _flag=published) -> Any:
            _flag[0] = True
            return on_chunk(text)

        attempt_callback = _tracked_chunk if on_chunk is not None else None

        def _one_attempt(attempt_callback=attempt_callback) -> Any:
            return client.chat(
                messages,
                system=system,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                on_chunk=attempt_callback,
                **extra_kwargs,
            )

        try:
            if watchdog is not None:
                response = await watchdog.call(_one_attempt)
            else:
                response = await _one_attempt()
            return response
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

            # 本次尝试已流出过正文才需要标注；首块之前的失败保持无痕重试。
            if on_chunk is not None and published[0]:
                await _maybe_await(on_chunk, "\n\n[生成中断，正在自动重试…]\n\n")

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
        combined = "\n".join(f"{STEER_PREFIX} {s}" for s in steers)
        messages.append({"role": "user", "content": combined})

    return steers
