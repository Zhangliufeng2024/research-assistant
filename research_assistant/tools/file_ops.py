"""File operation tools: read, write, edit, glob, grep."""

import asyncio
import re
from pathlib import Path

from ..constants import BINARY_EXTENSIONS, GLOB_MAX_RESULTS, GREP_MAX_RESULTS
from ..core import safe_resolve


def _unquote_path(file_path: str) -> str:
    """剥掉模型传入路径两端可能自带的包裹引号。

    A+ 修复（路径含空格工作区）：外置产物指针、dir 输出等都可能让模型以
    `"D:\\vscode files\\...\\x.txt"` 的带引号形态回传路径——Windows 工作区
    路径含空格极其常见，引号原样进 ``safe_resolve`` 会被当成文件名的一部分，
    于是「读得到却写不进」这类幽灵故障。只剥**成对**的包裹引号，路径中间
    的引号（合法文件名字符）不受影响。
    """
    text = str(file_path).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


async def read_file(
    file_path: str,
    offset: int = 0,
    limit: int = 2000,
    sandbox: str | None = None,
    write_anchor: str | None = None,
) -> str:
    """Read a file and return its content with line numbers.

    Args:
        file_path: Absolute or relative path to the file.
        offset: Line number to start reading from (0-based).
        limit: Maximum number of lines to read.
        sandbox: If set, restricts access to this directory tree.
        write_anchor: 双轨回退（修复 G）：相对路径在 sandbox 根下不存在而
            anchor 下存在时读 anchor 副本；绝对路径行为完全不变。
    """
    raw = Path(_unquote_path(file_path))
    relative = not raw.is_absolute()
    p: Path
    if sandbox:
        try:
            sandbox_path = Path(sandbox)
            p = safe_resolve(
                raw if not relative else sandbox_path / raw,
                sandbox_path,
            )
            # 相对路径双轨回退：根下没有、anchor 下有 → 读 anchor 副本，
            # 避免「写进 anchor、读到根」的会话内不一致。
            if relative and write_anchor is not None and not p.exists():
                anchor_candidate = safe_resolve(
                    Path(write_anchor) / raw, sandbox_path)
                if anchor_candidate.exists():
                    p = anchor_candidate
        except ValueError as e:
            return f"Error: {e}"
    else:
        p = raw.resolve()

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


#: Windows 保留设备名（修复 H）：整名匹配——con.txt 拒绝、concrete.md 放行。
_WINDOWS_RESERVED_RE = re.compile(
    r"(aux|con|prn|nul|com[1-9]|lpt[1-9])(\..*)?$",
    re.IGNORECASE,
)


