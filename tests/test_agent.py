"""Tests for research_assistant.agent — custom agentic loop."""

import asyncio

import pytest

from research_assistant.agent import AgentResult, _accumulate_usage, _is_completion_loop, run_agent
from research_assistant.constants import TASK_COMPLETE_MARKER
from research_assistant.llm.base import LLMClient, LLMResponse, ToolCall
from research_assistant.models import TokenUsage
from research_assistant.tools.registry import ToolRegistry


class MockLLMClient(LLMClient):
    """Mock LLM client that returns pre-configured responses."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self._call_count = 0

    async def chat(self, messages, *, system="", tools=None, temperature=0.7, max_tokens=16384, on_chunk=None):
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
            self._call_count += 1
        else:
            resp = LLMResponse(content="Done.", stop_reason="end_turn")
        if on_chunk and resp.content:
            result = on_chunk(resp.content)
            if asyncio.iscoroutine(result):
                await result
        return resp

    async def close(self):
        pass


class TestAccumulateUsage:
    def test_accumulates_tokens(self):
        total = TokenUsage()
        resp = LLMResponse(usage=TokenUsage(input_tokens=100, output_tokens=50))
        _accumulate_usage(total, resp)
        assert total.input_tokens == 100
        assert total.output_tokens == 50

        resp2 = LLMResponse(usage=TokenUsage(input_tokens=200, output_tokens=100))
        _accumulate_usage(total, resp2)
        assert total.input_tokens == 300
        assert total.output_tokens == 150


class TestRunAgent:
    @pytest.mark.asyncio
    async def test_simple_text_response(self):
        client = MockLLMClient([
            LLMResponse(content="Hello!", stop_reason="end_turn"),
        ])
        tools = ToolRegistry()

        result = await run_agent(
            prompt="Hi",
            system_prompt="You are helpful.",
            llm_client=client,
            tools=tools,
            auto_continue=False,
        )

        assert result.success
        assert "Hello!" in result.text_output

    @pytest.mark.asyncio
    async def test_tool_call_then_response(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world")

        client = MockLLMClient([
            LLMResponse(
                content="Let me read that file.",
                tool_calls=[ToolCall(id="tc_1", name="read_file", arguments={"file_path": str(test_file)})],
                stop_reason="tool_use",
            ),
            LLMResponse(content="The file contains 'hello world'.", stop_reason="end_turn"),
        ])
        tools = ToolRegistry(work_dir=str(tmp_path))

        result = await run_agent(
            prompt="Read test.txt",
            system_prompt="You are helpful.",
            llm_client=client,
            tools=tools,
            auto_continue=False,
        )

        assert result.success
        assert "hello world" in result.text_output

    @pytest.mark.asyncio
    async def test_auto_continue(self):
        client = MockLLMClient([
            LLMResponse(content="Part 1.", stop_reason="end_turn"),
            LLMResponse(content="Part 2.", stop_reason="end_turn"),
        ])
        tools = ToolRegistry()

        result = await run_agent(
            prompt="Generate content",
            system_prompt="You are helpful.",
            llm_client=client,
            tools=tools,
            auto_continue=True,
            max_continuations=1,
        )

        assert result.success
        assert "Part 1." in result.text_output

    @pytest.mark.asyncio
    async def test_max_tokens_continues(self):
        client = MockLLMClient([
            LLMResponse(content="Partial...", stop_reason="max_tokens"),
            LLMResponse(content="...complete.", stop_reason="end_turn"),
        ])
        tools = ToolRegistry()

        result = await run_agent(
            prompt="Write a long text",
            system_prompt="",
            llm_client=client,
            tools=tools,
            auto_continue=False,
        )

        assert result.success
        assert "Partial..." in result.text_output
        assert "...complete." in result.text_output

    @pytest.mark.asyncio
    async def test_text_callback(self):
        client = MockLLMClient([
            LLMResponse(content="Hello callback!", stop_reason="end_turn"),
        ])
        tools = ToolRegistry()
        collected = []

        async def on_text(text):
            collected.append(text)

        await run_agent(
            prompt="Hi",
            system_prompt="",
            llm_client=client,
            tools=tools,
            auto_continue=False,
            on_text=on_text,
        )

        assert "Hello callback!" in collected

    @pytest.mark.asyncio
    async def test_tool_callback(self, tmp_path):
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        client = MockLLMClient([
            LLMResponse(
                tool_calls=[ToolCall(id="tc_1", name="read_file", arguments={"file_path": str(test_file)})],
                stop_reason="tool_use",
            ),
            LLMResponse(content="Done.", stop_reason="end_turn"),
        ])
        tools = ToolRegistry(work_dir=str(tmp_path))
        tool_log = []

        async def on_tool(name, args, result):
            tool_log.append((name, args))

        await run_agent(
            prompt="Read file",
            system_prompt="",
            llm_client=client,
            tools=tools,
            auto_continue=False,
            on_tool_use=on_tool,
        )

        assert len(tool_log) == 1
        assert tool_log[0][0] == "read_file"

    @pytest.mark.asyncio
    async def test_token_tracking(self):
        client = MockLLMClient([
            LLMResponse(
                content="Hello!",
                stop_reason="end_turn",
                usage=TokenUsage(input_tokens=100, output_tokens=50),
            ),
        ])
        tools = ToolRegistry()

        result = await run_agent(
            prompt="Hi",
            system_prompt="",
            llm_client=client,
            tools=tools,
            auto_continue=False,
        )

        assert result.token_usage.input_tokens == 100
        assert result.token_usage.output_tokens == 50


class TestSteerInjection:
    @pytest.mark.asyncio
    async def test_steer_replaces_auto_continue(self):
        """When steer is queued, it replaces the 'Continue.' message."""
        messages_seen = []

        class CapturingClient(LLMClient):
            def __init__(self):
                self._call_count = 0

            async def chat(self, messages, **kwargs):
                self._call_count += 1
                messages_seen.append([m.copy() for m in messages])
                if self._call_count <= 2:
                    return LLMResponse(content="Working...", stop_reason="end_turn")
                return LLMResponse(content="Done.", stop_reason="end_turn")

            async def close(self):
                pass

        steer_queue = asyncio.Queue()
        await steer_queue.put("focus on methods")

        steers_received = []
        await run_agent(
            prompt="Write a paper",
            system_prompt="",
            llm_client=CapturingClient(),
            tools=ToolRegistry(),
            auto_continue=True,
            max_continuations=2,
            steer_queue=steer_queue,
            on_steer_injected=lambda s: steers_received.append(s),
        )

        assert len(steers_received) >= 1
        assert "focus on methods" in steers_received[0]

    @pytest.mark.asyncio
    async def test_no_steer_sends_continue(self):
        """Without steer, auto-continue sends 'Continue.' as before."""
        messages_seen = []

        class CapturingClient(LLMClient):
            def __init__(self):
                self._call_count = 0

            async def chat(self, messages, **kwargs):
                self._call_count += 1
                messages_seen.append([m.copy() for m in messages])
                if self._call_count == 1:
                    return LLMResponse(content="Part 1.", stop_reason="end_turn")
                return LLMResponse(content="Done.", stop_reason="end_turn")

            async def close(self):
                pass

        await run_agent(
            prompt="Write",
            system_prompt="",
            llm_client=CapturingClient(),
            tools=ToolRegistry(),
            auto_continue=True,
            max_continuations=1,
            steer_queue=asyncio.Queue(),
        )

        second_call_msgs = messages_seen[1]
        user_msgs = [m for m in second_call_msgs if m["role"] == "user"]
        assert any("Continue." in m["content"] for m in user_msgs)

    @pytest.mark.asyncio
    async def test_no_steer_queue_unchanged_behavior(self):
        """Passing steer_queue=None preserves existing behavior exactly."""
        client = MockLLMClient([
            LLMResponse(content="Hello!", stop_reason="end_turn"),
        ])
        result = await run_agent(
            prompt="Hi",
            system_prompt="",
            llm_client=client,
            tools=ToolRegistry(),
            auto_continue=False,
            steer_queue=None,
        )
        assert result.success
        assert "Hello!" in result.text_output

    @pytest.mark.asyncio
    async def test_tool_start_callback(self, tmp_path):
        """on_tool_start fires before tool execution."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        client = MockLLMClient([
            LLMResponse(
                tool_calls=[ToolCall(id="tc_1", name="read_file", arguments={"file_path": str(test_file)})],
                stop_reason="tool_use",
            ),
            LLMResponse(content="Done.", stop_reason="end_turn"),
        ])
        tools = ToolRegistry(work_dir=str(tmp_path))
        starts = []

        async def on_start(name, args):
            starts.append(name)

        await run_agent(
            prompt="Read file",
            system_prompt="",
            llm_client=client,
            tools=tools,
            auto_continue=False,
            on_tool_start=on_start,
        )

        assert starts == ["read_file"]

    @pytest.mark.asyncio
    async def test_turn_start_callback(self):
        """on_turn_start fires at the beginning of each turn."""
        client = MockLLMClient([
            LLMResponse(content="Hello!", stop_reason="end_turn"),
        ])
        turns = []

        async def on_turn(turn, elapsed, usage):
            turns.append(turn)

        await run_agent(
            prompt="Hi",
            system_prompt="",
            llm_client=client,
            tools=ToolRegistry(),
            auto_continue=False,
            on_turn_start=on_turn,
        )

        assert turns == [1]


