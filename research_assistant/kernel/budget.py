"""Budget guard: hard caps on tokens, cost, turns, and wall-clock time.

The agent loop consults :class:`BudgetGuard` before every LLM call. A hard
breach raises :class:`BudgetExceededError`, which the loop converts into a
graceful stop (state is saved; artifacts written so far are kept).

Environment variables:
    RA_MAX_COST_USD      float  Hard spend cap in USD (0/absent = unlimited)
    RA_MAX_TOKENS        int    Cap on total tokens (in+out, cache excluded)
    RA_MAX_TURNS         int    Max LLM call rounds
    RA_MAX_WALL_SECONDS  float  Max wall-clock seconds for the run

Prices are approximate USD per million tokens; unknown models are priced at
zero with a warning so cost tracking degrades gracefully instead of lying.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from ..llm.base import LLMResponse

#: USD per million tokens: {"input": x, "output": y, "cache_write": z, "cache_read": w}
PRICES_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-opus": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    "claude-haiku": {"input": 0.80, "output": 4.0, "cache_write": 1.0, "cache_read": 0.08},
    "gpt-4o": {"input": 2.50, "output": 10.0, "cache_write": 2.50, "cache_read": 1.25},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_write": 0.15, "cache_read": 0.075},
    "gpt-5": {"input": 1.25, "output": 10.0, "cache_write": 1.25, "cache_read": 0.125},
    "deepseek-chat": {"input": 0.27, "output": 1.10, "cache_write": 0.27, "cache_read": 0.07},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19, "cache_write": 0.55, "cache_read": 0.14},
}

_DEFAULT_PRICE = {"input": 0.0, "output": 0.0, "cache_write": 0.0, "cache_read": 0.0}
_WARN_FRACTION = 0.8


def price_for(model: str) -> dict[str, float]:
    """Longest-prefix price match for *model*; zero-price default if unknown."""
    best_key = ""
    for key in PRICES_USD_PER_MTOK:
        if model.lower().startswith(key) and len(key) > len(best_key):
            best_key = key
    return PRICES_USD_PER_MTOK.get(best_key, _DEFAULT_PRICE)


@dataclass
class BudgetLimits:
    """Hard caps. ``None`` or <=0 means unlimited for that dimension."""

    max_cost_usd: float | None = None
    max_total_tokens: int | None = None
    max_turns: int | None = None
    max_wall_seconds: float | None = None

    @classmethod
    def from_env(cls) -> BudgetLimits:
        def _float(name: str) -> float | None:
            raw = os.getenv(name)
            if not raw:
                return None
            try:
                v = float(raw)
            except ValueError:
                return None
            return v if v > 0 else None

        def _int(name: str) -> int | None:
            v = _float(name)
            return int(v) if v is not None else None

        return cls(
            max_cost_usd=_float("RA_MAX_COST_USD"),
            max_total_tokens=_int("RA_MAX_TOKENS"),
            max_turns=_int("RA_MAX_TURNS"),
            max_wall_seconds=_float("RA_MAX_WALL_SECONDS"),
        )

    @property
    def any_limit(self) -> bool:
        return bool(
            self.max_cost_usd or self.max_total_tokens
            or self.max_turns or self.max_wall_seconds
        )


class BudgetExceededError(RuntimeError):
    """Raised when a hard budget limit is breached. Carries a human report."""

    def __init__(self, report: str) -> None:
        super().__init__(report)
        self.report = report


@dataclass
class BudgetState:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    turns: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class BudgetVerdict:
    """Result of a budget check."""

    exceeded_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.exceeded_reasons


class BudgetGuard:
    """Accumulates usage and enforces :class:`BudgetLimits`."""

    def __init__(
        self,
        limits: BudgetLimits | None = None,
        model: str = "",
        started_at: float | None = None,
    ) -> None:
        self.limits = limits or BudgetLimits.from_env()
        self.model = model
        self.prices = price_for(model)
        self.state = BudgetState()
        self.started_at = started_at if started_at is not None else time.monotonic()
        if not self.prices.get("input") and not self.prices.get("output"):
            if self.limits.max_cost_usd and self.limits.any_limit:
                import logging

                logging.getLogger(__name__).warning(
                    "No price table entry for model %r — cost budget unenforceable", model
                )
        # 未知价格 + 设了成本上限 → 上限无法按美元强制执行（token/轮次/时长上限不受影响）。
        # 快照里如实上报，前端据此显示告示而不是静默展示 $0.00。
        price_known = bool(self.prices.get("input") or self.prices.get("output"))
        self.cost_cap_enforceable = (
            not self.limits.max_cost_usd or price_known
        )
        self._warned: set[str] = set()

    # -- accumulation -------------------------------------------------------

    def record(self, response: LLMResponse) -> None:
        u = response.usage
        s = self.state
        s.input_tokens += u.input_tokens
        s.output_tokens += u.output_tokens
        s.cache_creation_tokens += u.cache_creation_input_tokens
        s.cache_read_tokens += u.cache_read_input_tokens
        s.turns += 1
        p = self.prices
        s.cost_usd += (
            u.input_tokens * p["input"]
            + u.output_tokens * p["output"]
            + u.cache_creation_input_tokens * p["cache_write"]
            + u.cache_read_input_tokens * p["cache_read"]
        ) / 1_000_000.0

    # -- checking -----------------------------------------------------------

    def check(self) -> BudgetVerdict:
        """Return current verdict; raise BudgetExceededError on hard breach."""
        s = self.state
        lim = self.limits
        verdict = BudgetVerdict()
        reasons: list[str] = []

        if lim.max_turns and s.turns >= lim.max_turns:
            reasons.append(f"turn limit reached ({s.turns}/{lim.max_turns})")
        if lim.max_total_tokens and s.total_tokens >= lim.max_total_tokens:
            reasons.append(
                f"token limit reached ({s.total_tokens}/{lim.max_total_tokens})"
            )
        if lim.max_cost_usd and s.cost_usd >= lim.max_cost_usd:
            reasons.append(f"cost limit reached (${s.cost_usd:.2f}/${lim.max_cost_usd:.2f})")
        elapsed = time.monotonic() - self.started_at
        if lim.max_wall_seconds and elapsed >= lim.max_wall_seconds:
            reasons.append(f"wall-clock limit reached ({elapsed:.0f}s/{lim.max_wall_seconds:.0f}s)")

        verdict.warnings.extend(self._warnings(elapsed))
        verdict.exceeded_reasons = reasons
        if reasons:
            raise BudgetExceededError("; ".join(reasons))
        return verdict

    def _warnings(self, elapsed: float) -> list[str]:
        lim = self.limits
        s = self.state
        out: list[str] = []
        if lim.max_cost_usd and s.cost_usd >= _WARN_FRACTION * lim.max_cost_usd \
                and "cost" not in self._warned:
            out.append(f"cost at ${s.cost_usd:.2f} of ${lim.max_cost_usd:.2f}")
            self._warned.add("cost")
        if lim.max_total_tokens and s.total_tokens >= _WARN_FRACTION * lim.max_total_tokens \
                and "tokens" not in self._warned:
            out.append(f"tokens at {s.total_tokens} of {lim.max_total_tokens}")
            self._warned.add("tokens")
        if lim.max_wall_seconds and elapsed >= _WARN_FRACTION * lim.max_wall_seconds \
                and "wall" not in self._warned:
            out.append(f"elapsed {elapsed:.0f}s of {lim.max_wall_seconds:.0f}s")
            self._warned.add("wall")
        return out

    # -- reporting ----------------------------------------------------------

    def snapshot(self, include_elapsed: bool = True) -> dict:
        s = self.state
        d = {
            "model": self.model,
            "input_tokens": s.input_tokens,
            "output_tokens": s.output_tokens,
            "cache_creation_tokens": s.cache_creation_tokens,
            "cache_read_tokens": s.cache_read_tokens,
            "total_tokens": s.total_tokens,
            "turns": s.turns,
            "cost_usd": round(s.cost_usd, 4),
            "cost_cap_enforceable": self.cost_cap_enforceable,
            "limits": {
                "max_cost_usd": self.limits.max_cost_usd,
                "max_total_tokens": self.limits.max_total_tokens,
                "max_turns": self.limits.max_turns,
                "max_wall_seconds": self.limits.max_wall_seconds,
            },
        }
        if include_elapsed:
            d["elapsed_seconds"] = round(time.monotonic() - self.started_at, 1)
        return d
