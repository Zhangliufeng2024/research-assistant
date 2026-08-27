"""Tests for research_assistant.kernel — events, budget, context management."""

import pytest

from research_assistant.kernel.budget import (
    BudgetExceededError,
    BudgetGuard,
    BudgetLimits,
    price_for,
)
from research_assistant.kernel.context import (
    externalize_tool_result,
    find_cut_point,
    maybe_compact,
    window_for,
)
from research_assistant.kernel.events import AgentEvent, EventKind, HookBus, HookVerdict
from research_assistant.llm.base import LLMClient, LLMResponse
from research_assistant.models import TokenUsage

# ---------------------------------------------------------------------------
# HookBus
# ---------------------------------------------------------------------------

class TestHookBus:
    @pytest.mark.asyncio
    async def test_sync_and_async_handlers_receive_events(self):
        bus = HookBus()
        seen = []

        def sync_handler(event):
            seen.append(("sync", event.kind))

        async def async_handler(event):
            seen.append(("async", event.kind))

        bus.on(EventKind.TURN_START, sync_handler)
        bus.on(EventKind.TURN_START, async_handler)
        verdict = await bus.emit(AgentEvent(EventKind.TURN_START, turn=1))

        assert verdict.allowed
        assert ("sync", EventKind.TURN_START) in seen
        assert ("async", EventKind.TURN_START) in seen

    @pytest.mark.asyncio
    async def test_pre_tool_use_deny_short_circuits(self):
        bus = HookBus()

        async def deny_all(event):
            return HookVerdict(allowed=False, reason="blocked by test")

        bus.on(EventKind.PRE_TOOL_USE, deny_all)
        verdict = await bus.emit(
            AgentEvent(EventKind.PRE_TOOL_USE, tool_name="bash", payload={"arguments": {}})
        )
        assert not verdict.allowed
        assert verdict.reason == "blocked by test"

    @pytest.mark.asyncio
    async def test_handler_exception_does_not_crash_emit(self):
        bus = HookBus()

        def boom(event):
            raise RuntimeError("hook bug")

        bus.on(EventKind.RUN_END, boom)
        verdict = await bus.emit(AgentEvent(EventKind.RUN_END))
        assert verdict.allowed

    @pytest.mark.asyncio
    async def test_off_removes_handler(self):
        bus = HookBus()
        seen = []

        def handler(event):
            seen.append(event)

        bus.on(EventKind.ERROR, handler)
        bus.off(EventKind.ERROR, handler)
        await bus.emit(AgentEvent(EventKind.ERROR))
        assert not seen


# ---------------------------------------------------------------------------
# BudgetGuard
# ---------------------------------------------------------------------------

def _resp(inp=0, out=0, cw=0, cr=0):
    return LLMResponse(usage=TokenUsage(
        input_tokens=inp, output_tokens=out,
        cache_creation_input_tokens=cw, cache_read_input_tokens=cr,
    ))


