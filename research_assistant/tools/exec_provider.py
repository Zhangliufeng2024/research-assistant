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

    # workspace_root 为加性扩展（R12 P1）：冻结执行器需要工作区根来注入
    # WS 常量；不能从 cwd 推导（会话模式下 cwd 是产物目录）。默认 None，
    # 旧实现可忽略。
    async def run_python(
        self, code: str, timeout: int, cwd: str,
        workspace_root: str | None = None,
    ) -> str: ...


class LocalExecProvider:
    """Default provider: delegates to the existing local implementations."""

    async def run_bash(self, command: str, timeout: int, cwd: str) -> str:
        from .bash import run_bash

        return await run_bash(command=command, timeout=timeout, cwd=cwd)

    async def run_python(
        self, code: str, timeout: int, cwd: str,
        workspace_root: str | None = None,
    ) -> str:
        from .python_exec import run_python

        return await run_python(
            code=code, timeout=timeout, cwd=cwd,
            workspace_root=workspace_root,
        )