def _reject_windows_hazard(file_path: str) -> str | None:
    """Windows 特有非法写入目标校验；返回拒绝文案，合法返回 None（修复 H）。

    - 保留设备名（CON/NUL/AUX/COM1-9/LPT1-9）：即便带扩展名，写入也会被
      系统重定向到设备吞掉内容（静默数据丢失），必须拒绝；
    - 盘符之外的冒号：NTFS 备用数据流（ADS）形态（file:stream），不属于
      普通文件语义，拒绝以防绕过版本跟踪与审阅。

    调用面（P1-4 收敛说明，**全部三处都在本文件这一个实现上**）：
    - ``write_file`` / ``edit_file`` / ``apply_patch`` —— 工具入口，命中即
      **拒绝**（返回 Error 文案给模型）；
    - ``web/chat.py:_safe_upload_name`` —— 附件文件名消毒，命中则**降级**
      （名字加 ``_`` 前缀）而非拒绝：上传是用户主动操作，降级体验更好。
    跨模块 import 私有名是因为两者需要**同一套判定规则**；这里的语义差异
    （拒绝 vs 降级）是调用方的策略，不该复制成两份实现。
    """
    raw = Path(_unquote_path(file_path))
    name = raw.name
    if _WINDOWS_RESERVED_RE.fullmatch(name):
        return (
            f"Error: '{name}' 是 Windows 保留设备名，无法作为普通文件写入"
            "（内容会被设备吞掉导致静默丢失）。请换一个文件名。"
        )
    if ":" in file_path:
        normalized = file_path.replace("\\", "/")
        head = normalized.split("/", 1)[0]
        # 仅允许首段出现一次盘符冒号（D:\... / D:/...）；其余位置或数量的
        # 冒号均为 ADS 形态。
        colon_ok = (
            len(head) >= 2
            and head[1] == ":"
            and head.count(":") == 1
            and normalized.count(":") == 1
        )
        if not colon_ok:
            return (
                "Error: 文件路径含盘符之外的冒号（疑似 NTFS 备用数据流）:"
                f" {file_path}。请使用普通文件路径。"
            )
    return None


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
    hazard = _reject_windows_hazard(file_path)
    if hazard is not None:
        return hazard

    p = Path(file_path)
    if sandbox:
        try:
            # Resolve against sandbox — parent must also be inside sandbox
            sandbox_path = Path(sandbox)
            raw = Path(_unquote_path(file_path))
            if not raw.is_absolute():
                base = Path(write_anchor) if write_anchor is not None else sandbox_path
                raw = base / raw
            # A+ 阶段 1 / F-5：对**完整路径** resolve，与 read_file /
            # edit_file / glob / grep 保持同一口径。
            #
            # 修复前只 resolve 了父目录，再把原始文件名裸拼回去
            # （`resolved_parent / raw.name`）。若工作区内存在指向沙箱外
            # 的符号链接（用户自己的软链、或 bash 工具先建一个），
            # resolved_parent 的校验会通过，随后 write_text 沿链接写出去
            # ——路径围栏被绕过。读写口径不一致本身即证明这是遗漏而非设计。
            p = safe_resolve(raw, sandbox_path)
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
    write_anchor: str | None = None,
) -> str:
    """Replace an exact string in a file. old_string must appear exactly once.

    Args:
        file_path: Absolute or relative path to the file.
        old_string: The exact text to find and replace.
        new_string: The text to replace it with.
        sandbox: If set, restricts edits to this directory tree.
        write_anchor: anchor 优先存在性（修复 G）：相对路径在 anchor 下存在
            时编辑 anchor 副本（与 write_file 同一落点），否则退回 sandbox 根
            （共享文件编辑兼容）；绝对路径行为完全不变。
    """
    raw = Path(_unquote_path(file_path))
    # P1-4：edit 通道此前漏了 Windows 危险名校验——write_file 与 apply_patch
    # 都在入口处拦（CON/NUL 等保留设备名、NTFS ADS 冒号路径），唯独 edit_file
    # 没有，模型可以用 edit 绕过这两个通道的校验写设备文件。必须在 resolve
    # 之前拦：保留设备名即便带扩展名也会被系统重定向吞掉内容。
    hazard = _reject_windows_hazard(file_path)
    if hazard is not None:
        return hazard
    relative = not raw.is_absolute()
    p: Path
    if sandbox:
        try:
            sandbox_path = Path(sandbox)
            if not relative:
                p = safe_resolve(raw, sandbox_path)
            else:
                p = safe_resolve(sandbox_path / raw, sandbox_path)
                if write_anchor is not None:
                    anchor_candidate = safe_resolve(
                        Path(write_anchor) / raw, sandbox_path)
                    if anchor_candidate.exists():
                        p = anchor_candidate
        except ValueError as e:
            return f"Error: {e}"
    else:
        p = raw.resolve()

    if not p.exists():
        return f"Error: File does not exist: {file_path}"

    try:
        # errors="replace"：GBK 等存量编码文件可编不可崩（修复 G）
        text = p.read_text(encoding="utf-8", errors="replace")
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


