"""Quality gate framework.

A gate is an async check that either passes or fails. Blocking gates must
pass before a document may be finalized; warn-severity failures are
recorded but do not stop the pipeline.

Gates are plain awaitables over a context dict so they stay trivially
testable without network or LLM access (dependency results are injected).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class GateResult:
    """Outcome of a single gate."""

    name: str
    passed: bool
    severity: str = "blocking"          # "blocking" | "warn"
    failures: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateReport:
    """Aggregated results for one document run."""

    results: list[GateResult] = field(default_factory=list)
    revision_round: int = 0

    @property
    def passed(self) -> bool:
        """True when every *blocking* result passed (warn failures ignored)."""
        return all(r.passed for r in self.results if r.severity == "blocking")

    @property
    def blocking_failures(self) -> list[str]:
        out: list[str] = []
        for r in self.results:
            if r.severity == "blocking" and not r.passed:
                out.extend(f"[{r.name}] {f}" for f in r.failures)
        return out

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "revision_round": self.revision_round,
            "results": [r.to_dict() for r in self.results],
        }

    def save(self, path) -> None:
        p = __import__("pathlib").Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
                     encoding="utf-8")

    @classmethod
    def load(cls, path) -> "GateReport":
        data = json.loads(__import__("pathlib").Path(path).read_text(encoding="utf-8"))
        report = cls(revision_round=data.get("revision_round", 0))
        for r in data.get("results", []):
            report.results.append(GateResult(**r))
        return report


class Gate(ABC):
    """A named, async quality check."""

    name: str = "gate"
    severity: str = "blocking"

    @abstractmethod
    async def run(self, context: dict[str, Any]) -> GateResult:
        """Execute the check. *context* carries artifact paths from the pipeline."""

    def _result(self, passed: bool, failures: list[str] | None = None,
                details: dict | None = None) -> GateResult:
        return GateResult(
            name=self.name,
            passed=passed,
            severity=self.severity,
            failures=failures or [],
            details=details or {},
        )


def render_gate_report_md(report: GateReport) -> str:
    """Human-readable markdown for injecting into a revision prompt."""
    lines = [f"# Quality Gate Report (round {report.revision_round})",
             f"Overall: {'PASS' if report.passed else 'FAIL'}", ""]
    for r in report.results:
        status = "PASS" if r.passed else ("WARN-FAIL" if r.severity == "warn" else "FAIL")
        lines.append(f"## {r.name} — {status} ({r.severity})")
        for f in r.failures:
            lines.append(f"- {f}")
        lines.append("")
    return "\n".join(lines)
