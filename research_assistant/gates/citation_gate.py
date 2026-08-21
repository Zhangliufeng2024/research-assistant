"""Citation gate — fabricated references must block finalization."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .base import Gate, GateResult


class CitationGate(Gate):
    """Verify every BibTeX entry is a real publication.

    Blocking conditions:
      - any ``unverified`` citation, or
      - pass rate (verified+uncertain)/total below *min_pass_rate*.

    The underlying network verification can be stubbed in tests by passing
    ``verify_fn``; production uses
    :func:`research_assistant.tools.citation_verify.verify_bibtex_file`.
    """

    name = "citations"

    def __init__(
        self,
        bib_path: str | Path,
        min_pass_rate: float = 0.90,
        report_output: Optional[str | Path] = None,
        verify_fn=None,
    ) -> None:
        self.bib_path = Path(bib_path)
        self.min_pass_rate = min_pass_rate
        self.report_output = report_output
        self._verify_fn = verify_fn

    async def run(self, context: dict[str, Any]) -> GateResult:
        if not self.bib_path.exists():
            return self._result(False, [f"references.bib not found: {self.bib_path}"])

        if self._verify_fn is not None:
            outcome = self._verify_fn(self.bib_path)
            report = await outcome if hasattr(outcome, "__await__") else outcome
        else:
            from ..tools.citation_verify import verify_bibtex_file
            try:
                report = await verify_bibtex_file(self.bib_path)
            except (FileNotFoundError, ValueError) as e:
                return self._result(False, [str(e)])

        failures: list[str] = []
        for r in report.results:
            if r.status == "unverified":
                failures.append(
                    f"UNVERIFIED [{r.key}] {r.title[:80]!r} — replace with a real paper"
                )

        passed = (
            report.unverified == 0
            and report.pass_rate >= self.min_pass_rate
        )
        if report.unverified == 0 and report.pass_rate < self.min_pass_rate:
            failures.append(
                f"pass rate {report.pass_rate:.0%} below required "
                f"{self.min_pass_rate:.0%}"
            )

        details = {
            "total": report.total,
            "verified": report.verified,
            "uncertain": report.uncertain,
            "unverified": report.unverified,
            "pass_rate": round(report.pass_rate, 4),
            "min_pass_rate": self.min_pass_rate,
        }

        if self.report_output:
            try:
                from ..tools.citation_verify import _format_report
                out = Path(self.report_output)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(_format_report(report), encoding="utf-8")
                details["report_saved_to"] = str(out)
            except OSError:
                pass

        return self._result(passed, failures or None, details)
