"""
Retry and heartbeat utilities for research assistant.

Provides error classification and configuration for the agent loop's
built-in retry logic (see agent._llm_call_with_retry).

Errors handled:
  - Transient network errors (ConnectionError, TimeoutError, HTTP 502/503/529, etc.)
    → retried up to max_retries times with exponential backoff
  - Context/token limit errors (HTTP 400 "input token limit exceeded", etc.)
    → raised immediately as ContextLimitError (never retryable)
  - Model config errors (HTTP 400 "not supported model", etc.)
    → raised immediately as ModelConfigError (never retryable)
  - HeartbeatTimeoutError (LLM call exceeds heartbeat_timeout seconds)
    → retried automatically; after all retries exhausted, re-raised for user handling

Environment variables
---------------------
RA_MAX_RETRIES       int   Maximum retry attempts on network errors (default 3)
RA_RETRY_BASE_DELAY  float Seconds for first backoff delay (default 5.0)
RA_HEARTBEAT_TIMEOUT float Seconds of silence before "stuck" warning (default 300)
"""

import asyncio
import os

from .constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BASE_DELAY,
    DEFAULT_HEARTBEAT_TIMEOUT,
)


def _safe_int(value: str | None, default: int) -> int:
    """Parse an environment variable as int, falling back to *default*."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_float(value: str | None, default: float) -> float:
    """Parse an environment variable as float, falling back to *default*."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def get_max_retries() -> int:
    return _safe_int(os.getenv("RA_MAX_RETRIES"), DEFAULT_MAX_RETRIES)


def get_retry_base_delay() -> float:
    return _safe_float(os.getenv("RA_RETRY_BASE_DELAY"), DEFAULT_RETRY_BASE_DELAY)


def get_heartbeat_timeout() -> float:
    return _safe_float(os.getenv("RA_HEARTBEAT_TIMEOUT"), DEFAULT_HEARTBEAT_TIMEOUT)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class HeartbeatTimeoutError(Exception):
    """Raised when no message is received from the agent within the heartbeat window."""

    def __init__(self, timeout: float):
        self.timeout = timeout
        super().__init__(
            f"No output received from the agent for {timeout:.0f} seconds. "
            "The session may be stuck."
        )


# ---------------------------------------------------------------------------
# Retryable error detection
# ---------------------------------------------------------------------------

# Exception type names that are considered transient / worth retrying.
_RETRYABLE_TYPE_NAMES = {
    "ConnectionError",
    "ConnectionResetError",
    "ConnectionAbortedError",
    "ConnectionRefusedError",
    "BrokenPipeError",
    "TimeoutError",
    "asyncio.TimeoutError",
    "httpx.ConnectError",
    "httpx.ReadTimeout",
    "httpx.WriteTimeout",
    "httpx.RemoteProtocolError",
    "httpcore.ConnectError",
    "httpcore.ReadTimeout",
    "requests.exceptions.ConnectionError",
    "requests.exceptions.Timeout",
    "aiohttp.ClientConnectionError",
    "aiohttp.ServerDisconnectedError",
    "aiohttp.ClientPayloadError",
}

# Substrings in the error message that identify retryable conditions.
_RETRYABLE_MESSAGES = (
    "connection reset",
    "connection refused",
    "connection aborted",
    "broken pipe",
    "timed out",
    "timeout",
    "network",
    "eof",
    "ssl",
    "socket",
    "temporary failure",
    "service unavailable",
    "bad gateway",
    "gateway timeout",
    "overloaded",
    "rate limit",
    "too many requests",
    "529",   # Anthropic overload HTTP code
    "503",
    "502",
    # SDK subprocess / stream errors (claude-agent-sdk process crash)
    "stream closed",
    "command failed with exit code",
    "fatal error in message reader",
    "exit code: 1",
    "exit code: 2",
)

# Substrings that identify non-retryable API errors that should surface clearly.
_CONTEXT_LIMIT_MESSAGES = (
    "input token limit",
    "context length",
    "context_length_exceeded",
    "maximum context",
    "token limit exceeded",
    "tokens exceed",
)

# Substrings that identify non-retryable model configuration errors (HTTP 400).
# These will NEVER succeed on retry — the model name itself is wrong.
_MODEL_ERROR_MESSAGES = (
    "not supported model",
    "model not found",
    "invalid model",
    "model_not_found",
)


class ContextLimitError(Exception):
    """Raised when the API rejects a request due to exceeding the token/context limit.

    This is NOT retryable — repeating the same request will always fail.
    The caller should inform the user and suggest starting a new session or
    reducing the input size.
    """

    def __init__(self, original: BaseException):
        self.original = original
        super().__init__(
            f"Context/token limit exceeded: {original}. "
            "Start a new session or reduce the prompt size."
        )


class ModelConfigError(Exception):
    """Raised when the API rejects the model name (HTTP 400 "Not supported model").

    This is NOT retryable — the model name is wrong or unsupported by the gateway.
    The caller should inform the user to check LLM_MODEL in .env.
    """

    def __init__(self, original: BaseException):
        self.original = original
        super().__init__(
            f"Model configuration error: {original}\n"
            "Check LLM_MODEL in your .env file — "
            "the model may not be supported by your API gateway."
        )


def _is_context_limit(exc: BaseException) -> bool:
    """Return True if the exception is a non-retryable context/token limit error."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _CONTEXT_LIMIT_MESSAGES)


def _is_model_error(exc: BaseException) -> bool:
    """Return True if the exception is a non-retryable model configuration error (HTTP 400)."""
    msg = str(exc).lower()
    return any(kw in msg for kw in _MODEL_ERROR_MESSAGES)


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the exception represents a transient error worth retrying."""
    # Context limit errors are never retryable — raise them immediately as ContextLimitError.
    if _is_context_limit(exc):
        return False

    # Model configuration errors (400 "Not supported model") are never retryable.
    # The model name is wrong — retrying will always fail with the same error.
    if _is_model_error(exc):
        return False

    # asyncio.TimeoutError and our own HeartbeatTimeoutError are always retryable
    if isinstance(exc, (asyncio.TimeoutError, HeartbeatTimeoutError)):
        return True

    # Only network-level OSError subclasses are retryable.
    # Explicitly exclude filesystem/permission errors (also OSError subclasses)
    # that can never succeed on retry.
    _NON_RETRYABLE_OS = (
        PermissionError,
        FileNotFoundError,
        FileExistsError,
        IsADirectoryError,
        NotADirectoryError,
        ProcessLookupError,
        ChildProcessError,
    )
    if isinstance(exc, _NON_RETRYABLE_OS):
        return False

    # Network-oriented OSError subclasses: ConnectionError hierarchy + BrokenPipeError
    if isinstance(exc, (ConnectionError, BrokenPipeError, TimeoutError)):
        return True

    # Check by type name (catches third-party HTTP library errors without hard imports)
    type_name = type(exc).__name__
    qualified = f"{type(exc).__module__}.{type_name}"
    if type_name in _RETRYABLE_TYPE_NAMES or qualified in _RETRYABLE_TYPE_NAMES:
        return True

    # Check error message for known transient patterns
    msg = str(exc).lower()
    if any(kw in msg for kw in _RETRYABLE_MESSAGES):
        return True

    return False

