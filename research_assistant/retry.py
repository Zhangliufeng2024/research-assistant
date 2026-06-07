"""
Retry and heartbeat utilities for research assistant.

Provides two key capabilities:
  1. query_with_retry   – wraps an async-generator query call with exponential-backoff
                          retry on transient network / timeout errors.
  2. query_with_heartbeat – wraps an async-generator query call and raises
                            HeartbeatTimeoutError if no message is received within
                            a configurable window (detects "stuck" sessions).

Errors handled:
  - Transient network errors (ConnectionError, TimeoutError, HTTP 502/503/529, etc.)
    → retried up to max_retries times with exponential backoff
  - SDK subprocess crashes ("Stream closed", "Command failed with exit code", etc.)
    → treated as transient, retried automatically
  - Context/token limit errors (HTTP 400 "input token limit exceeded", etc.)
    → raised immediately as ContextLimitError (never retryable)
  - HeartbeatTimeoutError (agent produces no output for heartbeat_timeout seconds)
    → retried automatically; after all retries exhausted, re-raised for user handling

Environment variables
---------------------
RA_MAX_RETRIES       int   Maximum retry attempts on network errors (default 3)
RA_RETRY_BASE_DELAY  float Seconds for first backoff delay (default 5.0)
RA_HEARTBEAT_TIMEOUT float Seconds of silence before "stuck" warning (default 300)
"""

import asyncio
import os
from typing import AsyncIterator, Callable, AsyncGenerator, TypeVar

# ---------------------------------------------------------------------------
# Public defaults (can be overridden by environment variables)
# ---------------------------------------------------------------------------
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BASE_DELAY = 5.0       # seconds; doubles each attempt (5 → 10 → 20)
DEFAULT_HEARTBEAT_TIMEOUT = 300.0    # 5 minutes of silence = probably stuck


def get_max_retries() -> int:
    return int(os.getenv("RA_MAX_RETRIES", DEFAULT_MAX_RETRIES))


def get_retry_base_delay() -> float:
    return float(os.getenv("RA_RETRY_BASE_DELAY", DEFAULT_RETRY_BASE_DELAY))


def get_heartbeat_timeout() -> float:
    return float(os.getenv("RA_HEARTBEAT_TIMEOUT", DEFAULT_HEARTBEAT_TIMEOUT))


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


# ---------------------------------------------------------------------------
# query_with_retry
# ---------------------------------------------------------------------------

async def query_with_retry(
    prompt: str,
    options,
    query_fn,
    max_retries: int | None = None,
    base_delay: float | None = None,
    on_retry=None,          # optional async callback(attempt, exc, delay) for progress reporting
) -> AsyncGenerator:
    """
    Async-generator wrapper that retries *query_fn* on transient network errors.

    Args:
        prompt:      The prompt to pass to query_fn.
        options:     ClaudeAgentOptions to pass to query_fn.
        query_fn:    The async-generator callable (e.g. claude_query or sdk.query).
        max_retries: Max number of retries (default: RA_MAX_RETRIES env var).
        base_delay:  Seconds before first retry; doubles each attempt.
        on_retry:    Optional async callable(attempt, exc, delay) called before each retry.
                     Use this to yield progress updates from the caller.

    Yields:
        All messages from query_fn on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    if max_retries is None:
        max_retries = get_max_retries()
    if base_delay is None:
        base_delay = get_retry_base_delay()

    last_exc: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            async for message in query_fn(prompt=prompt, options=options):
                yield message
            return  # success — exit generator cleanly

        except BaseException as exc:
            last_exc = exc

            # Context limit: convert to a clear, non-retryable exception immediately
            if _is_context_limit(exc):
                raise ContextLimitError(exc) from exc

            # Model configuration error: convert to a clear, non-retryable exception
            if _is_model_error(exc):
                raise ModelConfigError(exc) from exc

            # Non-retryable or we've used all attempts → re-raise immediately
            if not _is_retryable(exc) or attempt >= max_retries:
                raise

            delay = base_delay * (2 ** attempt)  # 5 → 10 → 20 s

            if on_retry is not None:
                await on_retry(attempt + 1, exc, delay)

            await asyncio.sleep(delay)

    # Should not reach here, but satisfy type checker
    if last_exc is not None:
        raise last_exc


# ---------------------------------------------------------------------------
# query_with_heartbeat
# ---------------------------------------------------------------------------

async def query_with_heartbeat(
    prompt: str,
    options,
    query_fn,
    heartbeat_timeout: float | None = None,
) -> AsyncGenerator:
    """
    Async-generator wrapper that raises HeartbeatTimeoutError if the underlying
    query produces no messages for longer than *heartbeat_timeout* seconds.

    This detects "stuck" sessions where the agent has stopped producing output
    (network hang, model overload, infinite tool loop with no text output, etc.).

    Args:
        prompt:             Prompt to pass to query_fn.
        options:            ClaudeAgentOptions.
        query_fn:           The async-generator callable.
        heartbeat_timeout:  Seconds of silence before raising.
                            Defaults to RA_HEARTBEAT_TIMEOUT env var.

    Yields:
        All messages from query_fn.

    Raises:
        HeartbeatTimeoutError: If no message is received within the timeout window.
    """
    if heartbeat_timeout is None:
        heartbeat_timeout = get_heartbeat_timeout()

    iterator = query_fn(prompt=prompt, options=options).__aiter__()

    while True:
        try:
            message = await asyncio.wait_for(
                iterator.__anext__(),
                timeout=heartbeat_timeout,
            )
        except StopAsyncIteration:
            return
        except asyncio.TimeoutError:
            raise HeartbeatTimeoutError(heartbeat_timeout)

        yield message


# ---------------------------------------------------------------------------
# Combined: heartbeat + retry
# ---------------------------------------------------------------------------

async def query_with_retry_and_heartbeat(
    prompt: str,
    options,
    query_fn,
    max_retries: int | None = None,
    base_delay: float | None = None,
    heartbeat_timeout: float | None = None,
    on_retry=None,
) -> AsyncGenerator:
    """
    Combines heartbeat detection with retry logic.

    HeartbeatTimeoutError is treated as a retryable condition so that a stuck
    session automatically restarts (up to max_retries times) before giving up.

    All arguments are the same as query_with_retry / query_with_heartbeat.
    """
    if max_retries is None:
        max_retries = get_max_retries()
    if base_delay is None:
        base_delay = get_retry_base_delay()
    if heartbeat_timeout is None:
        heartbeat_timeout = get_heartbeat_timeout()

    last_exc: BaseException | None = None

    for attempt in range(max_retries + 1):
        try:
            async for message in query_with_heartbeat(
                prompt=prompt,
                options=options,
                query_fn=query_fn,
                heartbeat_timeout=heartbeat_timeout,
            ):
                yield message
            return  # success

        except BaseException as exc:
            last_exc = exc

            # Context limit: convert to a clear, non-retryable exception immediately
            if _is_context_limit(exc):
                raise ContextLimitError(exc) from exc

            # Model configuration error: convert to a clear, non-retryable exception
            if _is_model_error(exc):
                raise ModelConfigError(exc) from exc

            retryable = _is_retryable(exc) or isinstance(exc, HeartbeatTimeoutError)

            if not retryable or attempt >= max_retries:
                raise

            delay = base_delay * (2 ** attempt)

            if on_retry is not None:
                await on_retry(attempt + 1, exc, delay)

            await asyncio.sleep(delay)

    if last_exc is not None:
        raise last_exc
