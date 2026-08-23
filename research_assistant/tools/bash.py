"""Bash command execution tool."""

import asyncio
import os
import re
import sys

from ..constants import OUTPUT_TRUNCATION_HALF, OUTPUT_TRUNCATION_LIMIT

#: 冻结态拦截的可执行名（小写、去 .exe；python* 前缀另行匹配）。
_PY_INVOKABLE = frozenset({"python", "python3", "py", "pip", "pip3"})

_FROZEN_PY_GUARD_MSG = (
    "[打包环境] 本机没有独立 Python，无法在 bash 里执行 python/pip 命令——"
    "sys.executable 是本应用自身，启动它会重启整个桌面应用。\n"
    "请改用：\n"
    "- Python 代码 / matplotlib 画图：run_python 工具（内置 numpy/pandas/matplotlib）\n"
    "- 运行 .py 脚本文件：run_python 内调用 run_script(绝对路径, argv=[...])"
)

_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SEG_SPLIT_RE = re.compile(r"&&|\|\||[|&;]")


def _segments(command: str) -> list[str]:
    """按 shell 操作符切分命令（&& || | & ;），供逐段检查。"""
    return [seg.strip() for seg in _SEG_SPLIT_RE.split(command) if seg.strip()]


def _is_python_invocation(segment: str) -> bool:
    """判断一个命令段是否在调用 python/pip（跳过前导 KEY=VALUE 赋值）。"""
    tokens = segment.split()
    i = 0
    while i < len(tokens) and _ENV_ASSIGN_RE.match(tokens[i]):
        i += 1
    if i >= len(tokens):
        return False
    exe = os.path.basename(tokens[i]).lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    if exe in _PY_INVOKABLE:
        return True
    # 覆盖 python3.12 之类带版本号的写法（但不误伤 ipython 等）
    return exe.startswith("python")


async def _kill_process(proc: asyncio.subprocess.Process) -> None:
    """Terminate a subprocess, escalating to kill if necessary."""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
    except ProcessLookupError:
        pass


async def run_bash(
    command: str,
    timeout: int = 120,
    cwd: str = ".",
) -> str:
    """Execute a bash command and return stdout + stderr.

    Args:
        command: The shell command to execute.
        timeout: Timeout in seconds.
        cwd: Working directory for the command.
    """
    # R12 P1/A4：冻结态没有独立 Python——python/pip 调用只会把应用 exe
    # 再启动一遍（目标机「目录不存在」弹窗的直接成因）。逐段检查复合命令，
    # 命中即不 spawn、直接给出替代路径指引。
    if getattr(sys, "frozen", False) and any(
        _is_python_invocation(seg) for seg in _segments(command)
    ):
        return _FROZEN_PY_GUARD_MSG

    shell = "/bin/bash"
    if sys.platform == "win32":
        shell = os.environ.get("COMSPEC", "cmd.exe")
        args = [shell, "/c", command]
    else:
        if not os.path.exists(shell):
            shell = "/bin/sh"
        args = [shell, "-c", command]

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        if proc is not None:
            await _kill_process(proc)
        return f"Error: Command timed out after {timeout} seconds"
    except FileNotFoundError:
        return f"Error: Shell not found: {shell}"
    except Exception as e:
        if proc is not None:
            await _kill_process(proc)
        return f"Error executing command: {e}"

    output_parts = []
    if stdout:
        output_parts.append(stdout.decode("utf-8", errors="replace"))
    if stderr:
        output_parts.append(stderr.decode("utf-8", errors="replace"))

    result = "\n".join(output_parts).strip()

    if proc.returncode != 0:
        result = f"Exit code: {proc.returncode}\n{result}"

    if len(result) > OUTPUT_TRUNCATION_LIMIT:
        result = (
            result[:OUTPUT_TRUNCATION_HALF]
            + "\n\n... (output truncated) ...\n\n"
            + result[-OUTPUT_TRUNCATION_HALF:]
        )

    return result or "(no output)"
