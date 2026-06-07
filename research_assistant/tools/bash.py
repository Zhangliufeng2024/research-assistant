"""Bash command execution tool."""

import asyncio
import os
import sys
from typing import Optional


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

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ},
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
        return f"Error: Command timed out after {timeout} seconds"
    except FileNotFoundError:
        return f"Error: Shell not found: {shell}"
    except Exception as e:
        return f"Error executing command: {e}"

    output_parts = []
    if stdout:
        output_parts.append(stdout.decode("utf-8", errors="replace"))
    if stderr:
        output_parts.append(stderr.decode("utf-8", errors="replace"))

    result = "\n".join(output_parts).strip()

    if proc.returncode != 0:
        result = f"Exit code: {proc.returncode}\n{result}"

    if len(result) > 30000:
        result = result[:15000] + "\n\n... (output truncated) ...\n\n" + result[-15000:]

    return result or "(no output)"
