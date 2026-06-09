"""File operation tools: read, write, edit, glob, grep."""

import os
import re
from pathlib import Path

from ..constants import GREP_MAX_RESULTS, GLOB_MAX_RESULTS, BINARY_EXTENSIONS


async def read_file(file_path: str, offset: int = 0, limit: int = 2000) -> str:
    """Read a file and return its content with line numbers."""
    p = Path(file_path).resolve()
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


async def write_file(file_path: str, content: str) -> str:
    """Write content to a file, creating parent directories if needed."""
    p = Path(file_path).resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


async def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Replace an exact string in a file. old_string must appear exactly once."""
    p = Path(file_path).resolve()
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
