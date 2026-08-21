"""Metrics for golden-task evaluation.

Computes objective indicators from a finished run's artifacts — no LLM
judgment involved, so numbers are reproducible:

    status, word_count, figures_count, citations_count,
    citation_pass_rate, gates_passed, cost_usd, duration_seconds
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_gates_report(run_dir: Path) -> dict | None:
    p = Path(run_dir) / "gates_report.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def citation_metrics(run_dir: Path) -> dict[str, Any]:
    """Pull citation numbers from the gate report when present."""
    report = load_gates_report(Path(run_dir))
    out = {"citations_count": 0, "citation_pass_rate": 0.0, "unverified": None}
    if not report:
        return out
    for r in report.get("results", []):
        if r.get("name") == "citations":
            d = r.get("details", {})
            out["citations_count"] = int(d.get("total") or 0)
            out["citation_pass_rate"] = float(d.get("pass_rate") or 0.0)
            out["unverified"] = int(d.get("unverified") or 0)
    return out


def document_metrics(run_dir: Path) -> dict[str, Any]:
    """Word count + figure count from the final/draft docx and figures dir."""
    from ..gates.doc_gate import count_words, extract_docx_text

    run_dir = Path(run_dir)
    out: dict[str, Any] = {"word_count": 0, "figures_count": 0, "has_final_docx": False}

    docx = run_dir / "final" / "manuscript.docx"
    if not docx.exists():
        drafts = sorted((run_dir / "drafts").glob("v*_draft.docx")) if (run_dir / "drafts").exists() else []
        if drafts:
            docx = drafts[-1]
    if docx.exists():
        out["has_final_docx"] = (run_dir / "final" / "manuscript.docx").exists()
        try:
            out["word_count"] = count_words(extract_docx_text(docx))
        except Exception:
            pass

    figs = run_dir / "figures"
    if figs.exists():
        out["figures_count"] = len([
            f for f in figs.iterdir()
            if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg"}
        ])
    return out


def cost_metrics(run_dir: Path) -> dict[str, Any]:
    p = Path(run_dir) / "run.json"
    if not p.exists():
        return {"cost_usd": None}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cost_usd": None}
    budget = state.get("budget", {})
    return {
        "cost_usd": budget.get("cost_usd"),
        "total_tokens": budget.get("total_tokens"),
        "turns": budget.get("turns"),
    }


def compute_metrics(run_dir: Path) -> dict[str, Any]:
    """Aggregate all metrics for one finished run directory."""
    run_dir = Path(run_dir)
    gates = load_gates_report(run_dir)
    metrics: dict[str, Any] = {
        "status": "unknown",
        "gates_passed": bool(gates["passed"]) if gates else None,
        "_gates_raw": gates,
    }
    metrics.update(document_metrics(run_dir))
    metrics.update(citation_metrics(run_dir))
    metrics.update(cost_metrics(run_dir))
    return metrics


def check_thresholds(metrics: dict[str, Any], task: dict[str, Any]) -> list[str]:
    """Return a list of threshold violations (empty == pass)."""
    failures: list[str] = []

    def _num(v) -> float:
        return float(v) if v is not None else -1.0

    if task.get("min_words") and _num(metrics.get("word_count")) < task["min_words"]:
        failures.append(
            f"word_count {_num(metrics['word_count']):.0f} < min_words {task['min_words']}"
        )
    if task.get("min_citations") and metrics.get("citations_count", 0) < task["min_citations"]:
        failures.append(
            f"citations_count {metrics.get('citations_count')} < min_citations "
            f"{task['min_citations']}"
        )
    min_rate = task.get("citation_pass_rate")
    rate = metrics.get("citation_pass_rate")
    if min_rate is not None and rate is not None and _num(rate) < min_rate:
        failures.append(f"citation_pass_rate {rate} < required {min_rate}")
    if task.get("min_figures") and metrics.get("figures_count", 0) < task["min_figures"]:
        failures.append(
            f"figures_count {metrics.get('figures_count')} < min_figures "
            f"{task['min_figures']}"
        )
    if task.get("expect_sections"):
        # Section presence is enforced by DocGate during the run; surface its
        # missing-section failures here when a gate report exists.
        report = metrics.get("_gates_raw")
        if report is not None:
            doc = next((r for r in report.get("results", [])
                        if r.get("name") == "document"), {})
            for f in doc.get("failures", []):
                if "missing sections" in f:
                    failures.append(f)
    max_cost = task.get("budget_usd")
    cost = metrics.get("cost_usd")
    if max_cost and cost is not None and _num(cost) > max_cost:
        failures.append(f"cost_usd {cost:.2f} > budget_usd {max_cost}")
    return failures
