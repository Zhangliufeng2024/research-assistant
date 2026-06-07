"""Tests for research_assistant.steer — drain_steer_queue and SteerReader."""

import asyncio

import pytest

from research_assistant.agent import _drain_steer_queue


class TestDrainSteerQueue:
    def test_none_queue(self):
        messages = []
        result = _drain_steer_queue(None, messages)
        assert result == []
        assert messages == []

    def test_empty_queue(self):
        queue = asyncio.Queue()
        messages = []
        result = _drain_steer_queue(queue, messages)
        assert result == []
        assert messages == []

    def test_single_message(self):
        queue = asyncio.Queue()
        queue.put_nowait("focus on methods")
        messages = [{"role": "assistant", "content": "Working..."}]
        result = _drain_steer_queue(queue, messages)
        assert result == ["focus on methods"]
        assert len(messages) == 2
        assert messages[-1]["role"] == "user"
        assert "[USER STEER]: focus on methods" in messages[-1]["content"]

    def test_multiple_messages_batched(self):
        queue = asyncio.Queue()
        queue.put_nowait("change topic")
        queue.put_nowait("add more citations")
        messages = []
        result = _drain_steer_queue(queue, messages)
        assert len(result) == 2
        assert len(messages) == 1
        assert "[USER STEER]: change topic" in messages[0]["content"]
        assert "[USER STEER]: add more citations" in messages[0]["content"]

    def test_queue_is_drained(self):
        queue = asyncio.Queue()
        queue.put_nowait("msg1")
        queue.put_nowait("msg2")
        messages = []
        _drain_steer_queue(queue, messages)
        assert queue.empty()
        result2 = _drain_steer_queue(queue, messages)
        assert result2 == []