def _resolve_edit_target(
    file_path: str,
    sandbox: str | None,
    write_anchor: str | None,
) -> tuple[Path | None, str | None]:
    """Resolve an edit target path with the same dual-track anchor semantics as
    :func:`edit_file` (修复 G 口径一致).

    Returns ``(path, None)`` on success or ``(None, error)`` when resolution
    fails / escapes the sandbox. Kept as a pure helper so ``apply_patch`` can
    reuse the exact same resolution rule without disturbing the fully-tested
    :func:`edit_file`.
    """
    raw = Path(_unquote_path(file_path))
    relative = not raw.is_absolute()
    p: Path
    if sandbox:
        try:
            sandbox_path = Path(sandbox)
            if not relative:
                p = safe_resolve(raw, sandbox_path)
            else:
                p = safe_resolve(sandbox_path / raw, sandbox_path)
                if write_anchor is not None:
                    anchor_candidate = safe_resolve(
                        Path(write_anchor) / raw, sandbox_path)
                    if anchor_candidate.exists():
                        p = anchor_candidate
        except ValueError as e:
            return None, f"Error: {e}"
    else:
        p = raw.resolve()
    return p, None


async def apply_patch(
    patches: list[dict],
    sandbox: str | None = None,
    write_anchor: str | None = None,
) -> str:
    """Apply a batch of exact-replacement edits across multiple files atomically.

    ``patches`` is a list of ``{"file_path", "old_string", "new_string"}``.
    Every ``old_string`` must match **exactly once** in its target file,
    mirroring :func:`edit_file`'s uniqueness contract.

    **Atomicity**: all targets are resolved and *validate-and-read* in a first
    pass; only if every patch in every file is satisfiable are the new contents
    actually written. If any patch fails validation the whole batch is reported
    as failed and **no file is modified** (no partial application).

    Multiple patches may target the same file; they are applied in order within
    that file (sequence matters, mirroring a diff file's hunks).
    """
    if not isinstance(patches, list) or len(patches) == 0:
        return "Error: apply_patch requires a non-empty list of patches"

    # ---- Pass 1: validate structure + resolve + read with uniqueness check ----
    # plan: list[(path, orig_bytes, new_text)] on success; (path, error) on failure
    plan: list[tuple[Path, bytes, str]] = []
    by_file: dict[str, list[dict]] = {}
    for i, patch in enumerate(patches):
        if not isinstance(patch, dict):
            return f"Error: apply_patch patch #{i} is not an object"
        file_path = patch.get("file_path")
        old_string = patch.get("old_string")
        new_string = patch.get("new_string")
        if not isinstance(file_path, str) or not isinstance(old_string, str) \
                or not isinstance(new_string, str):
            return (
                f"Error: apply_patch patch #{i} requires string fields "
                f"'file_path', 'old_string', 'new_string'"
            )
        hazard = _reject_windows_hazard(file_path)
        if hazard is not None:
            return f"Error: apply_patch patch #{i}: {hazard}"
        by_file.setdefault(file_path, []).append(
            {"old": old_string, "new": new_string}
        )

    for file_path, file_patches in by_file.items():
        target, err = _resolve_edit_target(file_path, sandbox, write_anchor)
        if err is not None:
            return f"Error: apply_patch {file_path}: {err}"
        if target is None or not target.exists():
            return f"Error: apply_patch File does not exist: {file_path}"
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Error: apply_patch reading {file_path}: {e}"
        new_text = text
        for p in file_patches:
            count = new_text.count(p["old"])
            if count == 0:
                return (
                    f"Error: apply_patch {file_path}: old_string not found "
                    f"(patch {p['old'][:40]!r})"
                )
            if count > 1:
                return (
                    f"Error: apply_patch {file_path}: old_string appears "
                    f"{count} times; must be unique"
                )
            new_text = new_text.replace(p["old"], p["new"], 1)
        plan.append((target, text.encode("utf-8", errors="replace"), new_text))

    # ---- Pass 2: all validated — write them all ----
    for target, _orig, new_text in plan:
        try:
            target.write_text(new_text, encoding="utf-8")
        except Exception as e:
            return f"Error: apply_patch writing {target}: {e}"

    return f"Successfully applied {sum(len(v) for v in by_file.values())} edit(s) across {len(plan)} file(s)"


