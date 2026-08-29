"""Execution provider seam — where bash/python actually run.

Borrowed from DeepSeek Harness's replaceable execution-world design:
swap the provider and the whole tool family (bash, run_python) moves to a
different execution world (container, remote sandbox) without touching the
tool definitions. Today only the local provider exists; remote/container
providers are the documented extension point.
"""

from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# A+ 阶段 5 / G-4（半解）：子进程环境净化
#
# 模型生成的代码跑在本机子进程里。此前 bash / run_python 直接继承完整
# ``os.environ``——``os.environ["LLM_API_KEY"]`` 一行就能把密钥读走并随
# 工具输出回传给模型。这是一个真实的泄露面，而修复成本极低：执行工具
# 几乎从不需要这些变量。
#
# 这是**净化**而不是沙箱：真正的隔离（容器/受限进程）仍是 ExecProvider
# 的后续扩展点。但把密钥从子进程环境里拿掉，能把"一次提示词注入即可
# 外传全部密钥"降级为"需要先找到密钥落在哪"，收益/成本比极高。
# ---------------------------------------------------------------------------

#: 子进程环境里**必删**的变量名（大小写不敏感，按精确名匹配）。
_SENSITIVE_ENV_KEYS = frozenset({
    "LLM_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "IMAGE_API_KEY", "PARALLEL_API_KEY", "SEMANTIC_SCHOLAR_API_KEY",
    "TAVILY_API_KEY",
})
#: 名称中**包含**这些子串即视为疑似密钥（大小写不敏感）。
#:
#: 为什么是子串而不是前缀：真实世界的密钥名没有统一词位——
#: ``GITHUB_TOKEN`` 以 TOKEN 结尾、``MY_VENDOR_API_KEY`` 的 API_KEY 在中间、
#: ``AWS_SECRET_ACCESS_KEY`` 的 SECRET 也在中间。逐厂商维护清单永远追不全，
#: 子串匹配以极低的误伤成本（被剔除的多半也用不上）换取高覆盖率。
#: 代理设置一并剔除：模型代码经它外联既绕过审计也可能被恶意代理截获。
_SENSITIVE_ENV_SUBSTRINGS = ("API_KEY", "APIKEY", "TOKEN", "SECRET", "PASSWORD", "_PROXY")


def sanitized_exec_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """返回适合交给模型代码子进程的环境变量副本（剔除疑似密钥）。

    Args:
        base: 基底环境；None 表示 ``os.environ`` 的当前快照。

    Returns:
        剔除后的副本。**绝不**原地修改传入的 dict。
    """
    source = dict(os.environ if base is None else base)
    cleaned: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if upper in _SENSITIVE_ENV_KEYS:
            continue
        if any(token in upper for token in _SENSITIVE_ENV_SUBSTRINGS):
            continue
        cleaned[key] = value
    return cleaned


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
