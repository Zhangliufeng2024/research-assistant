"""Tests for agent-loop kernel integration: hooks, budget, cancel, heartbeat."""

import asyncio
import time

import pytest

from research_assistant.agent import run_agent, RunConfig
from research_assistant.kernel.events import EventKind, HookBus, HookVerdict
from research_assistant.kernel.budget import BudgetGuard, BudgetLimits
from research_assistant.llm.base import LLMClient, LLMResponse
from research_assistant.llm.errors import HeartbeatTimeoutError
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


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_budget_exceeded_stops_gracefully(tmp_path):
    guard = BudgetGuard(BudgetLimits(max_turns=1), model="claude-sonnet-4-6")
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
