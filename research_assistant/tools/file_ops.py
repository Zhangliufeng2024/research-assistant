"""File operation tools: read, write, edit, glob, grep."""

import asyncio
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
    write_anchor: str | None = None,
) -> str:
    """Write content to a file, creating parent directories if needed.

    R12 P2 写入归巢：``write_anchor`` 设置时，**相对路径一律解析到
    ``<anchor>/<relpath>``**（确定性落地——产物进产物目录，且会话永不
    静默覆写共享文件；修改既有共享文件走 edit_file，它仍按 sandbox 根
    解析）。无 anchor 时相对路径按 sandbox 根解析（生产中进程 CWD=根的
    旧语义，此处不再依赖进程状态）。sandbox 内绝对路径原样写入。
    成功回执回显最终绝对路径，供模型后续读写与前端 files 启发式定位。

    Args:
        file_path: Absolute or relative path to the file.
        content: The content to write.
        sandbox: If set, restricts writes to this directory tree.
        write_anchor: 归巢目录（相对路径的确定性落点），须位于 sandbox 内。
    """
    p = Path(file_path)
    if sandbox:
        try:
            # Resolve against sandbox — parent must also be inside sandbox
            sandbox_path = Path(sandbox)
            raw = Path(file_path)
            if not raw.is_absolute():
                base = Path(write_anchor) if write_anchor is not None else sandbox_path
                raw = base / raw
            resolved_parent = safe_resolve(raw.parent, sandbox_path)
            p = resolved_parent / raw.name
        except ValueError as e:
            return f"Error: {e}"
    else:
        p = p.resolve()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {p}"
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

    # 目录遍历可能很重（海量文件/OneDrive 按需文件）：放线程池，
    # 避免在 async def 里同步 rglob 卡死事件循环——那会让所有 WS/REST
    # 一起失联（R9 任务页「无法建立连接」的候选共因）。
    matches = await asyncio.to_thread(lambda: sorted(base.glob(pattern)))
    if not matches:
        return f"No files matching '{pattern}' in {path}"

    lines = [str(m) for m in matches[:GLOB_MAX_RESULTS]]
    result = "\n".join(lines)
    if len(matches) > GLOB_MAX_RESULTS:
        result += f"\n\n... ({len(matches) - GLOB_MAX_RESULTS} more matches)"
    return result


def _grep_scan(
    regex: re.Pattern, files: list[Path], results: list[str]
) -> None:
    """同步扫描实现（在线程池中执行）：逐文件读入并按行匹配。"""
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
                    return
        if len(results) >= GREP_MAX_RESULTS:
            return


async def grep_search(pattern: str, path: str = ".", glob: str = "") -> str:
    """Search for a regex pattern in files."""
    base = Path(path)
    if not base.exists():
        return f"Error: Path does not exist: {path}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    if base.is_file():
        files: list[Path] = [base]
    else:
        if glob:
            files = await asyncio.to_thread(lambda: sorted(base.rglob(glob)))
        else:
            files = await asyncio.to_thread(lambda: sorted(base.rglob("*")))

    results: list[str] = []
    await asyncio.to_thread(_grep_scan, regex, files, results)

    if not results:
        return f"No matches for pattern '{pattern}'"
    output = "\n".join(results)
    if len(results) >= GREP_MAX_RESULTS:
        output += "\n\n... (results truncated)"
    return output
