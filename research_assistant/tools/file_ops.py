"""File operation tools: read, write, edit, glob, grep."""

import re
from pathlib import Path

from ..constants import BINARY_EXTENSIONS, GLOB_MAX_RESULTS, GREP_MAX_RESULTS
from ..core import safe_resolve


async def read_file(
    file_path: str,
    offset: int = 0,
    limit: int = 2000,
    sandbox: str | None = None,
) -> str:
    """Read a file and return its content with line numbers.

    Args:
        file_path: Absolute or relative path to the file.
        offset: Line number to start reading from (0-based).
        limit: Maximum number of lines to read.
        sandbox: If set, restricts access to this directory tree.
    """
    p = Path(file_path)
    if sandbox:
        try:
            p = safe_resolve(p, Path(sandbox))
        except ValueError as e:
            return f"Error: {e}"
    else:
        p = p.resolve()

    if not p.exists():
        return f"Error: File does not exist: {file_path}"
    if p.is_dir():
        return f"Error: Path is a directory, not a file: {file_path}"

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"

    lines = text.splitlines()
    total = len(lines)
    selected = lines[offset: offset + limit]

    numbered = []
    for i, line in enumerate(selected, start=offset + 1):
        numbered.append(f"{i}\t{line}")

    result = "\n".join(numbered)
    if offset + limit < total:
        result += f"\n\n... ({total - offset - limit} more lines)"
    return result


async def write_file(
    file_path: str,
    content: str,
    sandbox: str | None = None,
) -> str:
    """Write content to a file, creating parent directories if needed.

    Args:
        file_path: Absolute or relative path to the file.
        content: The content to write.
        sandbox: If set, restricts writes to this directory tree.
    """
    p = Path(file_path)
    if sandbox:
        try:
            # Resolve against sandbox — parent must also be inside sandbox
            sandbox_path = Path(sandbox)
            resolved_parent = safe_resolve(Path(file_path).parent, sandbox_path)
            p = resolved_parent / Path(file_path).name
        except ValueError as e:
            return f"Error: {e}"
    else:
        p = p.resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    sandbox: str | None = None,
) -> str:
    """Replace an exact string in a file. old_string must appear exactly once.

    Args:
        file_path: Absolute or relative path to the file.
        old_string: The exact text to find and replace.
        new_string: The text to replace it with.
        sandbox: If set, restricts edits to this directory tree.
    """
    p = Path(file_path)
    if sandbox:
        try:
            p = safe_resolve(p, Path(sandbox))
        except ValueError as e:
            return f"Error: {e}"
    else:
        p = p.resolve()

    if not p.exists():
        return f"Error: File does not exist: {file_path}"

    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file: {e}"

    count = text.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {file_path}"
    if count > 1:
        return f"Error: old_string appears {count} times in {file_path}. Must be unique."

    new_text = text.replace(old_string, new_string, 1)
    try:
        p.write_text(new_text, encoding="utf-8")
        return f"Successfully edited {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def glob_files(pattern: str, path: str = ".") -> str:
    """Find files matching a glob pattern."""
    base = Path(path)
    if not base.exists():
        return f"Error: Directory does not exist: {path}"

    matches = sorted(base.glob(pattern))
    if not matches:
        return f"No files matching '{pattern}' in {path}"

    lines = [str(m) for m in matches[:GLOB_MAX_RESULTS]]
    result = "\n".join(lines)
    if len(matches) > GLOB_MAX_RESULTS:
        result += f"\n\n... ({len(matches) - GLOB_MAX_RESULTS} more matches)"
    return result


async def grep_search(pattern: str, path: str = ".", glob: str = "") -> str:
    """Search for a regex pattern in files."""
    base = Path(path)
    if not base.exists():
        return f"Error: Path does not exist: {path}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    results = []

    if base.is_file():
        files = [base]
    else:
        if glob:
            files = sorted(base.rglob(glob))
        else:
            files = sorted(base.rglob("*"))

    for fp in files:
        if not fp.is_file():
            continue
        if fp.suffix in BINARY_EXTENSIONS:
            continue
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                results.append(f"{fp}:{i}: {line.rstrip()}")
                if len(results) >= GREP_MAX_RESULTS:
                    break
        if len(results) >= GREP_MAX_RESULTS:
            break

    if not results:
        return f"No matches for pattern '{pattern}'"
    output = "\n".join(results)
    if len(results) >= GREP_MAX_RESULTS:
        output += "\n\n... (results truncated)"
    return output