class TestBudget:
    def test_price_prefix_match(self):
        assert price_for("claude-sonnet-5")["input"] == 3.0
        assert price_for("gpt-4o-mini-2024")["output"] == 0.60
        assert price_for("totally-unknown-model")["input"] == 0.0

    def test_cost_accumulation_uses_cache_prices(self):
        guard = BudgetGuard(BudgetLimits(), model="claude-sonnet-5")
        guard.record(_resp(inp=1_000_000, out=100_000, cw=500_000, cr=250_000))
        expected = (1_000_000 * 3.0 + 100_000 * 15.0 + 500_000 * 3.75 + 250_000 * 0.30) / 1e6
        assert abs(guard.state.cost_usd - expected) < 1e-9

    def test_no_limits_never_raises(self):
        guard = BudgetGuard(BudgetLimits(), model="m")
        for _ in range(50):
            guard.record(_resp(out=10_000))
        guard.check()  # should not raise

    def test_turn_limit_raises(self):
        guard = BudgetGuard(BudgetLimits(max_turns=2), model="m")
        guard.record(_resp())
        guard.check()
        guard.record(_resp())
        with pytest.raises(BudgetExceededError, match="turn limit"):
            guard.check()

    def test_token_limit_raises(self):
        guard = BudgetGuard(BudgetLimits(max_total_tokens=100), model="m")
        guard.record(_resp(inp=60, out=60))
        with pytest.raises(BudgetExceededError, match="token limit"):
            guard.check()

    def test_cost_limit_raises(self):
        guard = BudgetGuard(BudgetLimits(max_cost_usd=0.001), model="claude-sonnet-5")
        guard.record(_resp(inp=10_000_000))
        with pytest.raises(BudgetExceededError, match="cost limit"):
            guard.check()

    def test_warning_at_80_percent(self):
        guard = BudgetGuard(BudgetLimits(max_total_tokens=1000), model="m")
        guard.record(_resp(inp=850))
        verdict = guard.check()
        assert verdict.ok
        assert any("tokens" in w for w in verdict.warnings)
        # warning fires only once
        verdict2 = guard.check()
        assert not any("tokens" in w for w in verdict2.warnings)

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("RA_MAX_COST_USD", "5")
        monkeypatch.setenv("RA_MAX_TURNS", "40")
        limits = BudgetLimits.from_env()
        assert limits.max_cost_usd == 5.0
        assert limits.max_turns == 40

    def test_snapshot_shape(self):
        guard = BudgetGuard(BudgetLimits(max_turns=9), model="deepseek-chat")
        guard.record(_resp(inp=100, out=10))
        snap = guard.snapshot()
        assert snap["model"] == "deepseek-chat"
        assert snap["total_tokens"] == 110
        assert snap["limits"]["max_turns"] == 9

    def test_cost_cap_enforceable_flag(self):
        # 已知价格 + 设了成本上限 → 可执行
        g1 = BudgetGuard(BudgetLimits(max_cost_usd=5), model="claude-sonnet-5")
        assert g1.snapshot()["cost_cap_enforceable"] is True
        # 未知价格 + 设了成本上限 → 如实上报不可执行（token 等其它上限不受影响）
        g2 = BudgetGuard(BudgetLimits(max_cost_usd=5), model="agnes-2.0-flash")
        assert g2.snapshot()["cost_cap_enforceable"] is False
        # 未设成本上限 → 无所谓可不可执行，恒为 True
        g3 = BudgetGuard(model="agnes-2.0-flash")
        assert g3.snapshot()["cost_cap_enforceable"] is True

    def test_reservations_make_turn_limit_atomic(self):
        guard = BudgetGuard(BudgetLimits(max_turns=1), model="m")
        reservation = guard.reserve(max_output_tokens=10)
        with pytest.raises(BudgetExceededError, match="turn limit"):
            guard.reserve(max_output_tokens=10)
        guard.release(reservation)
        assert guard.snapshot()["in_flight"] == 0

    def test_reservations_share_remaining_token_capacity(self):
        guard = BudgetGuard(BudgetLimits(max_total_tokens=100), model="m")
        first = guard.reserve(max_output_tokens=70, estimated_input_tokens=10)
        second = guard.reserve(max_output_tokens=70, estimated_input_tokens=10)
        assert first.max_output_tokens == 70
        assert second.max_output_tokens == 10
        assert guard.snapshot()["reserved_tokens"] == 100
        with pytest.raises(BudgetExceededError, match="token limit"):
            guard.reserve(max_output_tokens=1)
        guard.release(first)
        guard.release(second)

    def test_set_model_refreshes_pricing(self):
        guard = BudgetGuard(BudgetLimits(max_cost_usd=5), model="unknown")
        assert guard.cost_cap_enforceable is False
        guard.set_model("claude-sonnet-5")
        assert guard.prices["output"] == 15.0
        assert guard.cost_cap_enforceable is True


# ---------------------------------------------------------------------------
# Context management
# ---------------------------------------------------------------------------

class TestExternalize:
    def test_small_result_passthrough(self, tmp_path):
        r = externalize_tool_result("short", "grep_search", 1, tmp_path)
        assert r == "short"
        assert list(tmp_path.iterdir()) == []

    def test_large_result_written_with_pointer(self, tmp_path):
        big = "x" * 10_000
        out = externalize_tool_result(big, "read_file", 7, tmp_path)
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "turn_0007_read_file.txt"
        assert files[0].read_text(encoding="utf-8") == big
        assert "turn_0007_read_file.txt" in out
        assert len(out) < 2_000


def _tool_exchange(i):
    """One assistant tool_calls message followed by its tool result."""
    return [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": f"c{i}", "name": "bash", "arguments": {"command": f"cmd{i}"}}
        ]},
        {"role": "tool", "tool_call_id": f"c{i}", "content": f"result {i}"},
    ]


def _long_history(n_exchanges=30):
    msgs = [{"role": "user", "content": "write a paper"}]
    for i in range(n_exchanges):
        msgs.extend(_tool_exchange(i))
    msgs.append({"role": "assistant", "content": "working on it"})
    return msgs


class TestCutPoint:
    def test_tail_never_starts_on_tool_result(self):
        msgs = _long_history()
        cut = find_cut_point(msgs, keep_recent=12)
        assert cut > 0
        tail = msgs[cut:]
        assert tail[0]["role"] != "tool"

    def test_no_orphaned_tool_calls_before_cut(self):
        msgs = _long_history()
        cut = find_cut_point(msgs, keep_recent=12)
        if cut > 0:
            prev = msgs[cut - 1]
            assert not prev.get("tool_calls")

    def test_too_short_history_returns_zero(self):
        msgs = [{"role": "user", "content": "hi"}] + _tool_exchange(0)
        assert find_cut_point(msgs, keep_recent=12) == 0


