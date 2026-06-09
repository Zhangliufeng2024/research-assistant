"""Human-readable formatting for real-time agent activity display."""

from pathlib import Path

from .models import TokenUsage
from .constants import DISPLAY_TRUNCATION_LENGTH, DISPLAY_TOKEN_THRESHOLD


def _is_error(result: str) -> bool:
    """Check if a tool result indicates an error."""
    return result.startswith("Error") or result.startswith("Exit code:")


def _truncate(text: str, max_len: int = DISPLAY_TRUNCATION_LENGTH) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


def _relative_path(file_path: str) -> str:
    """Try to shorten a file path for display."""
    try:
        return str(Path(file_path).relative_to(Path.cwd()))
    except (ValueError, RuntimeError):
        name = Path(file_path).name
        parent = Path(file_path).parent.name
        if parent:
            return f"{parent}/{name}"
        return name


def format_tool_start(name: str, args: dict) -> str:
    """Format a tool-call announcement shown BEFORE execution."""
    if name == "write_file":
        fp = _relative_path(args.get("file_path", "?"))
        return f"✦ Write: {fp}"

    if name == "read_file":
        fp = _relative_path(args.get("file_path", "?"))
        return f"✦ Read: {fp}"

    if name == "edit_file":
        fp = _relative_path(args.get("file_path", "?"))
        return f"✦ Edit: {fp}"

    if name == "bash":
        cmd = _truncate(args.get("command", "?"))
        return f"✦ Bash: {cmd}"

    if name == "run_python":
        code = args.get("code", "")
        lines = code.count("\n") + 1
        return f"✦ Python: {lines} line{'s' if lines != 1 else ''}"

    if name == "glob_files":
        pattern = args.get("pattern", "?")
        return f"✦ Glob: {pattern}"

    if name == "grep_search":
        pattern = args.get("pattern", "?")
        return f'✦ Grep: "{pattern}"'

    return f"✦ {name}"


def format_tool_result_tag(result: str) -> str:
    """Format a short tag shown AFTER tool execution completes."""
    if _is_error(result):
        return " [ERR]"
    return " [OK]"


def format_status_line(turn: int, elapsed: float, usage: TokenUsage) -> str:
    """Format a turn/time/token status line."""
    total = usage.input_tokens + usage.output_tokens
    if total >= DISPLAY_TOKEN_THRESHOLD:
        token_str = f"{total:,}"
    else:
        token_str = str(total)
    return f"[Turn {turn} | {elapsed:.0f}s | {token_str} tokens]"