class TestCompletionDetection:
    def test_is_completion_loop_empty(self):
        assert not _is_completion_loop([])

    def test_is_completion_loop_single(self):
        assert not _is_completion_loop(["Task is done."])

    def test_is_completion_loop_different_messages(self):
        assert not _is_completion_loop([
            "Writing the introduction section now.",
            "Moving on to the methodology section.",
        ])

    def test_is_completion_loop_similar_messages(self):
        assert _is_completion_loop([
            "The task is complete. All files have been created and saved.",
            "The task is complete. All files have been created and delivered.",
        ])

    def test_is_completion_loop_identical_messages(self):
        assert _is_completion_loop([
            "Done! The paper has been written.",
            "Done! The paper has been written.",
        ])

    @pytest.mark.asyncio
    async def test_task_complete_marker_stops_loop(self):
        """Agent stops immediately when LLM outputs [TASK_COMPLETE]."""
        client = MockLLMClient([
            LLMResponse(
                content=f"All done. {TASK_COMPLETE_MARKER}",
                stop_reason="end_turn",
            ),
        ])
        tools = ToolRegistry()

        result = await run_agent(
            prompt="Write something",
            system_prompt="",
            llm_client=client,
            tools=tools,
            auto_continue=True,
            max_continuations=10,
        )

        assert result.success
        assert result.turns == 1

    @pytest.mark.asyncio
    async def test_repeat_detection_stops_loop(self):
        """Agent stops when LLM repeats similar completion messages."""
        client = MockLLMClient([
            LLMResponse(content="The paper is finished. All sections written.", stop_reason="end_turn"),
            LLMResponse(content="The paper is finished. All sections delivered.", stop_reason="end_turn"),
        ])
        tools = ToolRegistry()

        result = await run_agent(
            prompt="Write a paper",
            system_prompt="",
            llm_client=client,
            tools=tools,
            auto_continue=True,
            max_continuations=10,
        )

        assert result.success
        assert result.turns == 2

    @pytest.mark.asyncio
    async def test_tool_calls_reset_repeat_tracker(self):
        """Tool call activity clears the repeat tracker so work continues."""
        test_calls = []

        class WorkingClient(LLMClient):
            def __init__(self):
                self._call_count = 0

            async def chat(self, messages, **kwargs):
                self._call_count += 1
                test_calls.append(self._call_count)
                if self._call_count == 1:
                    return LLMResponse(content="Starting work.", stop_reason="end_turn")
                if self._call_count == 2:
                    return LLMResponse(
                        tool_calls=[ToolCall(id="tc_1", name="run_python", arguments={"code": "print('hi')"})],
                        stop_reason="tool_use",
                    )
                return LLMResponse(
                    content=f"All done. {TASK_COMPLETE_MARKER}",
                    stop_reason="end_turn",
                )

            async def close(self):
                pass

        result = await run_agent(
            prompt="Do work",
            system_prompt="",
            llm_client=WorkingClient(),
            tools=ToolRegistry(),
            auto_continue=True,
            max_continuations=5,
        )

        assert result.success
        assert len(test_calls) == 3


class TestAgentResult:
    def test_defaults(self):
        r = AgentResult()
        assert r.success
        assert r.text_output == ""
        assert r.files_written == []
        assert r.error is None
        assert r.turns == 0
