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
    _safe_int,
    _safe_float,
    get_max_retries,
    get_retry_base_delay,
    get_heartbeat_timeout,
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


class TestSafeEnvParsing:
    def test_safe_int_valid(self):
        assert _safe_int("5", 3) == 5

    def test_safe_int_none(self):
        assert _safe_int(None, 3) == 3

    def test_safe_int_invalid(self):
        assert _safe_int("abc", 3) == 3

    def test_safe_int_empty(self):
        assert _safe_int("", 3) == 3

    def test_safe_float_valid(self):
        assert _safe_float("2.5", 1.0) == 2.5

    def test_safe_float_none(self):
        assert _safe_float(None, 1.0) == 1.0

    def test_safe_float_invalid(self):
        assert _safe_float("xyz", 1.0) == 1.0

    def test_get_max_retries_default(self, monkeypatch):
        monkeypatch.delenv("RA_MAX_RETRIES", raising=False)
        assert get_max_retries() == 3

    def test_get_max_retries_from_env(self, monkeypatch):
        monkeypatch.setenv("RA_MAX_RETRIES", "7")
        assert get_max_retries() == 7

    def test_get_max_retries_bad_env(self, monkeypatch):
        monkeypatch.setenv("RA_MAX_RETRIES", "not_a_number")
        assert get_max_retries() == 3

    def test_get_retry_base_delay_default(self, monkeypatch):
        monkeypatch.delenv("RA_RETRY_BASE_DELAY", raising=False)
        assert get_retry_base_delay() == 5.0

    def test_get_heartbeat_timeout_default(self, monkeypatch):
        monkeypatch.delenv("RA_HEARTBEAT_TIMEOUT", raising=False)
        assert get_heartbeat_timeout() == 300.0
