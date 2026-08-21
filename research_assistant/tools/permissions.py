"""Permission policy — a built-in PRE_TOOL_USE hook that denies dangerous ops.

Modes (env ``RA_PERMISSION_MODE``):
    off              no checking
    deny_dangerous   block catastrophic commands only (default); normal work
                     (writing files, running python in the workspace) is
                     unaffected.

The policy targets irreversible / system-wide damage — not sandboxing.
True isolation is a separate concern (see docs/plans §8 deferred items).
"""

from __future__ import annotations

import os
import re

from ..kernel.events import AgentEvent, HookVerdict

# Patterns matched against bash/run_python input. Deliberately narrow:
# they must never fire on legitimate research/writing workloads.
_DANGEROUS_PATTERNS: tuple[str, ...] = (
    # *nix filesystem annihilation
    r"rm\s+(-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r)\s+/(\s|$)",       # rm -rf /
    r"rm\s+-[a-z]*r[a-z]*f\s+(~|\$HOME|/etc|/usr|/bin|/var\b)",
    r"mkfs(\.\w+)?\s",
    r"dd\s+if=.*of=/dev/(sd|nvme|hd)",
    r">\s*/dev/sd[a-z]",
    r"chmod\s+-R\s+777\s+/",
    # fork bomb
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
    # Windows destructive commands
    r"\bdel\s+/[sq]\s+[a-zA-Z]:\\\s*$",
    r"\brd\s+/s\s+/q\s+[a-zA-Z]:\\\s*$",
    r"\bformat\s+[a-zA-Z]:",
    r"\bshutdown\s+(/r|/s|-r|-s)",
    r"reg\s+delete\s+HK(LM|CR|U)",
    r"Remove-Item\s+.*-Recurse\s+.*-Force\s+[A-Za-z]:\\(\s|$)",
    r"cipher\s+/w:",
    # remote code exec as root
    r"curl\s+[^\|]*\|\s*(sudo\s+)?(ba)?sh",
    r"wget\s+[^\|]*\|\s*(sudo\s+)?(ba)?sh",
)

_DANGEROUS_RES: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE) for p in _DANGEROUS_PATTERNS
)

_EXEC_TOOLS = frozenset({"bash", "run_python"})


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
        if tool_name not in _EXEC_TOOLS:
            return HookVerdict()

        text = arguments.get("command") or arguments.get("code") or ""
        if not isinstance(text, str):
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
