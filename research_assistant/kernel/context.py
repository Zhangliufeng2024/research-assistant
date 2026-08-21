"""Context management: token estimation, tool-result externalization, compaction.

Two strategies keep long runs inside the model's context window:

1. **Externalization** — large tool results are written to disk immediately;
   the conversation keeps only a preview plus a file pointer the model can
   ``read_file`` later.
2. **Compaction** — when measured input tokens exceed the trigger fraction of
   the model's window, older messages are replaced by one structured summary.
   Cut points respect tool_use/tool_result pairing so requests stay valid.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

SUMMARY_MARKER = "[CONTEXT SUMMARY"
EXTERNALIZE_THRESHOLD_CHARS = 4_000
PREVIEW_CHARS = 800
COMPACTION_TRIGGER_FRACTION = 0.7
KEEP_RECENT_MESSAGES = 12
MIN_SPAN_MESSAGES = 6

# Conservative context windows (input tokens) keyed by model-name prefix.
_MODEL_WINDOWS: tuple[tuple[str, int], ...] = (
    ("claude-opus", 200_000),
    ("claude-sonnet", 200_000),
    ("claude-haiku", 200_000),
    ("claude-", 200_000),
    ("gpt-5", 272_000),
    ("gpt-4.1", 1_000_000),
    ("gpt-4o", 128_000),
    ("gpt-4", 128_000),
    ("deepseek-reasoner", 128_000),
    ("deepseek-chat", 128_000),
    ("qwen", 128_000),
)
DEFAULT_CONTEXT_WINDOW = 128_000


@dataclass
class ModelWindow:
    context_window: int


def window_for(model: str) -> int:
    """Return the known context-window size (input tokens) for *model*."""
    low = (model or "").lower()
    for prefix, size in _MODEL_WINDOWS:
        if low.startswith(prefix):
            return size
    return DEFAULT_CONTEXT_WINDOW


def _message_chars(msg: dict) -> int:
    n = 0
    content = msg.get("content")
    if isinstance(content, str):
        n += len(content)
    elif isinstance(content, list):
        n += sum(len(json.dumps(b)) for b in content)
    for tc in msg.get("tool_calls") or []:
        n += len(json.dumps(tc.get("arguments", {})))
    return n


def estimate_tokens(messages: list[dict], system: str = "") -> int:
    """Rough token estimate (~4 chars/token) good enough for trigger decisions."""
    total = len(system)
    for msg in messages:
        total += _message_chars(msg)
    return total // 4


# ---------------------------------------------------------------------------
# Externalization
# ---------------------------------------------------------------------------

def externalize_tool_result(
    result: str,
    tool_name: str,
    turn: int,
    artifacts_dir: Path,
) -> str:
    """Write *result* to disk if oversized; return preview-with-pointer either way."""
    if len(result) <= EXTERNALIZE_THRESHOLD_CHARS:
        return result

    try:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = artifacts_dir / f"turn_{turn:04d}_{tool_name}.txt"
        path.write_text(result, encoding="utf-8")
    except OSError:
        return result  # best-effort: never lose a tool result over an IO error

    head = result[:PREVIEW_CHARS]
    return (
        f"{head}\n\n"
        f"[OUTPUT TRUNCATED — full {len(result)}-char result saved to: {path} "
        f"(use read_file to view)]"
    )


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------

_SUMMARY_SYSTEM = (
    "You are compacting an AI agent's conversation history so work can continue "
    "seamlessly in a fresh context. Produce a dense markdown summary with exactly "
    "these sections:\n"
    "## Goal\n## Decisions Made\n## Facts & Data Found\n## Files Created/Modified\n"
    "## Current State & Next Steps\n"
    "Be specific: preserve file paths, section names, numbers, citation keys, and "
    "any pending TODOs. Maximum 800 words."
)


def _is_tool_result(msg: dict) -> bool:
    return msg.get("role") == "tool"


def _has_pending_tool_calls(msg: dict) -> bool:
    return bool(msg.get("tool_calls"))


def find_cut_point(messages: list[dict], keep_recent: int = KEEP_RECENT_MESSAGES) -> int:
    """Find index *cut* such that messages[:cut] can be summarized and dropped.

    The kept tail ``messages[cut:]`` must be self-contained: it may not start
    with a ``tool`` result orphaned from its assistant tool_calls, and the
    message before *cut* may not carry unresolved tool_calls. Returns 0 when
    there is nothing safely compactable.
    """
    cut = len(messages) - keep_recent
    if cut < 2:
        return 0

    # Never start the tail on an orphaned tool result.
    while cut > 0 and _is_tool_result(messages[cut]):
        cut -= 1

    # Never leave an assistant tool_calls message pointing at dropped results.
    while cut > 0 and _has_pending_tool_calls(messages[cut - 1]):
        cut -= 1
        while cut > 0 and _is_tool_result(messages[cut]):
            cut -= 1

    # Span must be meaty enough to be worth an LLM call.
    # messages[0] is the original user prompt and always stays.
    if cut - 1 < MIN_SPAN_MESSAGES:
        return 0
    return cut


def render_span_for_summary(span: list[dict]) -> str:
    """Flatten a message span into readable transcript text for the summarizer."""
    lines: list[str] = []
    for msg in span:
        role = msg.get("role", "?")
        content = msg.get("content") or ""
        if isinstance(content, list):
            content = json.dumps(content)[:1500]
        lines.append(f"[{role}] {content}".rstrip())
        for tc in msg.get("tool_calls") or []:
            args = json.dumps(tc.get("arguments", {}), ensure_ascii=False)[:600]
            lines.append(f"[{role}:tool_call] {tc.get('name')}({args})")
    return "\n".join(lines)


async def summarize_span(
    llm_client,
    span_text: str,
    max_tokens: int = 1600,
) -> str:
    response = await llm_client.chat(
        messages=[{"role": "user", "content": span_text}],
        system=_SUMMARY_SYSTEM,
        temperature=0.2,
        max_tokens=max_tokens,
    )
    return response.content.strip()


async def maybe_compact(
    messages: list[dict],
    *,
    llm_client,
    model: str,
    last_input_tokens: int = 0,
    keep_recent: int = KEEP_RECENT_MESSAGES,
    trigger_fraction: float = COMPACTION_TRIGGER_FRACTION,
) -> tuple[list[dict], bool]:
    """Compact *messages* in place when nearing the context window.

    Trigger: measured ``last_input_tokens`` when available, otherwise the
    character-based estimate. Returns ``(messages, compacted)``.

    The original opening prompt (index 0) is preserved verbatim; any previous
    summary block at index 1 is replaced so successive compactions stay
    incremental rather than nested.
    """
    window = window_for(model)
    trigger = int(window * trigger_fraction)
    measured = last_input_tokens or estimate_tokens(messages)
    if measured < trigger:
        return messages, False

    cut = find_cut_point(messages, keep_recent=keep_recent)
    if not cut:
        return messages, False

    span = messages[1:cut]
    span_text = render_span_for_summary(span)
    summary = await summarize_span(llm_client, span_text)

    summary_msg = {
        "role": "user",
        "content": (
            f"{SUMMARY_MARKER} — earlier messages were compacted. "
            "This summary replaces them; continue the task from here.\n\n"
            f"{summary}"
        ),
    }
    had_previous_summary = (
        len(messages) > 1 and SUMMARY_MARKER in str(messages[1].get("content", ""))
    )
    if had_previous_summary:
        # Replace in place: the old span occupied [1:cut); index 1 is now the
        # refreshed summary, so drop [2:cut).
        messages[1] = summary_msg
        del messages[2:cut]
    else:
        # Fresh insert shifts everything up one: the span moved to [2:cut+1).
        messages.insert(1, summary_msg)
        del messages[2:cut + 1]
    return messages, True