class _SummarizerClient(LLMClient):
    """Returns a canned (incrementing) summary and records prompts it was given."""

    def __init__(self):
        self.prompts: list[str] = []
        self._n = 0

    async def chat(self, messages, *, system="", tools=None, temperature=0.7,
                   max_tokens=16384, on_chunk=None):
        self._n += 1
        self.prompts.append(messages[-1]["content"])
        return LLMResponse(
            content=(
                "## Goal\nWrite paper.\n## Current State & Next Steps\nKeep going.\n"
                f"(summary #{self._n})"
            )
        )

    async def close(self):
        pass


class TestMaybeCompact:
    @pytest.mark.asyncio
    async def test_below_trigger_is_noop(self):
        client = _SummarizerClient()
        msgs = _long_history(5)
        out, compacted, _info = await maybe_compact(
            msgs, llm_client=client, model="claude-sonnet-5",
        )
        assert not compacted
        assert out is msgs
        assert client.prompts == []

    @pytest.mark.asyncio
    async def test_compaction_preserves_head_and_tool_pairing(self):
        client = _SummarizerClient()
        msgs = _long_history(40)
        original_first = dict(msgs[0])
        # Force trigger via measured tokens.
        out, compacted, _info = await maybe_compact(
            msgs, llm_client=client, model="claude-sonnet-5",
            last_input_tokens=190_000,
        )
        assert compacted
        # Original opening prompt untouched.
        assert out[0] == original_first
        # Summary block present at index 1.
        assert "[CONTEXT SUMMARY" in str(out[1]["content"])
        # Tail is pairing-safe.
        assert out[2]["role"] != "tool"
        for i, m in enumerate(out):
            if m.get("tool_calls"):
                ids = {tc["id"] for tc in m["tool_calls"]}
                following = [x.get("tool_call_id") for x in out[i + 1:i + 3]]
                assert ids.issubset(set(following)), "orphaned tool_call found"

    @pytest.mark.asyncio
    async def test_repeated_compaction_replaces_summary(self):
        client = _SummarizerClient()
        msgs = _long_history(40)
        await maybe_compact(msgs, llm_client=client, model="m", last_input_tokens=190_000)
        first_summary = str(msgs[1]["content"])
        # Grow well past the minimum span again, then recompact.
        for j in range(20):
            msgs.extend(_tool_exchange(100 + j))
        msgs.append({"role": "assistant", "content": "still going"})
        _, compacted_again, _info2 = await maybe_compact(
            msgs, llm_client=client, model="m", last_input_tokens=190_000,
        )
        assert compacted_again
        assert str(msgs[1]["content"]) != first_summary
        # Only one summary block at index 1 — no nesting.
        assert sum("[CONTEXT SUMMARY" in str(m.get("content", "")) for m in msgs) == 1


class _RecordingBudget:
    """计量桩：record() 收到的响应用量记下来。"""

    def __init__(self):
        self.recorded: list[LLMResponse] = []

    def record(self, response):
        self.recorded.append(response)


class TestCompactionMetering:
    """缺陷 I：压缩用的 summarize_span 调用本身也要计入预算计量。"""

    @pytest.mark.asyncio
    async def test_summarize_span_records_into_budget(self):
        from research_assistant.kernel.context import summarize_span

        client = _SummarizerClient()
        budget = _RecordingBudget()

        await summarize_span(client, "span text", budget=budget)

        assert len(budget.recorded) == 1
        assert client.prompts == ["span text"]

    @pytest.mark.asyncio
    async def test_summarize_span_without_budget_still_works(self):
        from research_assistant.kernel.context import summarize_span

        client = _SummarizerClient()
        summary = await summarize_span(client, "span text")
        assert "## Goal" in summary

    @pytest.mark.asyncio
    async def test_maybe_compact_passes_budget_through(self):
        client = _SummarizerClient()
        budget = _RecordingBudget()
        msgs = _long_history(40)

        await maybe_compact(
            msgs, llm_client=client, model="claude-sonnet-5",
            last_input_tokens=190_000, budget=budget,
        )

        assert len(budget.recorded) == 1


class TestWindowFor:
    def test_known_models(self):
        assert window_for("claude-sonnet-5") == 200_000
        assert window_for("gpt-4o") == 128_000
        assert window_for("deepseek-chat") == 128_000

    def test_unknown_model_default(self):
        assert window_for("mystery-model") == 128_000
