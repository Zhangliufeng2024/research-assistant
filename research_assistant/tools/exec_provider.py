"""Execution provider seam — where bash/python actually run.

Borrowed from DeepSeek Harness's replaceable execution-world design:
swap the provider and the whole tool family (bash, run_python) moves to a
different execution world (container, remote sandbox) without touching the
tool definitions. Today only the local provider exists; remote/container
providers are the documented extension point.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ExecProvider(Protocol):
    async def run_bash(self, command: str, timeout: int, cwd: str) -> str: ...

    async def run_python(self, code: str, timeout: int, cwd: str) -> str: ...


class LocalExecProvider:
    """Default provider: delegates to the existing local implementations."""

    async def run_bash(self, command: str, timeout: int, cwd: str) -> str:
        from .bash import run_bash

        return await run_bash(command=command, timeout=timeout, cwd=cwd)

    async def run_python(self, code: str, timeout: int, cwd: str) -> str:
        from .python_exec import run_python

        return await run_python(code=code, timeout=timeout, cwd=cwd)
