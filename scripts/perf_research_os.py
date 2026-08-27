"""Synthetic performance acceptance for the research operating system.

The benchmark intentionally exercises the durable SQLite paths rather than an
LLM provider: 1,000 ordered events, 500 evidence fragments, and 100 tasks.
Run from the repository root with ``python scripts/perf_research_os.py``.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

from research_assistant.runtime import PlatformStore


def timed(callable_, *args, **kwargs):
    started = time.perf_counter()
    value = callable_(*args, **kwargs)
    return value, (time.perf_counter() - started) * 1000


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ra-perf-") as raw_root:
        root = Path(raw_root)
        store = PlatformStore(root / ".ra" / "platform.sqlite3")
        project = store.ensure_project(root, "Performance acceptance")
        task = store.create_task(
            task_id="perf-events", project_id=project["id"], query="event benchmark",
            mode="benchmark", output_dir=str(root / "writing_outputs"),
        )
        started = time.perf_counter()
        for index in range(1000):
            store.append_event(task["id"], {"type": "status", "index": index})
        event_write_ms = (time.perf_counter() - started) * 1000
        _, event_read_ms = timed(store.read_events, task["id"], limit=1000)

        claims = []
        for index in range(100):
            claims.append(store.create_claim(project_id=project["id"], text=f"claim {index}"))
        for index in range(500):
            evidence = store.create_evidence(
                project_id=project["id"], source_anchor=f"chunk:{index}",
                excerpt=f"evidence {index}", metadata={"benchmark": True},
            )
            store.link_evidence(
                project_id=project["id"], claim_id=claims[index % len(claims)]["id"],
                evidence_id=evidence["id"], relation="supports",
            )
        _, matrix_ms = timed(store.evidence_matrix, project["id"], limit=500)

        for index in range(100):
            store.create_task(
                task_id=f"perf-task-{index}", project_id=project["id"],
                query=f"task {index}", mode="benchmark",
            )
        _, task_list_ms = timed(store.list_tasks, project["id"], 100)
        _, home_ms = timed(store.project_home, project["id"])
        result = {
            "events": 1000, "evidence": 500, "tasks": 101,
            "event_write_ms": round(event_write_ms, 2),
            "event_read_ms": round(event_read_ms, 2),
            "evidence_matrix_ms": round(matrix_ms, 2),
            "task_list_ms": round(task_list_ms, 2),
            "project_home_ms": round(home_ms, 2),
        }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        # These are generous local acceptance ceilings; the benchmark is meant
        # to catch accidental O(N²) regressions, not judge machine speed.
        if result["event_read_ms"] > 1500 or result["evidence_matrix_ms"] > 1500 or result["task_list_ms"] > 1000 or result["project_home_ms"] > 1000:
            raise SystemExit("[PERF-RESEARCH-OS] FAIL: local acceptance ceiling exceeded")
        print("[PERF-RESEARCH-OS] PASS")


if __name__ == "__main__":
    main()
