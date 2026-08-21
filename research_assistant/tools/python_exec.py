"""Python code execution tool."""

import asyncio
import sys
import uuid
from pathlib import Path

from ..constants import OUTPUT_TRUNCATION_HALF, OUTPUT_TRUNCATION_LIMIT
from .bash import _kill_process


async def run_python(
    code: str,
    timeout: int = 120,
    cwd: str = ".",
) -> str:
    """Execute Python code and return stdout + stderr.

    Writes the code to a temporary file in cwd and runs it with the
    current Python interpreter (inheriting venv site-packages).

    Args:
        code: Python source code to execute.
        timeout: Timeout in seconds.
        cwd: Working directory for execution.
    """
    temp_name = f"_ra_exec_{uuid.uuid4().hex[:8]}.py"
    temp_path = Path(cwd) / temp_name

    try:
        temp_path.write_text(code, encoding="utf-8")
    except Exception as e:
        return f"Error writing temp file: {e}"

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(temp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        if proc is not None:
            await _kill_process(proc)
        return f"Error: Python code timed out after {timeout} seconds"
    except FileNotFoundError:
        return f"Error: Python interpreter not found: {sys.executable}"
    except Exception as e:
        if proc is not None:
            await _kill_process(proc)
        return f"Error executing Python code: {e}"
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass

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
