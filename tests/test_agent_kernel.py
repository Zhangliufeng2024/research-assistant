"""Tests for agent-loop kernel integration: hooks, budget, cancel, heartbeat."""

import asyncio
import time

import pytest

from research_assistant.agent import RunConfig, run_agent
from research_assistant.kernel.budget import BudgetGuard, BudgetLimits
from research_assistant.kernel.events import EventKind, HookBus, HookVerdict
from research_assistant.llm.base import LLMClient, LLMResponse
from research_assistant.llm.errors import HeartbeatTimeoutError, NetworkError
from research_assistant.tools.registry import ToolRegistry


class ScriptedClient(LLMClient):
    """Returns scripted responses in order, then a final plain response."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._i = 0

    async def chat(self, messages, *, system="", tools=None, temperature=0.7,
                   max_tokens=16384, on_chunk=None, **kw):
        if self._i < len(self._responses):
            r = self._responses[self._i]
        else:
            r = LLMResponse(content=f"[TASK_COMPLETE] done {self._i}")
        self._i += 1
        return r

    async def close(self):
        pass


def _tool_call_response(name="bash", arguments=None, cid="c1"):
    return LLMResponse(
        content="",
        tool_calls=[type("TC", (), {"id": cid, "name": name,
                                    "arguments": arguments or {}})()],
        stop_reason="tool_use",
    )


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pre_tool_use_hook_denies_execution(tmp_path):
    canary = tmp_path / "canary.txt"
    bus = HookBus()

    async def deny_bash(event):
        if event.tool_name == "bash":
            return HookVerdict(allowed=False, reason="bash disabled in test")
        return None

    bus.on(EventKind.PRE_TOOL_USE, deny_bash)
    client = ScriptedClient([
        _tool_call_response("bash", {"command": f"echo hi > {canary}"}),
    ])

    seen_results = []

    async def on_tool_use(name, args, result):
        seen_results.append((name, result))

    result = await run_agent(
        prompt="go", system_prompt="s", llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(hooks=bus, auto_continue=False),
        on_tool_use=on_tool_use,
    )

    assert result.stop_reason == "completed"
    assert seen_results[0][0] == "bash"
    assert "[DENIED by policy] bash disabled in test" in seen_results[0][1]
    assert not canary.exists(), "denied tool must not execute"


@pytest.mark.asyncio
async def test_lifecycle_events_emitted(tmp_path):
    bus = HookBus()
    kinds = []

    def recorder(event):
        kinds.append(event.kind)

    for k in (EventKind.RUN_START, EventKind.TURN_START,
              EventKind.LLM_REQUEST, EventKind.LLM_RESPONSE, EventKind.RUN_END):
        bus.on(k, recorder)

    client = ScriptedClient([LLMResponse(content="[TASK_COMPLETE] ok")])
    await run_agent(
        prompt="p", system_prompt="s", llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(hooks=bus, auto_continue=False),
    )

    assert EventKind.RUN_START in kinds
    assert EventKind.TURN_START in kinds
    assert EventKind.LLM_REQUEST in kinds
    assert EventKind.LLM_RESPONSE in kinds
    assert EventKind.RUN_END in kinds


@pytest.mark.asyncio
async def test_reused_hook_bus_does_not_accumulate_per_run_handlers(tmp_path):
    bus = HookBus()
    observed: list[EventKind] = []
    bus.on(EventKind.RUN_START, lambda event: observed.append(event.kind))
    original_counts = {k: len(v) for k, v in bus._handlers.items()}

    for _ in range(2):
        await run_agent(
            prompt="p", system_prompt="s",
            llm_client=ScriptedClient([
                LLMResponse(content="[TASK_COMPLETE] ok"),
            ]),
            tools=ToolRegistry(work_dir=str(tmp_path)),
            config=RunConfig(hooks=bus, auto_continue=False),
        )

    assert observed == [EventKind.RUN_START, EventKind.RUN_START]
    assert {k: len(v) for k, v in bus._handlers.items()} == original_counts
    assert EventKind.PRE_TOOL_USE not in bus._handlers


@pytest.mark.asyncio
async def test_restored_history_is_model_visible_and_audited(tmp_path):
    class Log:
        def __init__(self):
            self.events = []

        def log(self, kind, data=None):
            self.events.append({"kind": kind, "data": data or {}})

    log = Log()
    captured: list[list[dict]] = []

    class CaptureClient(ScriptedClient):
        async def chat(self, messages, **kwargs):
            captured.append([dict(m) for m in messages])
            return await super().chat(messages, **kwargs)

    await run_agent(
        prompt="new question", system_prompt="s",
        llm_client=CaptureClient([
            LLMResponse(content="[TASK_COMPLETE] answer"),
        ]),
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(
            auto_continue=False,
            initial_messages=[
                {"role": "user", "content": "old question"},
                {"role": "assistant", "content": "old answer"},
            ],
            session_log=log,
        ),
    )

    assert [m["content"] for m in captured[0]] == [
        "old question", "old answer", "new question",
    ]
    additions = [e["data"] for e in log.events if e["kind"] == "msg_add"]
    assert [e["origin"] for e in additions[:3]] == [
        "history", "history", "current",
    ]


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_budget_exceeded_stops_gracefully(tmp_path):
    guard = BudgetGuard(BudgetLimits(max_turns=1), model="claude-sonnet-5")
    client = ScriptedClient([
        LLMResponse(content="turn one"),
        LLMResponse(content="turn two"),  # would need turn 2 -> blocked by budget
    ])
    # auto_continue would normally keep going forever; budget must stop it.
    result = await run_agent(
        prompt="p", system_prompt="s", llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(
            budget=guard, auto_continue=True, max_continuations=50,
        ),
    )
    assert result.stop_reason == "budget_exceeded"
    assert "[BUDGET EXCEEDED]" in result.text_output
    assert result.success  # graceful stop is still a successful run


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_event_before_run(tmp_path):
    cancel = asyncio.Event()
    cancel.set()
    client = ScriptedClient([LLMResponse(content="hello")])

    result = await run_agent(
        prompt="p", system_prompt="s", llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(cancel_event=cancel, auto_continue=False),
    )
    assert result.stop_reason == "cancelled"
    assert result.turns == 0


@pytest.mark.asyncio
async def test_cancel_event_between_tools(tmp_path):
    cancel = asyncio.Event()
    client = ScriptedClient([
        _tool_call_response("write_file",
                            {"file_path": str(tmp_path / "a.txt"), "content": "x"},
                            cid="c1"),
    ])

    async def flip_on_first_tool(name, args, result):
        cancel.set()

    result = await run_agent(
        prompt="p", system_prompt="s", llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(cancel_event=cancel, auto_continue=False),
        on_tool_use=flip_on_first_tool,
    )
    assert result.stop_reason == "cancelled"


# ---------------------------------------------------------------------------
# Externalization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_large_tool_result_externalized(tmp_path):
    big_file = tmp_path / "big.txt"
    big_file.write_text("y" * 10_000, encoding="utf-8")

    client = ScriptedClient([
        _tool_call_response("read_file", {"file_path": str(big_file)}),
    ])
    captured = []

    async def on_tool_use(name, args, result):
        captured.append(result)

    await run_agent(
        prompt="p", system_prompt="s", llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(externalize_outputs=True, auto_continue=False),
        on_tool_use=on_tool_use,
    )

    out_dir = tmp_path / ".ra" / "tool_outputs"
    files = list(out_dir.glob("turn_*_read_file.txt"))
    assert len(files) == 1
    # read_file output includes line-number prefixes, so >= the raw size.
    assert files[0].stat().st_size >= 10_000
    assert "[OUTPUT TRUNCATED" in captured[0]
    assert str(files[0]) in captured[0]


# ---------------------------------------------------------------------------
# Heartbeat watchdog
# ---------------------------------------------------------------------------

class SlowStreamingClient(LLMClient):
    """Streams several chunks with real sleeps, feeding on_activity."""

    def __init__(self, chunk_sleep: float, chunks: int = 4, silent: bool = False):
        self.chunk_sleep = chunk_sleep
        self.chunks = chunks
        self.silent = silent

    async def chat(self, messages, *, system="", tools=None, temperature=0.7,
                   max_tokens=16384, on_chunk=None, on_activity=None, **kw):
        text = ""
        for _ in range(self.chunks):
            await asyncio.sleep(self.chunk_sleep)
            if not self.silent and on_activity is not None:
                on_activity()
            text += "chunk "
        return LLMResponse(content=text.strip())

    async def close(self):
        pass


class SilentSlowClient(LLMClient):
    """Sleeps longer than any reasonable heartbeat without any activity."""

    def __init__(self, sleep: float):
        self.sleep = sleep

    async def chat(self, messages, **kw):
        await asyncio.sleep(self.sleep)
        return LLMResponse(content="too late")

    async def close(self):
        pass


class PartialThenSuccessfulClient(LLMClient):
    """Fails after a visible chunk, then succeeds on the retry."""

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, *, on_chunk=None, **kw):
        self.calls += 1
        if self.calls == 1:
            if on_chunk:
                result = on_chunk("discarded partial ")
                if hasattr(result, "__await__"):
                    await result
            raise NetworkError("temporary disconnect")
        if on_chunk:
            result = on_chunk("final text")
            if hasattr(result, "__await__"):
                await result
        return LLMResponse(content="final text", stop_reason="end_turn")

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_stream_retry_passes_through_and_marks_interrupted_attempt(
        tmp_path, monkeypatch):
    """R12.x 流式直通：失败尝试的正文实时可见，重试前补一条中断标注。

    （旧行为：整次调用被缓冲到成功后一次性回放，UI 全程看不到正文。）
    """
    monkeypatch.setenv("RA_MAX_RETRIES", "1")
    monkeypatch.setenv("RA_RETRY_BASE_DELAY", "0")
    client = PartialThenSuccessfulClient()
    emitted: list[str] = []

    result = await run_agent(
        prompt="p", system_prompt="s", llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(auto_continue=False),
        on_text=emitted.append,
    )

    assert client.calls == 2
    # 失败尝试的 chunk 实时透传；重试开始前插入诚实的中断标注。
    assert emitted == [
        "discarded partial ",
        "\n\n[生成中断，正在自动重试…]\n\n",
        "final text",
    ]
    # collected_text 只含最终响应内容（流式 chunk 不重复计入）。
    assert result.text_output == "final text"


class FailBeforeFirstChunkClient(LLMClient):
    """首块之前就失败（连接/429 等最常见场景），重试后成功。"""

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, *, on_chunk=None, **kw):
        self.calls += 1
        if self.calls == 1:
            raise NetworkError("connection reset by peer")
        if on_chunk:
            result = on_chunk("hello")
            if hasattr(result, "__await__"):
                await result
        return LLMResponse(content="hello", stop_reason="end_turn")

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_stream_retry_before_first_chunk_is_silent(tmp_path, monkeypatch):
    """首块之前的失败依旧无痕重试：不插入中断标注、不重复内容。"""
    monkeypatch.setenv("RA_MAX_RETRIES", "1")
    monkeypatch.setenv("RA_RETRY_BASE_DELAY", "0")
    client = FailBeforeFirstChunkClient()
    emitted: list[str] = []

    await run_agent(
        prompt="p", system_prompt="s", llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(auto_continue=False),
        on_text=emitted.append,
    )

    assert client.calls == 2
    assert emitted == ["hello"]


class HangingStreamClient(LLMClient):
    """挂死在 LLM 调用中：供硬取消测试打断。"""

    async def chat(self, messages, **kw):
        await asyncio.Event().wait()

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_hard_cancel_releases_reservation_and_emits_run_end(tmp_path):
    """硬取消（task.cancel()）必须归还预算预留并尽力补发 RUN_END。

    （缺陷 A：CancelledError 是 BaseException 直接穿堂——预留永久滞留
    BudgetGuard、RUN_END 缺失。）
    """
    guard = BudgetGuard(BudgetLimits(), model="m")
    bus = HookBus()
    ended: list[dict] = []
    request_started = asyncio.Event()

    bus.on(EventKind.RUN_END, lambda e: ended.append(dict(e.payload)))
    bus.on(EventKind.LLM_REQUEST, lambda e: request_started.set())

    task = asyncio.create_task(run_agent(
        prompt="p", system_prompt="s", llm_client=HangingStreamClient(),
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(budget=guard, hooks=bus, auto_continue=False),
    ))
    try:
        await asyncio.wait_for(request_started.wait(), timeout=2.0)
        # 预留在途（LLM 调用挂死期间）
        assert guard.snapshot()["in_flight"] == 1

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()

    # 预留已归还，不再滞留共享预算
    snap = guard.snapshot()
    assert snap["in_flight"] == 0
    assert snap["reserved_tokens"] == 0
    # RUN_END 尽力补发，前端才能收尾
    assert len(ended) == 1
    assert ended[0]["stop_reason"] == "cancelled"


@pytest.mark.asyncio
async def test_healthy_slow_stream_survives_short_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setenv("RA_MAX_RETRIES", "0")
    # Total duration (~0.6s) exceeds the 0.25s window, but beats keep it alive.
    client = SlowStreamingClient(chunk_sleep=0.15, chunks=4)
    result = await run_agent(
        prompt="p", system_prompt="s", llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(auto_continue=False, heartbeat_timeout=0.25),
    )
    assert result.stop_reason == "completed"
    assert "chunk" in result.text_output


@pytest.mark.asyncio
async def test_silence_raises_heartbeat_quickly(tmp_path, monkeypatch):
    monkeypatch.setenv("RA_MAX_RETRIES", "0")
    monkeypatch.setenv("RA_RETRY_BASE_DELAY", "0.01")
    client = SilentSlowClient(sleep=1.0)
    start = time.monotonic()
    with pytest.raises(HeartbeatTimeoutError):
        await run_agent(
            prompt="p", system_prompt="s", llm_client=client,
            tools=ToolRegistry(work_dir=str(tmp_path)),
            config=RunConfig(auto_continue=False, heartbeat_timeout=0.2),
        )
    elapsed = time.monotonic() - start
    assert elapsed < 0.9, f"watchdog took {elapsed:.2f}s — not silence-based"
