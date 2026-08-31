"""Permission policy — a built-in PRE_TOOL_USE hook that denies dangerous ops.

Modes (env ``RA_PERMISSION_MODE``):
    off              no checking
    deny_dangerous   block catastrophic commands only (default); normal work
                     (writing files, running python in the workspace) is
                     unaffected.

The policy targets irreversible / system-wide damage — not sandboxing.
True isolation is a separate concern (see docs/plans §8 deferred items).

检查面（P1-1 修订）
------------------
黑名单只对**可执行面**生效，不对所有工具一律套用：

* ``bash`` / ``run_python`` —— 匹配 ``command`` / ``code``，这是策略的主战场；
* **未知工具名**（即 MCP 等声明式扩展）—— 拼接全部字符串参数后匹配。扩展是
  外部能力，名字不在本模块已知清单里，默认按「可执行」对待（此前它们被
  ``_EXEC_TOOLS`` 白名单直接跳过，等于完全没有检查）；
* **已知的非执行工具**（``write_file`` / ``edit_file`` / ``apply_patch`` /
  ``verify_citations`` / ``record_research_*`` / 三个只读工具）—— 不匹配。
  对文件内容跑 shell 黑名单会误伤：一篇讲 shell 的论文正文里出现
  ``rm -rf /`` 不该被拦；记台账写库更与命令无关。这些工具的路径安全由
  工作区围栏（``core.safe_resolve``）负责，那是正确的归属层。

注：钩子本身对**每个**工具调用都会触发（agent.py:918 的 PRE_TOOL_USE），
扩展从未被"绕过钩子"——是旧实现的白名单让策略主动跳过了它们。
"""

from __future__ import annotations

import os
import re

from ..kernel.events import AgentEvent, HookVerdict

# Patterns matched against the *executable* surface of a tool call.
# Deliberately narrow: they must never fire on legitimate research/writing
# workloads.
#
# 编写约束（P1-1 修订，逐条都是实测过的绕过点）：
# 1. **不要在盘符/目录后锚结尾**（``$``）。旧的 ``[a-zA-Z]:\\\s*$`` 只挡得住
#    ``del /s /q C:\``，跟任何子目录即失配——``del /s /q C:\Users\Alice``
#    因此全放行。
# 2. **系统目录只拦顶层本身**，不拦其下的深路径。``rm -rf /var`` 是灾难，
#    但 macOS 上 ``rm -rf /var/folders/...`` 是日常清理，误伤代价同样高。
# 3. Windows 的用户/系统目录``任意深度``都拦：``del /s /q`` 递归强删用户
#    数据本身就是策略要挡的那类不可逆操作。
_DANGEROUS_PATTERNS: tuple[str, ...] = (
    # ---- *nix 文件系统毁灭 --------------------------------------------
    # rm -rf 裸根 / 根目录通配（--no-preserve-root 等变体一并覆盖）
    r"rm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)(?:\s+--[a-z-]+)*\s+/(?:\s|$|\*)",
    # rm -rf 家目录（~ 与 $HOME 的多种写法）
    r"rm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)(?:\s+--[a-z-]+)*\s+"
    r"(?:~|\$HOME|\$\{HOME\}|\$\{?HOME\}?)(?:\s|/|$)",
    # rm -rf 系统目录（任意深度）：这些路径归系统所有，删其下任何东西都
    # 是破坏。用 `/` 续接，故 `rm -rf /etc/nginx` 一并拦下。
    r"rm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)(?:\s+--[a-z-]+)*\s+"
    r"/(?:etc|usr|bin|sbin|lib|lib64|boot|dev|proc|sys|root|run|media|mnt"
    r"|opt|srv)(?:\s|/|$)",
    # /home 与 /var **只拦顶层及下一层**：工作区常位于 /home/<user>/...，
    # macOS 的 /var/folders/... 更是日常清理目标——更深路径必须放行。
    #   rm -rf /home            → 拦（顶层）
    #   rm -rf /home/alice      → 拦（用户主目录）
    #   rm -rf /home/a/p/build  → 放行（用户自己的构建产物）
    # 量词必须是 ?（最多一层），不能是 *：否则深路径会被一并拦下。
    r"rm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)(?:\s+--[a-z-]+)*\s+"
    r"/(?:home|var)(?:/[^/\s]+/?)?(?:\s|$)",
    r"mkfs(\.\w+)?\s",
    r"dd\s+if=\S*\s+of=/dev/(sd|nvme|hd|disk|mmcblk|vd)",
    r">\s*/dev/(sd|nvme|hd|disk|mmcblk|vd)",
    r"chmod\s+(-R|--recursive)\s+[0-7]*777\s+/(?:\s|$)",
    r"chown\s+(-R|--recursive)\s+\S+\s+/(?:\s|$)",
    # fork bomb
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
    # ---- Windows 破坏性命令 -------------------------------------------
    # 开关与路径的**先后顺序不固定**（`del /s /q C:\` 与 `del C:\ /s /q`
    # 等价），因此用前瞻断言判定开关、再向后扫路径——早先按「开关在前」
    # 写死的顺序假设漏掉了 `Remove-Item -Path X -Recurse -Force` 这类写法。
    # 裸盘符：del /s /q C:\  （旧规则在此处锚了 $，跟子目录即失效）
    r"\bdel\s+(?=[^\n]*/[sq]\b)[^\n]*[a-zA-Z]:\\?(?:\s|$|')",
    r"\brd\s+(?=[^\n]*/[sq]\b)[^\n]*[a-zA-Z]:\\?(?:\s|$|')",
    # 递归强删系统/用户目录，任意深度（裸盘符规则管不到的一律在此拦下）
    r"\bdel\s+(?=[^\n]*/[sq]\b)[^\n]*[a-zA-Z]:\\"
    r"(?:Windows|Users|Program Files|ProgramData|Documents and Settings)"
    r"(?:\\|\s|$)",
    r"\brd\s+(?=[^\n]*/[sq]\b)[^\n]*[a-zA-Z]:\\"
    r"(?:Windows|Users|Program Files|ProgramData|Documents and Settings)"
    r"(?:\\|\s|$)",
    r"\bformat\s+[a-zA-Z]:",
    r"\bcipher\s+/w:",
    r"\bvssadmin\s+delete\s+shadows",
    r"\bbcdedit\s+/set\s+.*recoveryenabled\s+no",
    r"\btakeown\s+/f\s+\S*\s+/r",
    r"\bicacls\s+.*/grant\s+.*Everyone\s*:\s*F",
    r"\brobocopy\s+.*/MIR",
    r"\bdiskpart\b",
    r"\breg\s+delete\s+HK(LM|CR|CU|U|UY)\b",
    r"\bshutdown\s+(/r|/s|-r|-s)\b",
    # 同样用前瞻解耦顺序：只要出现 -Recurse，路径在前后任一位置都算
    r"\bRemove-Item\s+(?=[^\n]*-Recurse)[^\n]*[A-Za-z]:\\?(?:\s|$|')",
    r"\bRemove-Item\s+(?=[^\n]*-Recurse)[^\n]*[A-Za-z]:\\"
    r"(?:Windows|Users|Program Files|ProgramData)(?:\\|\s|$)",
    # ---- 远程代码执行 --------------------------------------------------
    r"curl\s+[^\|]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b",
    r"wget\s+[^\|]*\|\s*(sudo\s+)?(ba|z|da|k)?sh\b",
    r"curl\s+[^\|]*\|\s*(sudo\s+)?python[0-9.]*",
    r"wget\s+[^\|]*\|\s*(sudo\s+)?python[0-9.]*",
)

