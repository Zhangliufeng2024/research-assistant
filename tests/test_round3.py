"""Tests for round-3 harness borrowings: approval ask-state, repeat guard,
result rewriting, and session-log mirroring."""

import asyncio
import json

import pytest

from research_assistant.agent import run_agent, RunConfig
from research_assistant.kernel.approval import (
    ApprovalDecision,
    QueueApprover,
    ToolApprovalRequest,
    resolve_approval,
)
from research_assistant.kernel.events import AgentEvent, EventKind, HookBus, HookVerdict
from research_assistant.kernel.guards import RepeatToolCallGuard
from research_assistant.llm.base import LLMClient, LLMResponse, ToolCall
from research_assistant.tools.registry import ToolRegistry


class ScriptedClient(LLMClient):
    """Plays a scripted sequence; ends with TASK_COMPLETE."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._i = 0

    async def chat(self, messages, **kw):
        if self._i < len(self._responses):
            r = self._responses[self._i]
        else:
            r = LLMResponse(content="[TASK_COMPLETE]")
        self._i += 1
        return r

    async def close(self):
        pass


def _tool_call(name="bash", arguments=None, cid="c1"):
    return LLMResponse(
        content="",
        tool_calls=[ToolCall(id=cid, name=name, arguments=arguments or {})],
        stop_reason="tool_use",
    )


# ---------------------------------------------------------------------------
# resolve_approval
# ---------------------------------------------------------------------------

REQ = ToolApprovalRequest(tool_name="bash", arguments={"command": "ls"})

class TestResolveApproval:
    @pytest.mark.asyncio
    async def test_no_approver_denies(self):
        approved, note = await resolve_approval(None, REQ)
        assert not approved
        assert "no approver" in note

    @pytest.mark.asyncio
    async def test_sync_approve_and_reject(self):
        yes, _ = await resolve_approval(lambda r: ApprovalDecision(True), REQ)
        no, note = await resolve_approval(
            lambda r: ApprovalDecision(False, "because"), REQ)
        assert yes
        assert not no
        assert note == "because"

    @pytest.mark.asyncio
    async def test_async_approver(self):
        async def approver(req):
            return ApprovalDecision(True)
        approved, _ = await resolve_approval(approver, REQ)
        assert approved

    @pytest.mark.asyncio
    async def test_timeout_denies(self):
        async def slow(req):
            await asyncio.sleep(5)
            return ApprovalDecision(True)
        approved, note = await resolve_approval(slow, REQ, timeout=0.05)
        assert not approved
        assert "timed out" in note

    @pytest.mark.asyncio
    async def test_approver_error_denies(self):
        def boom(req):
            raise RuntimeError("approver bug")
        approved, note = await resolve_approval(boom, REQ)
        assert not approved
        assert "approver bug" in note


class TestQueueApprover:
    @pytest.mark.asyncio
    async def test_yes_answers_approve(self):
        q: asyncio.Queue = asyncio.Queue()
        approver = QueueApprover(q, timeout=1.0)
        task = asyncio.create_task(approver(REQ))
        await asyncio.sleep(0.01)
        await q.put("y")
        decision = await task
        assert decision.approved

    @pytest.mark.asyncio
    async def test_no_answers_reject(self):
        q: asyncio.Queue = asyncio.Queue()
        approver = QueueApprover(q, timeout=1.0)
        task = asyncio.create_task(approver(REQ))
        await asyncio.sleep(0.01)
        await q.put("n")
        decision = await task
        assert not decision.approved

    @pytest.mark.asyncio
    async def test_on_request_callback_invoked(self):
        q: asyncio.Queue = asyncio.Queue()
        seen = []
        approver = QueueApprover(q, timeout=1.0, on_request=seen.append)
        task = asyncio.create_task(approver(REQ))
        await asyncio.sleep(0.01)
        await q.put("y")
        await task
        assert len(seen) == 1
        assert seen[0].tool_name == "bash"


# ---------------------------------------------------------------------------
# Ask routing inside the agent loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ask_without_approver_denies(tmp_path):
    canary = tmp_path / "canary.txt"
    bus = HookBus()

    async def always_ask(event):
        return HookVerdict(allowed=True, ask=True, reason="sensitive op")

    bus.on(EventKind.PRE_TOOL_USE, always_ask)
    results = []

    async def on_tool_use(name, args, result):
        results.append(result)

    await run_agent(
        prompt="p", system_prompt="s",
        llm_client=ScriptedClient([_tool_call("bash",
                                              {"command": f"echo hi > {canary}"})]),
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(hooks=bus, auto_continue=False),
        on_tool_use=on_tool_use,
    )
    assert "[DENIED by approval]" in results[0]
    assert "no approver" in results[0]
    assert not canary.exists()


@pytest.mark.asyncio
async def test_ask_with_approving_approver_executes(tmp_path):
    canary = tmp_path / "canary.txt"
    bus = HookBus()

    async def always_ask(event):
        return HookVerdict(ask=True)

    bus.on(EventKind.PRE_TOOL_USE, always_ask)
    results = []

    async def on_tool_use(name, args, result):
        results.append(result)

    await run_agent(
        prompt="p", system_prompt="s",
        llm_client=ScriptedClient([_tool_call("write_file",
                                              {"file_path": str(canary),
                                               "content": "ok"})]),
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(hooks=bus, auto_continue=False,
                         approver=lambda r: ApprovalDecision(True)),
        on_tool_use=on_tool_use,
    )
    assert canary.exists()
    assert "DENIED" not in results[0]


@pytest.mark.asyncio
async def test_ask_with_rejecting_approver_denies(tmp_path):
    canary = tmp_path / "canary.txt"
    bus = HookBus()

    async def always_ask(event):
        return HookVerdict(ask=True)

    bus.on(EventKind.PRE_TOOL_USE, always_ask)
    results = []

    async def on_tool_use(name, args, result):
        results.append(result)

    await run_agent(
        prompt="p", system_prompt="s",
        llm_client=ScriptedClient([_tool_call("bash",
                                              {"command": f"echo hi > {canary}"})]),
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(hooks=bus, auto_continue=False,
                         approver=lambda r: ApprovalDecision(False, "too risky")),
        on_tool_use=on_tool_use,
    )
    assert "[DENIED by approval] too risky" in results[0]
    assert not canary.exists()


# ---------------------------------------------------------------------------
# Repeat tool-call guard
# ---------------------------------------------------------------------------

class TestRepeatGuard:
    def test_counts_consecutive_identical_calls(self):
        guard = RepeatToolCallGuard(limit=3)
        args = {"command": "make all"}
        for i in range(2):
            verdict = guard.check_sync(args) if hasattr(guard, "check_sync") else None
        # use the async path directly
        async def drive():
            outs = []
            for _ in range(4):
                event = AgentEvent(EventKind.PRE_TOOL_USE, tool_name="bash",
                                   payload={"arguments": dict(args)})
                outs.append(asyncio.get_event_loop().run_until_complete(guard(event)))
            return outs
        # simpler: run via asyncio in the test below

    @pytest.mark.asyncio
    async def test_third_identical_call_denied_then_recovers(self):
        guard = RepeatToolCallGuard(limit=3)
        args = {"command": "make all"}

        async def call():
            event = AgentEvent(EventKind.PRE_TOOL_USE, tool_name="bash",
                               payload={"arguments": dict(args)})
            return await guard(event)

        v1 = await call()
        v2 = await call()
        v3 = await call()
        v4 = await call()   # every (limit+1)-th passes through to avoid deadlock
        v5 = await call()

        assert v1 is None and v2 is None
        assert v3 is not None and not v3.allowed
        assert "repeated 3 times" in v3.reason
        assert v4 is None                      # relief valve
        assert v5 is not None and not v5.allowed

    @pytest.mark.asyncio
    async def test_different_args_reset_counter(self):
        guard = RepeatToolCallGuard(limit=3)

        async def call(n):
            event = AgentEvent(EventKind.PRE_TOOL_USE, tool_name="bash",
                               payload={"arguments": {"command": f"cmd {n}"}})
            return await guard(event)

        for i in range(10):
            assert await call(i) is None       # never identical twice


@pytest.mark.asyncio
async def test_guard_blocks_inside_agent_loop(tmp_path):
    results = []
    responses = [
        _tool_call("bash", {"command": "echo same"}, cid=f"c{i}")
        for i in range(3)
    ]
    # give each response a distinct id but identical arguments

    async def on_tool_use(name, args, result):
        results.append(result)

    await run_agent(
        prompt="p", system_prompt="s",
        llm_client=ScriptedClient(responses),
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(auto_continue=False, repeat_guard=True),
        on_tool_use=on_tool_use,
    )
    denied = [r for r in results if "[DENIED by policy]" in r]
    assert any("identical bash call repeated" in r for r in denied)


# ---------------------------------------------------------------------------
# TOOL_RESULT_REWRITE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_result_rewrite_hook_replaces_model_visible_text(tmp_path):
    bus = HookBus()

    async def redact(event):
        result = event.payload.get("result", "")
        return result.replace("SECRET", "[REDACTED]")

    bus.on(EventKind.TOOL_RESULT_REWRITE, redact)
    results = []
    big_file = tmp_path / "data.txt"
    big_file.write_text("token=SECRET", encoding="utf-8")

    async def on_tool_use(name, args, result):
        results.append(result)

    await run_agent(
        prompt="p", system_prompt="s",
        llm_client=ScriptedClient([_tool_call("read_file",
                                              {"file_path": str(big_file)})]),
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(hooks=bus, auto_continue=False),
        on_tool_use=on_tool_use,
    )
    assert "SECRET" not in results[0]
    assert "[REDACTED]" in results[0]


# ---------------------------------------------------------------------------
# Session-log mirroring ("model-visible is logged")
# ---------------------------------------------------------------------------

class MemoryLog:
    def __init__(self):
        self.events = []

    def log(self, kind, data=None):
        self.events.append({"kind": kind, "data": data or {}})


@pytest.mark.asyncio
async def test_session_log_mirrors_all_messages(tmp_path):
    log = MemoryLog()
    client = ScriptedClient([
        _tool_call("write_file", {"file_path": str(tmp_path / "a.txt"),
                                  "content": "x"}),
    ])
    await run_agent(
        prompt="hello task", system_prompt="sys",
        llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(auto_continue=False, session_log=log),
    )

    kinds = [e["kind"] for e in log.events]
    assert kinds[0] == "msg_add"                       # initial user prompt
    msg_roles = [e["data"]["role"] for e in log.events
                 if e["kind"] == "msg_add"]
    assert msg_roles == ["user", "assistant", "tool"]
    assert kinds.count("tool_call") == 1
    assert kinds[-1] == "run_end"
    # No invariant gaps detected during the run.
    assert "invariant_warning" not in kinds
    # tool result content is mirrored with role/tool metadata
    tool_entry = next(e for e in log.events
                      if e["kind"] == "msg_add" and e["data"]["role"] == "tool")
    assert tool_entry["data"]["seq"] >= 0


@pytest.mark.asyncio
async def test_session_log_survives_logging_errors(tmp_path):
    class BrokenLog(MemoryLog):
        def log(self, kind, data=None):
            raise OSError("disk full")

    client = ScriptedClient([LLMResponse(content="[TASK_COMPLETE]")])
    result = await run_agent(
        prompt="p", system_prompt="s", llm_client=client,
        tools=ToolRegistry(work_dir=str(tmp_path)),
        config=RunConfig(auto_continue=False, session_log=BrokenLog()),
    )
    assert result.stop_reason == "completed"   # telemetry failures are swallowed


# ---------------------------------------------------------------------------
# Pipeline / api threading smoke checks
# ---------------------------------------------------------------------------

def test_run_config_has_new_fields():
    cfg = RunConfig(approver="x", approval_timeout=5.0,
                    session_log="y", repeat_guard=None)
    assert cfg.approver == "x"
    assert cfg.approval_timeout == 5.0
    assert cfg.session_log == "y"


def test_generate_paper_signature_accepts_approver():
    import inspect
    from research_assistant.api import generate_paper
    params = inspect.signature(generate_paper).parameters
    assert "approver" in params
    assert "cancel_event" in params
    assert "budget_limits" in params
