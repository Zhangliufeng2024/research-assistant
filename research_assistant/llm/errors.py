"""Structured error taxonomy for LLM API failures.

Classifies errors from HTTP status codes, provider error bodies, and
Retry-After headers — replacing the legacy substring matching in retry.py.

Usage::

    from .errors import classify_response

    resp = await client.post(url, ...)
    if resp.status_code != 200:
        raise classify_response(resp.status_code, dict(resp.headers), resp.text)

Every :class:`LLMError` carries a ``retryable`` flag that the agent loop's
retry logic consults directly (see ``research_assistant.retry``).
"""

from __future__ import annotations

import email.utils
import time


class LLMError(Exception):
    """Base class for all classified LLM API errors."""

    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        provider_type: str = "",
        provider_code: str = "",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider_type = provider_type
        self.provider_code = provider_code
        self.retry_after = retry_after


class NetworkError(LLMError):
    """Transport-level failure (connect/read/timeout). Retryable."""

    retryable = True


class RateLimitError(LLMError):
    """HTTP 429. Retryable — honour ``retry_after`` when present."""

    retryable = True


class OverloadedError(LLMError):
    """Provider temporarily overloaded (Anthropic 529 / 503 overloaded)."""

    retryable = True


class ServerError(LLMError):
    """Other 5xx server errors."""

    retryable = True


class AuthError(LLMError):
    """HTTP 401/403 — bad key or forbidden. Never retryable."""


class ContextLimitError(LLMError):
    """Request exceeds the model's context window. Never retryable.

    Name kept identical to the legacy exception in research_assistant.retry
    so existing ``except`` clauses keep working. Legacy call style
    ``ContextLimitError(original_exception)`` is still supported and sets
    ``self.original``.
    """

    def __init__(self, message="", *, original=None, **kwargs) -> None:
        if isinstance(message, BaseException) and original is None:
            original = message
            message = (
                f"Context/token limit exceeded: {original}. "
                "Start a new session or reduce the prompt size."
            )
        super().__init__(message, **kwargs)
        self.original = original


class ModelConfigError(LLMError):
    """Unknown/unsupported model name. Never retryable."""

    def __init__(self, message="", *, original=None, **kwargs) -> None:
        if isinstance(message, BaseException) and original is None:
            original = message
            message = (
                f"Model configuration error: {original}\n"
                "Check LLM_MODEL in your .env file — "
                "the model may not be supported by your API gateway."
            )
        super().__init__(message, **kwargs)
        self.original = original


class BadRequestError(LLMError):
    """HTTP 400 that is neither a context-limit nor model-name problem."""


class HeartbeatTimeoutError(LLMError):
    """No streaming activity within the heartbeat window. Retryable."""

    retryable = True

    def __init__(self, timeout: float, phase: str = "") -> None:
        self.timeout = timeout
        # phase 说明卡在哪个阶段（R9）：「首字节」= 端点接受连接但迟迟不响应，
        # 「静默」= 流开始后中断；「总时长」= keepalive 滴流无限续期的兜底。
        label = f"{phase}（{timeout:.0f} 秒）" if phase else f"{timeout:.0f} 秒"
        super().__init__(
            f"No output received from the LLM for {label}. "
            "The stream may be stuck."
        )


# ---------------------------------------------------------------------------
# Body parsing helpers
# ---------------------------------------------------------------------------

_CONTEXT_MARKERS = (
    "input token limit",
    "context length",
    "context_length_exceeded",
    "maximum context",
    "token limit exceeded",
    "tokens exceed",
    "prompt is too long",
    "request too large",
    "exceeds the maximum",
)

_MODEL_MARKERS = (
    "not supported model",
    "model not found",
    "invalid model",
    "model_not_found",
    "does not exist or you do not have access",
)


def parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header value into seconds.

    Accepts delay-seconds (``"30"``) and HTTP-date formats.
    Returns None when absent or unparseable. Capped at 300 s.
    """
    if not value:
        return None
    value = value.strip()
    try:
        return min(float(value), 300.0)
    except ValueError:
        pass  # 控制流：非 delay-seconds 格式，继续尝试 HTTP-date 解析
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt is None:
            return None
        delta = dt.timestamp() - time.time()
        if delta <= 0:
            return None
        return min(delta, 300.0)
    except (TypeError, ValueError, OverflowError):
        return None


def classify_response(
    status_code: int,
    headers: dict | None = None,
    body_text: str = "",
) -> LLMError:
    """Build a typed :class:`LLMError` from an HTTP error response.

    Classification order matters: rate limiting is checked by status code
    first, then context-limit / model-name markers inside the body, then
    generic status-based classes.
    """
    headers = headers or {}
    body_lower = (body_text or "")[:4000].lower()
    retry_after = parse_retry_after(headers.get("retry-after"))

    def _err(cls: type[LLMError], message: str, **kw) -> LLMError:
        return cls(message, status_code=status_code, retry_after=retry_after, **kw)

    if status_code == 429:
        return _err(RateLimitError, f"Rate limited (429): {body_text[:300]}")

    # Provider-specific overload codes before generic 5xx handling.
    if status_code == 529 or (status_code == 503 and "overloaded" in body_lower):
        return _err(OverloadedError, f"Provider overloaded ({status_code}): {body_text[:300]}")

    if any(m in body_lower for m in _CONTEXT_MARKERS):
        return _err(ContextLimitError, f"Context/token limit exceeded: {body_text[:300]}")

    if any(m in body_lower for m in _MODEL_MARKERS):
        return _err(ModelConfigError, f"Model configuration error: {body_text[:300]}")

    if status_code in (401, 403):
        return _err(AuthError, f"Authentication failed ({status_code}): {body_text[:300]}")

    if status_code == 400:
        return _err(BadRequestError, f"Bad request (400): {body_text[:300]}")

    if 500 <= status_code < 600:
        return _err(ServerError, f"Server error ({status_code}): {body_text[:300]}")

    # Unknown non-200 status: treat as retryable server-side hiccup only if >=500,
    # otherwise a bad request we cannot interpret.
    if status_code >= 500:
        return _err(ServerError, f"Server error ({status_code}): {body_text[:300]}")
    return _err(BadRequestError, f"API error ({status_code}): {body_text[:300]}")
