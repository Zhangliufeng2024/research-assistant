"""Quality gates for research documents."""

from .base import Gate, GateReport, GateResult, render_gate_report_md
from .citation_gate import CitationGate
from .doc_gate import DocGate

__all__ = [
    "Gate",
    "GateReport",
    "GateResult",
    "render_gate_report_md",
    "CitationGate",
    "DocGate",
]
