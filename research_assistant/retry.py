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
import re

from .constants import (
    DEFAULT_HEARTBEAT_TIMEOUT,
    DEFAULT_LLM_ATTEMPT_WALL_TIMEOUT,
    DEFAULT_LLM_FIRST_BYTE_TIMEOUT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_BASE_DELAY,
)
from .llm.errors import (  # noqa: F401  (re-exported for backward compatibility)
    CONTEXT_MARKERS,
    MODEL_MARKERS,
    ContextLimitError,
    HeartbeatTimeoutError,
    LLMError,
    ModelConfigError,
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


def get_first_byte_timeout() -> float:
    """流式首字节前的静默窗口（R9）：此阶段没有任何心跳可续期，短超时快失败。"""
    return _safe_float(os.getenv("RA_LLM_FIRST_BYTE_TIMEOUT"), DEFAULT_LLM_FIRST_BYTE_TIMEOUT)


def get_attempt_wall_timeout() -> float:
    """单次 LLM 调用的墙钟上限（R9）：防 keepalive 滴流把静默看门狗无限续期。"""
    return _safe_float(
        os.getenv("RA_LLM_ATTEMPT_WALL_TIMEOUT"), DEFAULT_LLM_ATTEMPT_WALL_TIMEOUT
    )


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

# Retryable message patterns (缺陷 F：词边界匹配，替代裸子串).
# - 数字状态码用 \b 包裹："150290" 不再命中 "502"，"HTTP 502" 照常命中；
# - 网络词表同样词边界化，并删除裸 "network"——TypeError 提到 networkx、
#   普通消息里偶然出现 network 一词都不再被误判成可重试的网络错误。
_RETRYABLE_MESSAGE_PATTERN = re.compile(
    r"\b(?:"
    r"408|425|429|500|502|503|504|529"          # HTTP status codes
    r"|timed out|timeout"
    r"|connection reset|connection refused|connection aborted"
    r"|broken pipe|eof occurred|ssl|socket"
    r"|temporary failure|service unavailable|bad gateway"
    r"|gateway timeout|overloaded|rate limit|too many requests"
    # SDK subprocess / stream errors (claude-agent-sdk process crash)
    r"|stream closed"
    r"|command failed with exit code"
    r"|fatal error in message reader"
    r"|exit code: [12]"
    r")\b",
    re.IGNORECASE,
)

# 上下文上限 / 模型配置的标记表已收敛到 llm/errors.py（P2-5③ 单一来源），
# 此处直接引用其公开常量 CONTEXT_MARKERS / MODEL_MARKERS（超集，含
# "prompt is too long" 等 4 条旧表缺失的标记）。两表原先在两个文件里
# 各自维护，errors.py 侧已多出 4 条而 retry.py 没跟上——裸异常路径会
# 漏判这些不可重试错误，见 docs/CODE_REVIEW_2026-08-31.md P2-5③。


# ContextLimitError / ModelConfigError / HeartbeatTimeoutError are imported
# from llm.errors at the top of this module (backward-compatible re-export).


def _is_context_limit(exc: BaseException) -> bool:
    """Return True if the exception is a non-retryable context/token limit error."""
    msg = str(exc).lower()
    return any(kw in msg for kw in CONTEXT_MARKERS)


def _is_model_error(exc: BaseException) -> bool:
    """Return True if the exception is a non-retryable model configuration error (HTTP 400)."""
    msg = str(exc).lower()
    return any(kw in msg for kw in MODEL_MARKERS)


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

    # Check error message for known transient patterns (词边界匹配，见上方注释)
    if _RETRYABLE_MESSAGE_PATTERN.search(str(exc)):
        return True

    return False

