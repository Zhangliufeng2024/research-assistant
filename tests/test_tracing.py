"""G-6 执行链路 tracing 回归：HookBus 事件 → JSONL span 流。

被测实现 ``research_assistant/kernel/tracing.py``：
- TraceRecorder：LLM_REQUEST→LLM_RESPONSE 按 turn 配对、TOOL_START→
  TOOL_END 按 (turn, tool_name) FIFO 配对，结束行回填 duration_ms；
- JSONL 每行可独立解析，必含 ts / event / turn 字段；
- RA_TRACE_DIR 未设置时零开销（不注册 handler、不产生文件）；
- 异常路径（只发 ERROR 不发 RUN_END）也有 run_end 收尾记录。
"""

import json
from pathlib import Path

import pytest

from research_assistant.kernel.events import AgentEvent, EventKind, HookBus
from research_assistant.kernel.tracing import (
    attach_tracing,
    maybe_attach_tracing,
    trace_path_from_env,
)


def _read_lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _make_recorder(tmp_path: Path):
    bus = HookBus()
    path = tmp_path / "trace.jsonl"
    attach_tracing(bus, path)
    return bus, path


class TestSpanPairing:
    async def test_llm_request_response_paired_with_duration(self, tmp_path):
        bus, path = _make_recorder(tmp_path)
        await bus.emit(AgentEvent(EventKind.RUN_START, payload={"prompt_chars": 5}))
        await bus.emit(AgentEvent(EventKind.LLM_REQUEST, turn=1,
                                  payload={"messages": 3}, ts=1000.0))
        await bus.emit(AgentEvent(EventKind.LLM_RESPONSE, turn=1,
                                  payload={"stop_reason": "end_turn"}, ts=1002.5))
        lines = _read_lines(path)
        resp = lines[-1]
        assert resp["event"] == "llm_response"
        assert resp["turn"] == 1
        assert resp["duration_ms"] == pytest.approx(2500.0)

    async def test_tool_start_end_fifo_pairing(self, tmp_path):
        bus, path = _make_recorder(tmp_path)
        # 同回合同名工具两次调用：按 FIFO 与各自的 START 配对
        await bus.emit(AgentEvent(EventKind.TOOL_START, turn=2, tool_name="bash",
                                  payload={}, ts=10.0))
        await bus.emit(AgentEvent(EventKind.TOOL_START, turn=2, tool_name="bash",
                                  payload={}, ts=11.0))
        await bus.emit(AgentEvent(EventKind.TOOL_END, turn=2, tool_name="bash",
                                  payload={"result_chars": 12}, ts=12.0))
        await bus.emit(AgentEvent(EventKind.TOOL_END, turn=2, tool_name="bash",
                                  payload={"result_chars": 8}, ts=14.5))
        lines = _read_lines(path)
        durations = [r["duration_ms"] for r in lines if r["event"] == "tool_end"]
        assert durations[0] == pytest.approx(2000.0)  # 10→12
        assert durations[1] == pytest.approx(3500.0)  # 11→14.5

    async def test_unpaired_end_has_no_duration(self, tmp_path):
        bus, path = _make_recorder(tmp_path)
        await bus.emit(AgentEvent(EventKind.LLM_RESPONSE, turn=1, payload={}, ts=5.0))
        lines = _read_lines(path)
        assert "duration_ms" not in lines[-1]


class TestJsonlContract:
    async def test_full_run_sequence_parseable_and_ordered(self, tmp_path):
        bus, path = _make_recorder(tmp_path)
        await bus.emit(AgentEvent(EventKind.RUN_START, payload={"prompt_chars": 9}, ts=1.0))
        await bus.emit(AgentEvent(EventKind.TURN_START, turn=1, ts=1.1))
        await bus.emit(AgentEvent(EventKind.LLM_REQUEST, turn=1,
                                  payload={"messages": 2}, ts=1.2))
        await bus.emit(AgentEvent(EventKind.LLM_RESPONSE, turn=1,
                                  payload={"stop_reason": "tool_use"}, ts=1.5))
        await bus.emit(AgentEvent(EventKind.PRE_TOOL_USE, turn=1, tool_name="bash",
                                  payload={"arguments": {"command": "ls" * 400}}, ts=1.6))
        await bus.emit(AgentEvent(EventKind.TOOL_START, turn=1, tool_name="bash",
                                  payload={}, ts=1.7))
        await bus.emit(AgentEvent(EventKind.TOOL_END, turn=1, tool_name="bash",
                                  payload={"result_chars": 30}, ts=1.8))
        await bus.emit(AgentEvent(EventKind.RUN_END, turn=0,
                                  payload={"stop_reason": "completed", "turns": 1}, ts=2.0))
        lines = _read_lines(path)
        # 每行独立可解析，公共字段齐备
        for line in lines:
            assert isinstance(line["ts"], float)
            assert isinstance(line["event"], str)
            assert "turn" in line
        assert [r["event"] for r in lines] == [
            "run_start", "turn_start", "llm_request", "llm_response",
            "pre_tool_use", "tool_start", "tool_end", "run_end",
        ]
        # 载荷摘要：超长字符串被截断，不刷爆文件
        pre = next(r for r in lines if r["event"] == "pre_tool_use")
        assert len(pre["payload"]["arguments"]) <= 300

    async def test_error_without_run_end_still_writes_run_end(self, tmp_path):
        bus, path = _make_recorder(tmp_path)
        await bus.emit(AgentEvent(EventKind.RUN_START, payload={}, ts=1.0))
        await bus.emit(AgentEvent(EventKind.ERROR, payload={"error": "boom" * 200}, ts=2.0))
        lines = _read_lines(path)
        assert lines[-1]["event"] == "run_end"
        assert lines[-1]["payload"]["stop_reason"] == "error"


class TestEnvSwitch:
    def test_disabled_no_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("RA_TRACE_DIR", raising=False)
        bus = HookBus()
        assert maybe_attach_tracing(bus) is None
        assert trace_path_from_env() is None
        # 零开销口径：未设置时不注册任何 handler（事件派发无落盘副作用）
        assert bus._handlers == {}

    async def test_enabled_creates_and_writes_trace_file(self, tmp_path, monkeypatch):
        trace_dir = tmp_path / "traces"
        monkeypatch.setenv("RA_TRACE_DIR", str(trace_dir))
        bus = HookBus()
        recorder = maybe_attach_tracing(bus)
        assert recorder is not None
        await bus.emit(AgentEvent(EventKind.RUN_START, payload={}, ts=1.0))
        await bus.emit(AgentEvent(EventKind.RUN_END, payload={"stop_reason": "completed"}, ts=2.0))
        files = list(trace_dir.glob("trace-*.jsonl"))
        assert len(files) == 1
        lines = _read_lines(files[0])
        assert [r["event"] for r in lines] == ["run_start", "run_end"]

    def test_env_path_has_trace_prefix_and_pid(self, tmp_path, monkeypatch):
        import os
        monkeypatch.setenv("RA_TRACE_DIR", str(tmp_path))
        path = trace_path_from_env()
        assert path is not None
        assert path.parent == tmp_path
        assert path.name.startswith("trace-")
        assert str(os.getpid()) in path.name
