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
from .llm.errors import (  # noqa: F401  (re-exported for backward compatibility)
    LLMError,
    ContextLimitError,
    ModelConfigError,
    HeartbeatTimeoutError,
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
# HeartbeatTimeoutError / ContextLimitError / ModelConfigError are now defined
# in research_assistant.llm.errors with a structured retryable flag and
# re-exported here so existing ``from .retry import ...`` keeps working.
# ---------------------------------------------------------------------------


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


# ContextLimitError / ModelConfigError / HeartbeatTimeoutError are imported
# from llm.errors at the top of this module (backward-compatible re-export).


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
    # Structured errors from llm/errors.py carry their own classification.
    if isinstance(exc, LLMError):
        return exc.retryable

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

