"""Bash command execution tool."""

import asyncio
import os
import sys

from ..constants import OUTPUT_TRUNCATION_LIMIT, OUTPUT_TRUNCATION_HALF


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
