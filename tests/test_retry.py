"""Tests for research_assistant.retry."""

import asyncio
import pytest

from research_assistant.retry import (
    HeartbeatTimeoutError,
    ContextLimitError,
    ModelConfigError,
    _is_retryable,
    _is_context_limit,
    _is_model_error,
    query_with_retry,
    query_with_heartbeat,
    query_with_retry_and_heartbeat,
)


class TestErrorClassification:
    def test_connection_error_is_retryable(self):
        assert _is_retryable(ConnectionError("reset"))

    def test_timeout_error_is_retryable(self):
        assert _is_retryable(TimeoutError("timed out"))

    def test_broken_pipe_is_retryable(self):
        assert _is_retryable(BrokenPipeError("broken"))

    def test_permission_error_not_retryable(self):
        assert not _is_retryable(PermissionError("denied"))

    def test_file_not_found_not_retryable(self):
        assert not _is_retryable(FileNotFoundError("missing"))

    def test_value_error_not_retryable(self):
        assert not _is_retryable(ValueError("bad value"))

    def test_message_based_retryable(self):
        assert _is_retryable(RuntimeError("connection reset by peer"))
        assert _is_retryable(RuntimeError("HTTP 502 bad gateway"))
        assert _is_retryable(RuntimeError("HTTP 529 overloaded"))
        assert _is_retryable(RuntimeError("rate limit exceeded"))
        assert _is_retryable(RuntimeError("stream closed unexpectedly"))

    def test_heartbeat_timeout_is_retryable(self):
        assert _is_retryable(HeartbeatTimeoutError(300))

    def test_context_limit_not_retryable(self):
        assert not _is_retryable(RuntimeError("input token limit exceeded"))

    def test_model_error_not_retryable(self):
        assert not _is_retryable(RuntimeError("not supported model"))


class TestIsContextLimit:
    def test_positive(self):
        assert _is_context_limit(RuntimeError("input token limit reached"))
        assert _is_context_limit(RuntimeError("context_length_exceeded"))

    def test_negative(self):
        assert not _is_context_limit(RuntimeError("connection error"))


class TestIsModelError:
    def test_positive(self):
        assert _is_model_error(RuntimeError("not supported model: fake-model"))
        assert _is_model_error(RuntimeError("model not found"))

    def test_negative(self):
        assert not _is_model_error(RuntimeError("timeout"))


class TestHeartbeatTimeoutError:
    def test_attributes(self):
        e = HeartbeatTimeoutError(120.0)
        assert e.timeout == 120.0
        assert "120" in str(e)


class TestContextLimitError:
    def test_wraps_original(self):
        orig = RuntimeError("token limit")
        e = ContextLimitError(orig)
        assert e.original is orig
        assert "token limit" in str(e)


class TestModelConfigError:
    def test_wraps_original(self):
        orig = RuntimeError("not supported model")
        e = ModelConfigError(orig)
        assert e.original is orig


# --- Async generator tests ---

async def _mock_query_success(prompt, options):
    """Mock query that yields two messages."""
    for text in ["hello", "world"]:
        yield type("Msg", (), {"content": [type("B", (), {"text": text})()]})()


async def _mock_query_fail_then_succeed(prompt, options, _state={"calls": 0}):
    """Mock query that fails on first call, succeeds on second."""
    _state["calls"] += 1
    if _state["calls"] <= 1:
        raise ConnectionError("transient failure")
    yield type("Msg", (), {"content": [type("B", (), {"text": "recovered"})()]})()


async def _mock_query_context_limit(prompt, options):
    """Mock query that raises a context limit error."""
    raise RuntimeError("input token limit exceeded")
    yield  # pragma: no cover - makes this an async generator


async def _mock_query_slow(prompt, options):
    """Mock query that takes forever (for heartbeat testing)."""
    await asyncio.sleep(999)
    yield  # pragma: no cover


@pytest.mark.asyncio
async def test_query_with_retry_success():
    messages = []
    async for msg in query_with_retry(
        prompt="test", options=None, query_fn=_mock_query_success,
        max_retries=0, base_delay=0.01,
    ):
        messages.append(msg)
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_query_with_retry_context_limit():
    with pytest.raises(ContextLimitError):
        async for _ in query_with_retry(
            prompt="test", options=None, query_fn=_mock_query_context_limit,
            max_retries=3, base_delay=0.01,
        ):
            pass


@pytest.mark.asyncio
async def test_query_with_heartbeat_timeout():
    with pytest.raises(HeartbeatTimeoutError):
        async for _ in query_with_heartbeat(
            prompt="test", options=None, query_fn=_mock_query_slow,
            heartbeat_timeout=0.05,
        ):
            pass


@pytest.mark.asyncio
async def test_query_with_heartbeat_success():
    messages = []
    async for msg in query_with_heartbeat(
        prompt="test", options=None, query_fn=_mock_query_success,
        heartbeat_timeout=5.0,
    ):
        messages.append(msg)
    assert len(messages) == 2
