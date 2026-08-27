"""Tests for research_assistant.retry."""


from research_assistant.retry import (
    ContextLimitError,
    HeartbeatTimeoutError,
    ModelConfigError,
    _is_context_limit,
    _is_model_error,
    _is_retryable,
    _safe_float,
    _safe_int,
    get_heartbeat_timeout,
    get_max_retries,
    get_retry_base_delay,
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


class TestRetryableWordBoundaries:
    """缺陷 F：裸子串误判——TypeError 提 networkx、消息含 150290 都不该重试。"""

    def test_substring_lookalikes_not_retryable(self):
        assert not _is_retryable(TypeError(
            "unsupported operand type(s) for +: 'int' and 'networkx.classes.graph.Graph'"))
        assert not _is_retryable(ValueError("row index 150290 out of range"))
        assert not _is_retryable(RuntimeError("failed at step 5031"))  # 503 子串
        assert not _is_retryable(RuntimeError("imported module 'sslyze' missing"))

    def test_real_status_codes_still_retryable(self):
        assert _is_retryable(RuntimeError("HTTP 502 bad gateway"))
        assert _is_retryable(RuntimeError("HTTP/1.1 503 Service Unavailable"))
        assert _is_retryable(RuntimeError("429 too many requests"))
        assert _is_retryable(RuntimeError("529 overloaded_error"))

    def test_network_words_still_retryable(self):
        assert _is_retryable(RuntimeError("connection reset by peer"))
        assert _is_retryable(RuntimeError("read timed out"))
        assert _is_retryable(RuntimeError("[SSL: WRONG_VERSION_NUMBER]"))
        assert _is_retryable(RuntimeError("socket hang up"))
        assert _is_retryable(RuntimeError("peer closed connection (eof occurred)"))

    def test_bare_network_word_no_longer_matches(self):
        # 裸 "network" 已从词表移除：普通异常消息里的 incidental 词不再触发重试。
        assert not _is_retryable(ValueError("network graph is disconnected"))


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
