"""Session persistence — run.json state machine + append-only event log.

Replaces mtime-based directory guessing with an explicit, machine-readable
record of what a run has accomplished. A crashed process resumes by reading
``run.json``; every notable occurrence is appended to ``events.jsonl``
(Codex-CLI "rollout" style) for audit and debugging.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core import atomic_write_text

SCHEMA_VERSION = 1


@dataclass
class StageRecord:
    status: str = "pending"                  # pending|running|done|failed|skipped|partial
    artifacts: list[str] = field(default_factory=list)
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass
class SessionState:
    schema_version: int = SCHEMA_VERSION
    session_id: str = ""
    query: str = ""
    model: str = ""
    mode: str = "pipeline"                   # pipeline | single
    stage: str = ""                          # current/last stage name
    status: str = "running"                  # running|complete|failed|cancelled
    stages: dict[str, dict] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    #: chat 模式产物目录（相对工作区根的 POSIX 路径）；任务模式留空。
    outputs_dir: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


class SessionStore:
    """Owns ``run.json`` and ``events.jsonl`` inside one paper output dir."""

    RUN_FILE = "run.json"
    EVENTS_FILE = "events.jsonl"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = Path(run_dir)
        self.state = SessionState()
        self._load()

    # -- lifecycle -----------------------------------------------------------

    def _path(self, name: str) -> Path:
        return self.run_dir / name

    def _load(self) -> None:
        p = self._path(self.RUN_FILE)
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            state = SessionState(**{
                k: v for k, v in data.items() if k in SessionState.__dataclass_fields__
            })
            self.state = state
        except (json.JSONDecodeError, OSError, TypeError):
            pass  # corrupt file -> start fresh state; artifacts still recover us

    def save(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.state.updated_at = time.time()
        atomic_write_text(
            self._path(self.RUN_FILE),
            json.dumps(self.state.to_dict(), indent=2, ensure_ascii=False),
        )

    @classmethod
    def create(cls, run_dir: Path, query: str, model: str, mode: str = "pipeline") -> SessionStore:
        store = cls(run_dir)
        store.state = SessionState(
            session_id=run_dir.name or uuid.uuid4().hex[:12],
            query=query, model=model, mode=mode,
        )
        store.save()
        return store

    # -- stages ----------------------------------------------------------------

    def mark_stage(self, name: str, status: str,
                   artifacts: list[str] | None = None,
                   error: str = "") -> None:
        rec = self.state.stages.setdefault(name, StageRecord().__dict__)
        prev = self.state.stages.get(name) or {}
        rec.update({
            "status": status,
            "artifacts": artifacts if artifacts is not None else prev.get("artifacts", []),
            "error": error,
            "started_at": prev.get("started_at") or time.time(),
            "finished_at": time.time() if status in ("done", "failed", "partial") else 0.0,
        })
        self.state.stage = name
        self.save()

    def stage_status(self, name: str) -> str:
        return self.state.stages.get(name, {}).get("status", "pending")

    def done_stages(self) -> list[str]:
        return [n for n, r in self.state.stages.items() if r.get("status") == "done"]

    # -- events ---------------------------------------------------------------

    def log_event(self, kind: str, data: dict | None = None) -> None:
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            with open(self._path(self.EVENTS_FILE), "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": round(time.time(), 3), "kind": kind, "data": data or {},
                }, ensure_ascii=False) + "\n")
        except OSError:
            pass  # logging must never break the run

    def log(self, kind: str, data: dict | None = None) -> None:
        """Alias matching the kernel session-log port contract (``.log``)."""
        self.log_event(kind, data)

    def read_events(self) -> list[dict]:
        p = self._path(self.EVENTS_FILE)
        if not p.exists():
            return []
        out = []
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    # -- final bookkeeping ------------------------------------------------------

    def finish(self, status: str, budget_snapshot: dict | None = None) -> None:
        self.state.status = status
        if budget_snapshot:
            self.state.budget = budget_snapshot
        self.save()
        self.log_event("run_end", {"status": status})


def load_run_state(run_dir: Path) -> dict | None:
    """容错读取 run.json；缺失或损坏返回 ``None``（不抛异常）。

    工程债：``web/chat.py`` 与 ``web/routes.py`` 曾各维护一份逐字相同的
    ``_load_run_state``，收敛到本模块单一实现，两处经别名引用。
    """
    path = Path(run_dir) / SessionStore.RUN_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None