_DANGEROUS_RES: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _DANGEROUS_PATTERNS
)

#: 明确只读的工具：既无副作用，也不需要跑命令黑名单。
_READ_ONLY_TOOLS = frozenset({"read_file", "glob_files", "grep_search"})

#: 已知的非执行工具：路径安全归工作区围栏，内容不该被 shell 黑名单误伤。
#: （write_file / edit_file / apply_patch 写的是文件内容；
#:   verify_citations 走网络；record_research_* / list_research_ledger 写库。）
_KNOWN_NON_EXEC_TOOLS = frozenset({
    "write_file", "edit_file", "apply_patch", "verify_citations",
    "record_research_claim", "record_research_evidence",
    "record_research_item", "record_research_decision",
    "list_research_ledger",
})

#: 直接携带可执行载荷的内建工具 → 取对应的参数键。
_EXEC_ARG_KEYS = {"bash": ("command",), "run_python": ("code",)}


def _scan_text(tool_name: str, arguments: dict) -> str:
    """取出待匹配的文本；返回空串表示该工具不在检查面内。

    - bash / run_python：取 command / code；
    - 只读与已知非执行工具：不检查（返回空串）；
    - **其余一律视为可执行面**（MCP 扩展等未知工具）：拼接全部字符串参数。
      这是 P1-1 的关键扩围——旧实现用白名单把未知工具完全排除在外，
      接入 MCP 服务器后任意远端工具调用都不受任何拦截。
    """
    keys = _EXEC_ARG_KEYS.get(tool_name)
    if keys is not None:
        for key in keys:
            value = arguments.get(key)
            if isinstance(value, str):
                return value
        return ""
    if tool_name in _READ_ONLY_TOOLS or tool_name in _KNOWN_NON_EXEC_TOOLS:
        return ""
    parts: list[str] = []
    for value in arguments.values():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (list, tuple)):
            parts.extend(str(item) for item in value if isinstance(item, str))
    return "\n".join(parts)


class PermissionPolicy:
    """Decides whether a tool call may proceed."""

    def __init__(self, mode: str = "deny_dangerous",
                 extra_patterns: list[str] | None = None) -> None:
        self.mode = mode if mode in ("off", "deny_dangerous") else "deny_dangerous"
        self._patterns = _DANGEROUS_RES
        if extra_patterns:
            self._patterns = self._patterns + tuple(
                re.compile(p, re.IGNORECASE) for p in extra_patterns
            )

    def check(self, tool_name: str, arguments: dict) -> HookVerdict:
        if self.mode == "off":
            return HookVerdict()

        text = _scan_text(tool_name, arguments)
        if not text:
            return HookVerdict()
        for pattern in self._patterns:
            if pattern.search(text):
                return HookVerdict(
                    allowed=False,
                    reason=(
                        f"matches dangerous-operation pattern "
                        f"`{pattern.pattern}` (policy={self.mode})"
                    ),
                )
        return HookVerdict()

    async def as_hook(self, event: AgentEvent) -> HookVerdict | None:
        """Adapter for HookBus PRE_TOOL_USE."""
        verdict = self.check(event.tool_name, event.payload.get("arguments", {}))
        return verdict if not verdict.allowed else None


def policy_from_env() -> PermissionPolicy | None:
    mode = os.getenv("RA_PERMISSION_MODE", "deny_dangerous").strip().lower()
    if mode == "off":
        return None
    return PermissionPolicy(mode=mode)