async def glob_files(
    pattern: str,
    path: str = ".",
    sandbox: str | None = None,
) -> str:
    """Find files matching a glob pattern, optionally inside *sandbox*."""
    base = Path(path)
    if sandbox:
        try:
            sandbox_path = Path(sandbox)
            base = safe_resolve(
                base if base.is_absolute() else sandbox_path / base,
                sandbox_path,
            )
        except ValueError as e:
            return f"Error: {e}"
    else:
        base = base.resolve()
    if not base.exists():
        return f"Error: Directory does not exist: {path}"

    # 目录遍历可能很重（海量文件/OneDrive 按需文件）：放线程池，
    # 避免在 async def 里同步 rglob 卡死事件循环——那会让所有 WS/REST
    # 一起失联（R9 任务页「无法建立连接」的候选共因）。
    # 工程债：`sorted(base.glob("**/*"))` 会一次性物化全部匹配（含
    # node_modules 时数十万 Path）。改为有界收集——到上限即停再排序，
    # 截断语义不变（列表本就只展示前 GLOB_MAX_RESULTS 个）。
    def _bounded_glob() -> list[Path]:
        out: list[Path] = []
        for match in base.glob(pattern):
            out.append(match)
            if len(out) >= GLOB_MAX_RESULTS:
                break
        return sorted(out)

    matches = await asyncio.to_thread(_bounded_glob)
    if sandbox:
        safe_matches: list[Path] = []
        for match in matches:
            try:
                safe_matches.append(safe_resolve(match, Path(sandbox)))
            except ValueError:
                # Do not expose paths outside the configured workspace. A
                # pattern may contain ``..`` or traverse an external symlink.
                continue
        matches = safe_matches
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


async def grep_search(
    pattern: str,
    path: str = ".",
    glob: str = "",
    sandbox: str | None = None,
) -> str:
    """Search for a regex pattern in files, optionally inside *sandbox*."""
    base = Path(path)
    if sandbox:
        try:
            sandbox_path = Path(sandbox)
            base = safe_resolve(
                base if base.is_absolute() else sandbox_path / base,
                sandbox_path,
            )
        except ValueError as e:
            return f"Error: {e}"
    else:
        base = base.resolve()
    if not base.exists():
        return f"Error: Path does not exist: {path}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    if base.is_file():
        files: list[Path] = [base]
    else:
        # 工程债：有界收集替代 `sorted(base.rglob(...))` 全量物化；上限
        # 取结果上限的 10 倍（至少 2000），命中后 _grep_scan 自停。极端
        # 病理场景（前 2000 个文件零命中、其后才有）会少报，可接受——
        # 原实现的一次性物化在巨型目录下会 OOM，代价不成比例。
        def _bounded_rglob(pattern: str) -> list[Path]:
            cap = max(GREP_MAX_RESULTS * 10, 2000)
            out: list[Path] = []
            for match in base.rglob(pattern):
                out.append(match)
                if len(out) >= cap:
                    break
            return sorted(out)

        files = await asyncio.to_thread(_bounded_rglob, glob or "*")

    if sandbox:
        safe_files: list[Path] = []
        for match in files:
            try:
                safe_files.append(safe_resolve(match, Path(sandbox)))
            except ValueError:
                continue
        files = safe_files

    results: list[str] = []
    await asyncio.to_thread(_grep_scan, regex, files, results)

    if not results:
        return f"No matches for pattern '{pattern}'"
    output = "\n".join(results)
    if len(results) >= GREP_MAX_RESULTS:
        output += "\n\n... (results truncated)"
    return output
