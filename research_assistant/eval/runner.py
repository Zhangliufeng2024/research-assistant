"""Golden-task regression runner.

Usage::

    python -m research_assistant.eval.runner eval/golden_tasks/fem_literature_review.yaml \
        [--model deepseek-chat] [--workdir /tmp/ra-eval]

Executes the task through the pipeline (headless), computes metrics from the
run artifacts, and writes ``eval_results/<timestamp>_<task_id>.json``.
Exit code 0 when all thresholds pass, 1 otherwise — suitable for CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import yaml

from ..config import load_project_env
from ..kernel.budget import BudgetLimits
from .metrics import check_thresholds, compute_metrics


def load_task(path: str | Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for field in ("id", "query"):
        if not data.get(field):
            raise ValueError(f"task file {path} missing required field: {field}")
    return data


async def run_task(task: dict, model: str, base_workdir: Path) -> dict[str, Any]:
    """Run one golden task end-to-end and return its report dict."""
    from ..api import generate_paper

    started = time.time()
    run_dir: Path | None = None

    async for update in generate_paper(
        query=task["query"],
        cwd=str(base_workdir),
        model=model,
        multi_agent=True,
        budget_limits=BudgetLimits(
            max_cost_usd=task.get("budget_usd"),
            max_wall_seconds=task.get("max_wall_seconds", 3600),
        ),
        track_token_usage=True,
    ):
        if update.get("type") == "result":
            run_dir = Path(update.get("paper_directory") or "")

    duration = time.time() - started
    report: dict[str, Any] = {
        "task_id": task["id"],
        "model": model,
        "duration_seconds": round(duration, 1),
        "run_dir": str(run_dir) if run_dir else "",
    }
    if run_dir and run_dir.exists():
        report.update(compute_metrics(run_dir))
        report.pop("_gates_raw", None)
        report["threshold_failures"] = check_thresholds(report, task)
    else:
        report["threshold_failures"] = ["run produced no output directory"]
    report["passed"] = not report["threshold_failures"]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one golden eval task")
    parser.add_argument("task", help="Path to task YAML")
    parser.add_argument("--model", default=None)
    parser.add_argument("--workdir", default=None, help="Base working directory")
    parser.add_argument("--results-dir", default="eval_results")
    args = parser.parse_args()

    load_project_env(Path.cwd())
    if not os.getenv("LLM_API_KEY"):
        print("Error: LLM_API_KEY not set", file=sys.stderr)
        return 2

    task = load_task(args.task)
    model = args.model or os.getenv("LLM_MODEL") or "claude-sonnet-4-6"
    workdir = Path(args.workdir or Path.cwd())
    workdir.mkdir(parents=True, exist_ok=True)

    print(f"[eval] running {task['id']} with {model} ...")
    report = asyncio.run(run_task(task, model, workdir))

    results_dir = Path(args.results_dir)
    results_dir.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    json_path = results_dir / f"{stamp}_{task['id']}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    failures = report.get("threshold_failures", [])
    print(f"[eval] {'PASS' if report['passed'] else 'FAIL'} -> {json_path}")
    for f in failures:
        print(f"  - {f}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
