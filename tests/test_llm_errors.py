"""Tests for research_assistant.llm.errors — structured error taxonomy."""

import time
import email.utils

import httpx
import pytest

from research_assistant.llm.errors import (
    AuthError,
    BadRequestError,
    ContextLimitError,
    HeartbeatTimeoutError,
    LLMError,
    ModelConfigError,
    OverloadedError,
    RateLimitError,
    ServerError,
    classify_response,
    parse_retry_after,
)
from research_assistant.retry import _is_retryable


class TestParseRetryAfter:
    def test_delay_seconds(self):
        assert parse_retry_after("30") == 30.0

    def test_http_date(self):
        future = email.utils.formatdate(time.time() + 60, usegmt=True)
        val = parse_retry_after(future)
        assert val is not None and 0 < val <= 300

    def test_missing_and_garbage(self):
        assert parse_retry_after(None) is None
        assert parse_retry_after("") is None
        assert parse_retry_after("soon") is None

    def test_capped_at_300(self):
        assert parse_retry_after("9999") == 300.0


class TestClassifyResponse:
    def test_429_is_rate_limit_with_retry_after(self):
        err = classify_response(429, {"retry-after": "12"}, "too many requests")
        assert isinstance(err, RateLimitError)
        assert err.retryable
        assert err.retry_after == 12.0

    def test_529_is_overloaded(self):
        err = classify_response(529, {}, "overloaded_error")
        assert isinstance(err, OverloadedError)
        assert err.retryable

    def test_503_overloaded_body(self):
        err = classify_response(503, {}, '{"error":{"type":"overloaded_error"}}')
        assert isinstance(err, OverloadedError)

    def test_503_plain_is_server_error(self):
        err = classify_response(503, {}, "service unavailable")
        assert isinstance(err, ServerError)
        assert err.retryable

    def test_context_limit_markers(self):
        for body in (
            "prompt is too long: 250000 tokens > 200000",
            '{"error":{"message":"input token limit exceeded"}}',
            "context_length_exceeded",
        ):
            err = classify_response(400, {}, body)
            assert isinstance(err, ContextLimitError)
            assert not err.retryable

    def test_model_markers(self):
        for body in ("model_not_found", '"not supported model: gpt-9"'):
            err = classify_response(400, {}, body)
            assert isinstance(err, ModelConfigError)
            assert not err.retryable

    def test_auth(self):
        err = classify_response(401, {}, "invalid api key")
        assert isinstance(err, AuthError)
        assert not err.retryable

    def test_plain_400(self):
        err = classify_response(400, {}, "invalid_request_error")
        assert isinstance(err, BadRequestError)
        assert not err.retryable

    def test_500(self):
        err = classify_response(500, {}, "internal error")
        assert isinstance(err, ServerError)
        assert err.retryable


class TestRetryableIntegration:
    def test_typed_errors_drive_retry_decision(self):
        assert _is_retryable(RateLimitError("x"))
        assert _is_retryable(OverloadedError("x"))
        assert _is_retryable(ServerError("x"))
        assert not _is_retryable(ContextLimitError("x"))
        assert not _is_retryable(ModelConfigError("x"))
        assert not _is_retryable(AuthError("x"))

    def test_legacy_construction_sets_original(self):
        cause = RuntimeError("input token limit exceeded")
        err = ContextLimitError(cause)
        assert err.original is cause
        assert "Start a new session" in str(err)

        err2 = ModelConfigError(RuntimeError("not supported model"))
        assert err2.original is not None
        assert "LLM_MODEL" in str(err2)


def _client_with_mock(cls, handler):
    client = cls(api_key="test-key", base_url="http://fake.local", model="test-model")
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


class TestClientWiring:
    @pytest.mark.asyncio
    async def test_anthropic_raises_typed_rate_limit(self):
        from research_assistant.llm.anthropic import AnthropicClient

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"retry-after": "7"}, text="rate limited")

        client = _client_with_mock(AnthropicClient, handler)
        try:
            with pytest.raises(RateLimitError) as exc_info:
                await client.chat([{"role": "user", "content": "hi"}])
            assert exc_info.value.retry_after == 7.0
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_openai_raises_typed_context_limit(self):
        from research_assistant.llm.openai_compat import OpenAICompatClient

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={"error": {"message": "This model's maximum context length is exceeded"}},
            )

        client = _client_with_mock(OpenAICompatClient, handler)
        try:
            with pytest.raises(ContextLimitError):
                await client.chat([{"role": "user", "content": "hi"}])
        finally:
            await client.close()
