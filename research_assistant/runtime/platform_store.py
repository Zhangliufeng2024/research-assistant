"""SQLite-backed platform state.

The filesystem remains the source of truth for research artifacts.  This store
owns the relational state that does not fit safely in a WebSocket connection:
projects, background tasks, and their ordered event streams.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 10
PROJECT_OS_VERSION = 1


class PlatformStore:
    """Small transactional repository built on the Python stdlib SQLite driver."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    root TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    instructions TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    query TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    output_dir TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_project_updated
                    ON tasks(project_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS task_events (
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    ts REAL NOT NULL,
                    type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(task_id, seq)
                );
                CREATE TABLE IF NOT EXISTS task_steps (
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT '',
                    depends_on_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at REAL,
                    finished_at REAL,
                    error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(task_id, id)
                );
                -- First-class research objects.  These tables deliberately use
                -- stable text ids and JSON extension columns so the schema can
                -- evolve without invalidating existing projects.
                CREATE TABLE IF NOT EXISTS research_items (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open',
                    version INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_research_items_project_kind
                    ON research_items(project_id, kind, updated_at DESC);
                CREATE TABLE IF NOT EXISTS claims (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    confidence REAL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_claims_project_updated
                    ON claims(project_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS evidence (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source_id TEXT,
                    source_anchor TEXT NOT NULL DEFAULT '',
                    excerpt TEXT NOT NULL DEFAULT '',
                    artifact_path TEXT,
                    kind TEXT NOT NULL DEFAULT 'source',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_project_updated
                    ON evidence(project_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS evidence_links (
                    claim_id TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
                    evidence_id TEXT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
                    relation TEXT NOT NULL DEFAULT 'supports',
                    strength REAL,
                    created_at REAL NOT NULL,
                    PRIMARY KEY(claim_id, evidence_id, relation)
                );
                CREATE TABLE IF NOT EXISTS decisions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    rationale TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_project_updated
                    ON decisions(project_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS research_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                    workflow_id TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    inputs_json TEXT NOT NULL DEFAULT '{}',
                    outputs_json TEXT NOT NULL DEFAULT '{}',
                    environment_json TEXT NOT NULL DEFAULT '{}',
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_research_runs_project_started
                    ON research_runs(project_id, started_at DESC);
                CREATE TABLE IF NOT EXISTS provenance_edges (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    from_type TEXT NOT NULL,
                    from_id TEXT NOT NULL,
                    to_type TEXT NOT NULL,
                    to_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    UNIQUE(project_id, from_type, from_id, to_type, to_id, relation)
                );
                CREATE INDEX IF NOT EXISTS idx_provenance_project
                    ON provenance_edges(project_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS job_queue (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    task_id TEXT,
                    workflow_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    run_after REAL NOT NULL,
                    lease_until REAL,
                    last_error TEXT NOT NULL DEFAULT '',
                    priority INTEGER NOT NULL DEFAULT 0,
                    estimated_seconds REAL,
                    resource_key TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_job_queue_ready
                    ON job_queue(status, run_after, priority DESC, created_at);
                CREATE TABLE IF NOT EXISTS resource_leases (
                    id TEXT PRIMARY KEY,
                    resource_key TEXT NOT NULL,
                    worker_id TEXT NOT NULL,
                    job_id TEXT NOT NULL REFERENCES job_queue(id) ON DELETE CASCADE,
                    lease_until REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_resource_leases_active
                    ON resource_leases(resource_key, lease_until);
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL DEFAULT '',
                    object_type TEXT,
                    object_id TEXT,
                    read_at REAL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_notifications_project
                    ON notifications(project_id, read_at, created_at DESC);
                CREATE TABLE IF NOT EXISTS agent_approvals (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                    thread_id TEXT REFERENCES threads(id) ON DELETE SET NULL,
                    turn_id TEXT REFERENCES turns(id) ON DELETE SET NULL,
                    agent_id TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL DEFAULT '{}',
                    summary TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    note TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    resolved_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_approvals_project
                    ON agent_approvals(project_id, status, created_at DESC);
                CREATE TABLE IF NOT EXISTS workflow_definitions (
                    id TEXT NOT NULL,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL DEFAULT 1,
                    definition_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(project_id, id, version)
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_defs_project
                    ON workflow_definitions(project_id, id, version DESC);
                CREATE TABLE IF NOT EXISTS workflow_triggers (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    workflow_id TEXT NOT NULL,
                    interval_seconds REAL NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    next_run REAL NOT NULL,
                    last_run REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_workflow_triggers_due
                    ON workflow_triggers(enabled, next_run);
                CREATE TABLE IF NOT EXISTS threads (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'agent',
                    status TEXT NOT NULL DEFAULT 'idle',
                    parent_thread_id TEXT REFERENCES threads(id) ON DELETE SET NULL,
                    source_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                    context_summary TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    archived_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_threads_project_updated
                    ON threads(project_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS turns (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    status TEXT NOT NULL DEFAULT 'queued',
                    user_input TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_turns_thread_created
                    ON turns(thread_id, created_at);
                CREATE TABLE IF NOT EXISTS agent_items (
                    id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    turn_id TEXT REFERENCES turns(id) ON DELETE CASCADE,
                    seq INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'complete',
                    role TEXT,
                    title TEXT NOT NULL DEFAULT '',
                    content_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(thread_id, seq)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_items_turn_seq
                    ON agent_items(turn_id, seq);
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    thread_id TEXT REFERENCES threads(id) ON DELETE SET NULL,
                    turn_id TEXT REFERENCES turns(id) ON DELETE SET NULL,
                    agent_id TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    budget_json TEXT NOT NULL DEFAULT '{}',
                    inputs_json TEXT NOT NULL DEFAULT '{}',
                    outputs_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT NOT NULL DEFAULT '',
                    started_at REAL,
                    finished_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(task_id, agent_id)
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_project_updated
                    ON agent_runs(project_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS quality_items (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    gate TEXT NOT NULL,
                    severity TEXT NOT NULL DEFAULT 'info',
                    status TEXT NOT NULL DEFAULT 'open',
                    message TEXT NOT NULL,
                    details_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_quality_project_status
                    ON quality_items(project_id, status, severity, updated_at DESC);
                CREATE TABLE IF NOT EXISTS artifact_reviews (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    artifact_path TEXT NOT NULL,
                    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                    run_id TEXT REFERENCES research_runs(id) ON DELETE SET NULL,
                    thread_id TEXT REFERENCES threads(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    version INTEGER NOT NULL DEFAULT 1,
                    comment TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(project_id, artifact_path, version)
                );
                CREATE INDEX IF NOT EXISTS idx_artifact_reviews_project
                    ON artifact_reviews(project_id, status, updated_at DESC);
                CREATE TABLE IF NOT EXISTS analysis_runs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    research_run_id TEXT REFERENCES research_runs(id) ON DELETE SET NULL,
                    task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    script_path TEXT,
                    script_sha256 TEXT,
                    inputs_json TEXT NOT NULL DEFAULT '{}',
                    parameters_json TEXT NOT NULL DEFAULT '{}',
                    environment_json TEXT NOT NULL DEFAULT '{}',
                    outputs_json TEXT NOT NULL DEFAULT '{}',
                    stdout_preview TEXT NOT NULL DEFAULT '',
                    stderr_preview TEXT NOT NULL DEFAULT '',
                    exit_code INTEGER,
                    started_at REAL NOT NULL,
                    finished_at REAL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_analysis_runs_project_started
                    ON analysis_runs(project_id, started_at DESC);
                """
            )
            # ``CREATE TABLE IF NOT EXISTS`` does not evolve an existing
            # workspace database.  Keep upgrades deliberately small and
            # idempotent so users can open projects created by v3.4 without
            # losing their task history.
            project_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(projects)")
            }
            if "instructions" not in project_columns:
                conn.execute(
                    "ALTER TABLE projects ADD COLUMN instructions TEXT NOT NULL DEFAULT ''"
                )
            task_step_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(task_steps)")}
            if "role" not in task_step_columns:
                conn.execute("ALTER TABLE task_steps ADD COLUMN role TEXT NOT NULL DEFAULT ''")
            job_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(job_queue)")}
            for name, definition in (
                ("priority", "INTEGER NOT NULL DEFAULT 0"),
                ("estimated_seconds", "REAL"),
                ("resource_key", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in job_columns:
                    conn.execute(f"ALTER TABLE job_queue ADD COLUMN {name} {definition}")
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('project_os_version', ?)",
                (str(PROJECT_OS_VERSION),),
            )

    def ensure_project(self, root: str | Path, name: str | None = None) -> dict[str, Any]:
        resolved = str(Path(root).resolve())
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE root = ?", (resolved,)).fetchone()
            if row is None:
                project_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO projects(id, root, name, created_at, updated_at) "
                    "VALUES(?, ?, ?, ?, ?)",
                    (project_id, resolved, name or Path(resolved).name, now, now),
                )
                row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return dict(row)

    def update_project_instructions(
        self, project_id: str, *, instructions: str,
    ) -> dict[str, Any] | None:
        """Persist editable long-term project instructions."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE projects SET instructions = ?, updated_at = ? WHERE id = ?",
                (instructions or "", time.time(), project_id),
            )
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            return dict(row) if row is not None else None

    def create_task(
        self,
        *,
        task_id: str,
        project_id: str,
        query: str,
        mode: str,
        output_dir: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO tasks(id, project_id, query, mode, status, output_dir, "
                "metadata_json, created_at, updated_at, started_at) "
                "VALUES(?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
                (
                    task_id, project_id, query, mode, output_dir,
                    json.dumps(metadata or {}, ensure_ascii=False), now, now, now,
                ),
            )
        return self.get_task(task_id) or {}

    def create_steps(self, task_id: str, steps: list[dict[str, Any]]) -> None:
        """Persist a workflow DAG independently of the browser connection."""
        task = self.get_task(task_id) or {}
        metadata = task.get("metadata") or {}
        thread_id = metadata.get("thread_id")
        turn_id = metadata.get("turn_id")
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO task_steps(task_id, id, title, role, depends_on_json, status) VALUES(?, ?, ?, ?, ?, 'pending')",
                [(task_id, str(s["id"]), str(s.get("title") or s["id"]), str(s.get("role") or ""), json.dumps(s.get("depends_on") or [], ensure_ascii=False)) for s in steps],
            )
            conn.executemany(
                "INSERT INTO agent_runs(id, project_id, task_id, thread_id, turn_id, agent_id, role, model, status, inputs_json, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?) ON CONFLICT(task_id, agent_id) DO UPDATE SET role=excluded.role, model=excluded.model, updated_at=excluded.updated_at",
                [(
                    f"{task_id}:{str(s['id'])}", task.get("project_id"), task_id, thread_id, turn_id,
                    str(s["id"]), str(s.get("role") or ""), str(s.get("model") or ""),
                    json.dumps({"depends_on": s.get("depends_on") or []}, ensure_ascii=False), now, now,
                ) for s in steps],
            )
        for step in steps:
            agent_run_id = f"{task_id}:{str(step['id'])}"
            self.add_provenance_edge(
                project_id=str(task.get("project_id") or ""), from_type="task", from_id=task_id,
                to_type="agent_run", to_id=agent_run_id, relation="delegated",
                metadata={"agent_id": str(step["id"]), "role": str(step.get("role") or "")},
            )

    def update_step(self, task_id: str, step_id: str, *, status: str, error: str = "") -> None:
        if status not in {"pending", "running", "done", "failed", "skipped", "cancelled"}:
            raise ValueError(f"invalid step status: {status}")
        now = time.time()
        fields = ["status = ?", "error = ?"]
        values: list[Any] = [status, error]
        if status == "running":
            fields.append("started_at = COALESCE(started_at, ?)")
            values.append(now)
        if status in {"done", "failed", "skipped", "cancelled"}:
            fields.append("finished_at = ?")
            values.append(now)
        values.extend([task_id, step_id])
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE task_steps SET {', '.join(fields)} WHERE task_id = ? AND id = ?", values)
            run_status = "complete" if status == "done" else status
            conn.execute(
                "UPDATE agent_runs SET status=?, error=?, started_at=CASE WHEN ?='running' THEN COALESCE(started_at, ?) ELSE started_at END, "
                "finished_at=CASE WHEN ? IN ('complete','failed','cancelled','skipped') THEN ? ELSE finished_at END, updated_at=? "
                "WHERE task_id=? AND agent_id=?",
                (run_status, error, status, now, run_status, now, now, task_id, step_id),
            )

    def list_steps(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM task_steps WHERE task_id = ? ORDER BY rowid", (task_id,)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["depends_on"] = json.loads(item.pop("depends_on_json"))
            result.append(item)
        return result

    def list_agent_runs(self, project_id: str, *, task_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        query = "SELECT * FROM agent_runs WHERE project_id = ?"
        args: list[Any] = [project_id]
        if task_id:
            query += " AND task_id = ?"
            args.append(task_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 2000)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [self._decode_research_row(row) or {} for row in rows]

    def update_agent_run(self, task_id: str, agent_id: str, *, status: str | None = None,
                         role: str | None = None, model: str | None = None,
                         budget: dict[str, Any] | None = None, outputs: dict[str, Any] | None = None,
                         error: str | None = None) -> dict[str, Any] | None:
        fields = ["updated_at = ?"]
        values: list[Any] = [time.time()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
            if status == "running":
                fields.append("started_at = COALESCE(started_at, ?)")
                values.append(time.time())
            elif status in {"complete", "failed", "cancelled", "skipped"}:
                fields.append("finished_at = ?")
                values.append(time.time())
        for column, value in (("role", role), ("model", model), ("error", error)):
            if value is not None:
                fields.append(f"{column} = ?")
                values.append(value)
        if budget is not None:
            fields.append("budget_json = ?")
            values.append(json.dumps(budget, ensure_ascii=False))
        if outputs is not None:
            fields.append("outputs_json = ?")
            values.append(json.dumps(outputs, ensure_ascii=False))
        values.extend([task_id, agent_id])
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE agent_runs SET {', '.join(fields)} WHERE task_id = ? AND agent_id = ?", values)
            row = conn.execute("SELECT * FROM agent_runs WHERE task_id = ? AND agent_id = ?", (task_id, agent_id)).fetchone()
        return self._decode_research_row(row)

    def task_metrics(self, task_id: str) -> dict[str, Any] | None:
        """Return bounded, provider-agnostic timing metrics for a task."""
        task = self.get_task(task_id)
        if task is None:
            return None
        steps = self.list_steps(task_id)
        now = time.time()
        durations: list[dict[str, Any]] = []
        for step in steps:
            started = step.get("started_at")
            if started is None:
                elapsed = None
            else:
                elapsed = round(max(0.0, (step.get("finished_at") or now) - started), 3)
            durations.append({"id": step["id"], "title": step["title"], "status": step["status"], "seconds": elapsed})
        with self._lock, self._connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id = ?", (task_id,)).fetchone()[0]
        total = round(max(0.0, (task.get("finished_at") or now) - task["created_at"]), 3)
        duration_map = {d["id"]: float(d["seconds"] or 0.0) for d in durations}
        depends = {step["id"]: list(step.get("depends_on") or []) for step in steps}
        longest: dict[str, float] = {}

        def path_seconds(step_id: str, visiting: set[str] | None = None) -> float:
            if step_id in longest:
                return longest[step_id]
            visiting = visiting or set()
            if step_id in visiting:  # malformed DAG: avoid recursion loops
                return duration_map.get(step_id, 0.0)
            visiting.add(step_id)
            parents = depends.get(step_id, [])
            longest[step_id] = duration_map.get(step_id, 0.0) + max(
                (path_seconds(parent, visiting) for parent in parents), default=0.0,
            )
            visiting.remove(step_id)
            return longest[step_id]

        critical_path = max((path_seconds(step["id"]) for step in steps), default=0.0)
        return {
            "task_id": task_id,
            "status": task["status"],
            "total_seconds": total,
            "event_count": int(count),
            "critical_path_seconds": round(critical_path, 3),
            "steps": durations,
        }

    def resource_usage(self, project_id: str) -> dict[str, Any]:
        """Aggregate durable usage without exposing provider credentials."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, task_id, workflow_id, status, outputs_json, started_at, finished_at "
                "FROM research_runs WHERE project_id = ? ORDER BY started_at DESC LIMIT 1000",
                (project_id,),
            ).fetchall()
        total = {"cost_usd": 0.0, "total_tokens": 0, "turns": 0, "runs": 0, "failed_runs": 0, "seconds": 0.0}
        by_workflow: dict[str, dict[str, Any]] = {}
        by_role: dict[str, dict[str, Any]] = {}
        for row in rows:
            outputs = self._json_value(row["outputs_json"])
            usage = outputs.get("usage") if isinstance(outputs, dict) else {}
            usage = usage if isinstance(usage, dict) else {}
            cost = float(usage.get("cost_usd") or 0.0)
            tokens = int(usage.get("total_tokens") or 0)
            turns = int(usage.get("turns") or 0)
            seconds = float(usage.get("elapsed_seconds") or 0.0)
            total["cost_usd"] += cost
            total["total_tokens"] += tokens
            total["turns"] += turns
            total["seconds"] += seconds
            total["runs"] += 1
            if row["status"] in {"failed", "interrupted"}:
                total["failed_runs"] += 1
            key = str(row["workflow_id"] or "unknown")
            bucket = by_workflow.setdefault(key, {"workflow_id": key, "runs": 0, "cost_usd": 0.0, "total_tokens": 0, "seconds": 0.0})
            bucket["runs"] += 1
            bucket["cost_usd"] += cost
            bucket["total_tokens"] += tokens
            bucket["seconds"] += seconds
        with self._lock, self._connect() as conn:
            agent_rows = conn.execute(
                "SELECT role, budget_json, started_at, finished_at FROM agent_runs WHERE project_id=? ORDER BY updated_at DESC LIMIT 2000",
                (project_id,),
            ).fetchall()
        for row in agent_rows:
            role = str(row["role"] or "unknown")
            usage = self._json_value(row["budget_json"])
            bucket = by_role.setdefault(role, {"role": role, "runs": 0, "cost_usd": 0.0, "total_tokens": 0, "seconds": 0.0})
            bucket["runs"] += 1
            bucket["cost_usd"] += float(usage.get("cost_usd") or 0.0)
            bucket["total_tokens"] += int(usage.get("total_tokens") or 0)
            if row["started_at"] is not None:
                bucket["seconds"] += max(0.0, float(row["finished_at"] or time.time()) - float(row["started_at"]))
        total["cost_usd"] = round(total["cost_usd"], 4)
        total["seconds"] = round(total["seconds"], 3)
        for bucket in by_workflow.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 4)
            bucket["seconds"] = round(bucket["seconds"], 3)
        for bucket in by_role.values():
            bucket["cost_usd"] = round(bucket["cost_usd"], 4)
            bucket["seconds"] = round(bucket["seconds"], 3)
        return {"summary": total, "by_workflow": sorted(by_workflow.values(), key=lambda item: item["cost_usd"], reverse=True), "by_role": sorted(by_role.values(), key=lambda item: item["cost_usd"], reverse=True)}

    def create_notification(self, *, project_id: str, kind: str, title: str,
                             message: str = "", object_type: str | None = None,
                             object_id: str | None = None, notification_id: str | None = None) -> dict[str, Any]:
        notification_id = notification_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO notifications(id, project_id, kind, title, message, object_type, object_id, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (notification_id, project_id, str(kind), str(title), str(message), object_type, object_id, time.time()),
            )
            row = conn.execute("SELECT * FROM notifications WHERE id = ?", (notification_id,)).fetchone()
        return dict(row) if row is not None else {}

    def create_agent_approval(self, *, project_id: str, task_id: str | None = None,
                              thread_id: str | None = None, turn_id: str | None = None,
                              agent_id: str = "", role: str = "", tool_name: str = "",
                              arguments: dict[str, Any] | None = None, summary: str = "",
                              approval_id: str | None = None) -> dict[str, Any]:
        approval_id = approval_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agent_approvals(id, project_id, task_id, thread_id, turn_id, agent_id, role, tool_name, arguments_json, summary, status, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                (approval_id, project_id, task_id, thread_id, turn_id, str(agent_id), str(role), str(tool_name), json.dumps(arguments or {}, ensure_ascii=False), str(summary)[:4000], time.time()),
            )
            row = conn.execute("SELECT * FROM agent_approvals WHERE id = ? AND project_id = ?", (approval_id, project_id)).fetchone()
        item = dict(row) if row is not None else {}
        item["arguments"] = self._json_value(item.pop("arguments_json", "{}"))
        return item

    def list_agent_approvals(self, project_id: str, *, status: str | None = "pending", limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM agent_approvals WHERE project_id = ?"
        args: list[Any] = [project_id]
        if status:
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["arguments"] = self._json_value(item.pop("arguments_json", "{}"))
            result.append(item)
        return result

    def resolve_agent_approval(self, approval_id: str, project_id: str, *, approved: bool, note: str = "") -> dict[str, Any] | None:
        status = "approved" if approved else "rejected"
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE agent_approvals SET status = ?, note = ?, resolved_at = ? WHERE id = ? AND project_id = ? AND status = 'pending'",
                (status, str(note)[:4000], time.time(), str(approval_id), str(project_id)),
            )
            row = conn.execute("SELECT * FROM agent_approvals WHERE id = ? AND project_id = ?", (str(approval_id), str(project_id))).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["arguments"] = self._json_value(item.pop("arguments_json", "{}"))
        return item

    def list_notifications(self, project_id: str, *, unread_only: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM notifications WHERE project_id = ?"
        args: list[Any] = [project_id]
        if unread_only:
            query += " AND read_at IS NULL"
        query += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(query, args).fetchall()]

    def mark_notification_read(self, notification_id: str, project_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("UPDATE notifications SET read_at = ? WHERE id = ? AND project_id = ?", (time.time(), notification_id, project_id))
            return cursor.rowcount > 0

    def update_task(
        self,
        task_id: str,
        *,
        status: str | None = None,
        error: str | None = None,
        output_dir: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        fields = ["updated_at = ?"]
        values: list[Any] = [time.time()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
            if status in {"complete", "failed", "cancelled", "interrupted"}:
                fields.append("finished_at = ?")
                values.append(time.time())
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        if output_dir is not None:
            fields.append("output_dir = ?")
            values.append(output_dir)
        if metadata is not None:
            fields.append("metadata_json = ?")
            values.append(json.dumps(metadata, ensure_ascii=False))
        values.append(task_id)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?", values)

    def append_event(self, task_id: str, payload: dict[str, Any]) -> int:
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM task_events WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            seq = int(row["next_seq"])
            conn.execute(
                "INSERT INTO task_events(task_id, seq, ts, type, payload_json) "
                "VALUES(?, ?, ?, ?, ?)",
                (
                    task_id, seq, time.time(), str(payload.get("type") or "event"),
                    json.dumps(payload, ensure_ascii=False, default=str),
                ),
            )
            return seq

    @staticmethod
    def _decode_task(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        try:
            item["metadata"] = json.loads(item.pop("metadata_json"))
        except (json.JSONDecodeError, TypeError):
            item["metadata"] = {}
        return item

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return self._decode_task(row)

    def list_tasks(self, project_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as conn:
            if project_id:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE project_id = ? ORDER BY updated_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [self._decode_task(row) or {} for row in rows]

    def read_events(self, task_id: str, after: int = 0, limit: int = 2000) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 5000))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT seq, ts, payload_json FROM task_events "
                "WHERE task_id = ? AND seq > ? ORDER BY seq LIMIT ?",
                (task_id, max(0, int(after)), limit),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                continue
            payload["seq"] = row["seq"]
            payload.setdefault("ts", row["ts"])
            events.append(payload)
        return events

    def mark_orphaned_running_tasks(self) -> int:
        """Mark work left running by a previous process as interrupted."""
        now = time.time()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET status='interrupted', updated_at=?, finished_at=? "
                "WHERE status IN ('queued', 'running', 'stopping')",
                (now, now),
            )
            return int(cursor.rowcount)

    # ------------------------------------------------------------------
    # Research operating-system objects
    # ------------------------------------------------------------------
    @staticmethod
    def _json_value(raw: str | None) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _decode_research_row(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        for key in ("metadata_json", "inputs_json", "outputs_json", "environment_json", "parameters_json", "details_json", "budget_json"):
            if key in item:
                item[key[:-5] if key.endswith("_json") else key] = cls._json_value(item.pop(key))
        return item

    def _project_exists(self, conn: sqlite3.Connection, project_id: str) -> bool:
        return conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is not None

    # Unified Agent workspace ---------------------------------------------
    def create_thread(self, *, project_id: str, title: str = "", kind: str = "agent",
                      parent_thread_id: str | None = None, source_task_id: str | None = None,
                      context_summary: str = "", metadata: dict[str, Any] | None = None,
                      thread_id: str | None = None) -> dict[str, Any]:
        now, thread_id = time.time(), thread_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            if parent_thread_id:
                parent = conn.execute("SELECT project_id FROM threads WHERE id = ?", (parent_thread_id,)).fetchone()
                if parent is None or parent["project_id"] != project_id:
                    raise ValueError("父线程不属于当前项目")
            conn.execute(
                "INSERT INTO threads(id, project_id, title, kind, parent_thread_id, source_task_id, context_summary, metadata_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (thread_id, project_id, title.strip(), kind, parent_thread_id, source_task_id, context_summary, json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
            row = conn.execute("SELECT * FROM threads WHERE id = ?", (thread_id,)).fetchone()
        item = self._decode_research_row(row) or {}
        return item

    def get_thread(self, thread_id: str, project_id: str | None = None) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            query = "SELECT * FROM threads WHERE id = ?"
            args: list[Any] = [thread_id]
            if project_id:
                query += " AND project_id = ?"
                args.append(project_id)
            row = conn.execute(query, args).fetchone()
        return self._decode_research_row(row)

    def list_threads(self, project_id: str, *, limit: int = 100, include_archived: bool = False) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        query = "SELECT * FROM threads WHERE project_id = ?"
        args: list[Any] = [project_id]
        if not include_archived:
            query += " AND archived_at IS NULL"
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [self._decode_research_row(row) or {} for row in rows]

    def fork_thread(self, thread_id: str, *, project_id: str, title: str = "") -> dict[str, Any]:
        source = self.get_thread(thread_id, project_id)
        if source is None:
            raise ValueError("线程不存在")
        summary = str(source.get("context_summary") or source.get("title") or "")
        return self.create_thread(
            project_id=project_id, title=title or f"{source.get('title') or '研究线程'} · 分支",
            kind=str(source.get("kind") or "agent"), parent_thread_id=thread_id,
            context_summary=summary, metadata={"forked_from": thread_id},
        )

    def archive_thread(self, thread_id: str, *, project_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("UPDATE threads SET archived_at = ?, updated_at = ?, status = 'archived' WHERE id = ? AND project_id = ?", (time.time(), time.time(), thread_id, project_id))
            return cursor.rowcount > 0

    def create_turn(self, *, thread_id: str, project_id: str, user_input: str = "",
                    metadata: dict[str, Any] | None = None, turn_id: str | None = None) -> dict[str, Any]:
        thread = self.get_thread(thread_id, project_id)
        if thread is None:
            raise ValueError("线程不存在")
        now, turn_id = time.time(), turn_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute("INSERT INTO turns(id, thread_id, user_input, metadata_json, created_at) VALUES(?, ?, ?, ?, ?)", (turn_id, thread_id, user_input, json.dumps(metadata or {}, ensure_ascii=False), now))
            conn.execute("UPDATE threads SET status='running', updated_at=? WHERE id = ?", (now, thread_id))
            row = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        return self._decode_research_row(row) or {}

    def finish_turn(self, turn_id: str, *, status: str, error: str = "") -> dict[str, Any] | None:
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT thread_id FROM turns WHERE id = ?", (turn_id,)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE turns SET status=?, error=?, started_at=COALESCE(started_at, ?), finished_at=? WHERE id = ?", (status, error, now, now, turn_id))
            conn.execute("UPDATE threads SET status=?, updated_at=? WHERE id = ?", ("idle" if status == "complete" else status, now, row["thread_id"]))
            result = conn.execute("SELECT * FROM turns WHERE id = ?", (turn_id,)).fetchone()
        return self._decode_research_row(result)

    def append_agent_item(self, *, thread_id: str, project_id: str, item_type: str,
                          content: dict[str, Any] | None = None, turn_id: str | None = None,
                          role: str | None = None, title: str = "", status: str = "complete",
                          item_id: str | None = None) -> dict[str, Any]:
        if self.get_thread(thread_id, project_id) is None:
            raise ValueError("线程不存在")
        now, item_id = time.time(), item_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_items WHERE thread_id = ?", (thread_id,)).fetchone()
            seq = int(row[0])
            conn.execute("INSERT INTO agent_items(id, thread_id, turn_id, seq, type, status, role, title, content_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (item_id, thread_id, turn_id, seq, item_type, status, role, title, json.dumps(content or {}, ensure_ascii=False), now, now))
            conn.execute("UPDATE threads SET updated_at=? WHERE id = ?", (now, thread_id))
            result = conn.execute("SELECT * FROM agent_items WHERE id = ?", (item_id,)).fetchone()
        item = self._decode_research_row(result) or {}
        if "content_json" in item:
            item["content"] = self._json_value(item.pop("content_json"))
        return item

    def list_thread_items(self, thread_id: str, *, after: int = 0, limit: int = 1000) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 5000))
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM agent_items WHERE thread_id = ? AND seq > ? ORDER BY seq LIMIT ?", (thread_id, max(0, int(after)), limit)).fetchall()
        result = []
        for row in rows:
            item = self._decode_research_row(row) or {}
            item["content"] = self._json_value(item.pop("content_json", "{}"))
            result.append(item)
        return result

    def create_quality_item(self, *, project_id: str, object_type: str, object_id: str,
                            gate: str, message: str, severity: str = "info",
                            status: str = "open", details: dict[str, Any] | None = None,
                            quality_id: str | None = None) -> dict[str, Any]:
        now, quality_id = time.time(), quality_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute("INSERT INTO quality_items(id, project_id, object_type, object_id, gate, severity, status, message, details_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (quality_id, project_id, object_type, object_id, gate, severity, status, message, json.dumps(details or {}, ensure_ascii=False), now, now))
            row = conn.execute("SELECT * FROM quality_items WHERE id = ?", (quality_id,)).fetchone()
        return self._decode_research_row(row) or {}

    def list_quality_items(self, project_id: str, *, status: str | None = None,
                           object_type: str | None = None, object_id: str | None = None,
                           limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        query, args = "SELECT * FROM quality_items WHERE project_id = ?", [project_id]
        if status:
            query += " AND status = ?"
            args.append(status)
        if object_type:
            query += " AND object_type = ?"
            args.append(object_type)
        if object_id:
            query += " AND object_id = ?"
            args.append(object_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = self._json_value(item.pop("details_json"))
            result.append(item)
        return result

    def review_artifact(self, *, project_id: str, artifact_path: str, status: str,
                        comment: str = "", task_id: str | None = None, run_id: str | None = None,
                        thread_id: str | None = None, version: int = 1,
                        metadata: dict[str, Any] | None = None,
                        review_id: str | None = None) -> dict[str, Any]:
        if status not in {"pending", "accepted", "rejected", "needs_changes", "restored"}:
            raise ValueError("无效的产物审阅状态")
        now, review_id = time.time(), review_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            previous = conn.execute(
                "SELECT metadata_json FROM artifact_reviews WHERE project_id = ? AND artifact_path = ? AND version = ?",
                (project_id, artifact_path, int(version)),
            ).fetchone()
            prior_metadata = self._json_value(previous[0]) if previous is not None else {}
            merged_metadata = {**prior_metadata, **(metadata or {})}
            gates = merged_metadata.get("quality_gates")
            gate_failed = merged_metadata.get("quality_gate_status") == "failed" or (
                isinstance(gates, list) and any(isinstance(g, dict) and g.get("passed") is False for g in gates)
            )
            if status == "accepted" and gate_failed:
                raise ValueError("Citation/Doc/复现门禁未通过，产物不能标记为 accepted")
            conn.execute("INSERT INTO artifact_reviews(id, project_id, artifact_path, task_id, run_id, thread_id, status, version, comment, metadata_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(project_id, artifact_path, version) DO UPDATE SET status=excluded.status, comment=excluded.comment, metadata_json=excluded.metadata_json, updated_at=excluded.updated_at", (review_id, project_id, artifact_path, task_id, run_id, thread_id, status, int(version), comment, json.dumps(merged_metadata, ensure_ascii=False), now, now))
            row = conn.execute("SELECT * FROM artifact_reviews WHERE project_id = ? AND artifact_path = ? AND version = ?", (project_id, artifact_path, int(version))).fetchone()
        return self._decode_research_row(row) or {}

    def list_artifact_reviews(self, project_id: str, *, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        query, args = "SELECT * FROM artifact_reviews WHERE project_id = ?", [project_id]
        if status:
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [self._decode_research_row(row) or {} for row in rows]

    def get_artifact_review(self, review_id: str, project_id: str) -> dict[str, Any] | None:
        """Return one review while enforcing project isolation at the query boundary."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM artifact_reviews WHERE id = ? AND project_id = ?",
                (str(review_id), str(project_id)),
            ).fetchone()
        return self._decode_research_row(row)

    def export_project_manifest(self, project_id: str) -> dict[str, Any]:
        """Export the auditable relational part of a project without secrets.

        The filesystem is exported by the HTTP layer; this method deliberately
        returns JSON-safe rows so imports/archives remain portable and do not
        require shipping a live SQLite database or its WAL files.
        """
        tables = (
            "projects", "threads", "turns", "agent_items", "agent_runs", "tasks", "task_steps",
            "research_items", "claims", "evidence", "evidence_links", "decisions",
            "research_runs", "analysis_runs", "provenance_edges", "quality_items",
            "artifact_reviews", "job_queue", "workflow_definitions", "workflow_triggers",
            "notifications", "agent_approvals",
        )
        result: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "project_os_version": PROJECT_OS_VERSION}
        with self._lock, self._connect() as conn:
            project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if project is None:
                return {}
            result["project"] = dict(project)
            for table in tables:
                if table == "projects":
                    continue
                columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
                if "project_id" in columns:
                    rows = conn.execute(f"SELECT * FROM {table} WHERE project_id = ?", (project_id,)).fetchall()
                elif table in {"turns", "agent_items", "agent_runs", "task_steps"}:
                    # These tables are reached through project-owned parents.
                    if table == "turns":
                        rows = conn.execute("SELECT t.* FROM turns t JOIN threads p ON p.id=t.thread_id WHERE p.project_id=?", (project_id,)).fetchall()
                    elif table == "agent_items":
                        rows = conn.execute("SELECT a.* FROM agent_items a JOIN threads p ON p.id=a.thread_id WHERE p.project_id=?", (project_id,)).fetchall()
                    elif table == "agent_runs":
                        rows = conn.execute("SELECT a.* FROM agent_runs a WHERE a.project_id=?", (project_id,)).fetchall()
                    else:
                        rows = conn.execute("SELECT s.* FROM task_steps s JOIN tasks t ON t.id=s.task_id WHERE t.project_id=?", (project_id,)).fetchall()
                else:
                    continue
                result[table] = [dict(row) for row in rows]
        # Decode JSON columns for consumers and scrub queue worker internals.
        json_suffix = ("_json",)
        for rows in result.values():
            if not isinstance(rows, list):
                continue
            for item in rows:
                if not isinstance(item, dict):
                    continue
                for key in list(item):
                    if key.endswith(json_suffix):
                        decoded = self._json_value(item.pop(key))
                        item[key.removesuffix("_json")] = decoded
                payload = item.get("payload")
                if isinstance(payload, dict):
                    payload.pop("_worker_id", None)
        return result

    def import_project_manifest(self, project_id: str, manifest: dict[str, Any]) -> dict[str, int]:
        """Merge a decoded manifest into an existing project, remapping ownership."""
        if not isinstance(manifest, dict):
            return {}
        order = (
            "threads", "tasks", "task_steps", "turns", "agent_items", "agent_runs", "research_items",
            "claims", "evidence", "evidence_links", "decisions", "research_runs",
            "analysis_runs", "provenance_edges", "quality_items", "artifact_reviews",
            "job_queue", "workflow_definitions", "workflow_triggers", "notifications", "agent_approvals",
        )
        inserted: dict[str, int] = {}
        with self._lock, self._connect() as conn:
            for table in order:
                rows = manifest.get(table)
                if not isinstance(rows, list) or not rows:
                    continue
                columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")]
                for source in rows:
                    if not isinstance(source, dict):
                        continue
                    item = dict(source)
                    for column in columns:
                        if not column.endswith("_json"):
                            continue
                        base = column.removesuffix("_json")
                        if base in item and column not in item:
                            value = item.pop(base)
                            item[column] = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
                    if "project_id" in columns:
                        item["project_id"] = project_id
                    values = [item.get(column) for column in columns]
                    placeholders = ",".join("?" for _ in columns)
                    cursor = conn.execute(
                        f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                        values,
                    )
                    inserted[table] = inserted.get(table, 0) + int(cursor.rowcount > 0)
        return inserted

    def index_task_artifacts(self, *, project_id: str, output_dir: str | Path,
                             task_id: str | None = None, run_id: str | None = None,
                             thread_id: str | None = None, max_files: int = 200) -> list[dict[str, Any]]:
        """Create/update pending review records for files produced by a task.

        Files remain the source of truth; the relational row stores a hash and
        stable relative path so reviewers can detect a new version without
        copying or moving user artifacts.  Internal `.ra` state and secrets
        are intentionally excluded from the review surface.
        """
        with self._lock, self._connect() as conn:
            project = conn.execute("SELECT root FROM projects WHERE id = ?", (project_id,)).fetchone()
        if project is None:
            return []
        root = Path(str(project["root"])).resolve()
        target = Path(output_dir).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return []
        if not target.is_dir():
            return []
        gate_report: dict[str, Any] = {}
        report_path = target / "gates_report.json"
        if report_path.is_file():
            try:
                decoded = json.loads(report_path.read_text(encoding="utf-8"))
                if isinstance(decoded, dict):
                    gate_report = decoded
            except (OSError, json.JSONDecodeError):
                gate_report = {}
        records: list[dict[str, Any]] = []
        ignored = {".ra", ".git", "__pycache__"}
        for path in sorted(target.rglob("*")):
            if len(records) >= max(1, min(int(max_files), 1000)):
                break
            if not path.is_file() or any(part in ignored or part.startswith(".") for part in path.relative_to(root).parts):
                continue
            rel = path.relative_to(root).as_posix()
            digest = self.file_sha256(path)
            if digest is None:
                continue
            metadata = {
                "sha256": digest,
                "size": path.stat().st_size,
                "artifact_type": path.suffix.lower().lstrip(".") or "file",
                "quality_gate_status": (
                    "passed" if gate_report.get("passed") is True
                    else "failed" if gate_report.get("passed") is False else "pending"
                ),
            }
            if isinstance(gate_report.get("results"), list):
                metadata["quality_gates"] = [
                    {"name": result.get("name"), "passed": bool(result.get("passed")),
                     "severity": result.get("severity"), "failures": result.get("failures") or []}
                    for result in gate_report["results"] if isinstance(result, dict)
                ]
            with self._lock, self._connect() as conn:
                previous = conn.execute(
                    "SELECT * FROM artifact_reviews WHERE project_id = ? AND artifact_path = ? ORDER BY version DESC LIMIT 1",
                    (project_id, rel),
                ).fetchone()
            if previous is not None:
                prior_metadata = self._json_value(previous["metadata_json"])
                if isinstance(prior_metadata, dict) and prior_metadata.get("sha256") == digest:
                    continue
                version = int(previous["version"] or 0) + 1
            else:
                version = 1
            records.append(self.review_artifact(
                project_id=project_id, artifact_path=rel, status="pending",
                task_id=task_id, run_id=run_id, thread_id=thread_id,
                version=version, metadata=metadata,
            ))
        for record in records:
            if task_id and record.get("id"):
                self.add_provenance_edge(
                    project_id=project_id, from_type="task", from_id=task_id,
                    to_type="artifact_review", to_id=str(record["id"]), relation="produced",
                    metadata={"artifact_path": record.get("artifact_path"), "version": record.get("version")},
                )
            for gate in (record.get("metadata") or {}).get("quality_gates", []):
                if gate.get("passed") is False and record.get("id"):
                    self.create_quality_item(
                        project_id=project_id, object_type="artifact", object_id=str(record["id"]),
                        gate=str(gate.get("name") or "quality"), severity="error" if gate.get("severity") == "blocking" else "warning",
                        message="；".join(str(item) for item in (gate.get("failures") or [])) or "质量门禁未通过",
                        details={"artifact_path": record.get("artifact_path"), "version": record.get("version")},
                    )
        return records

    def project_activity(self, project_id: str, *, after: float = 0.0,
                         cursor: str | None = None, limit: int = 100) -> dict[str, Any]:
        """Return a stable project activity cursor across all OS objects.

        ``after`` remains as a backwards-compatible timestamp filter. New
        callers should pass the opaque ``ts|id`` cursor returned here; the ID
        tie-breaker prevents same-timestamp events from being skipped.
        """
        limit = max(1, min(int(limit), 500))
        cursor_ts: float | None = None
        cursor_id = ""
        if cursor:
            raw_ts, sep, raw_id = str(cursor).partition("|")
            if sep:
                try:
                    cursor_ts = float(raw_ts)
                    cursor_id = raw_id
                except ValueError:
                    cursor_ts = None
        threshold = cursor_ts if cursor_ts is not None else float(after)
        sql_operator = ">=" if cursor_ts is not None else ">"
        fetch_limit = min(500, limit * 2)
        items: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            task_rows = conn.execute(
                "SELECT e.task_id, e.seq, e.ts, e.type, e.payload_json, t.query "
                "FROM task_events e JOIN tasks t ON t.id=e.task_id "
                f"WHERE t.project_id=? AND e.ts{sql_operator}? ORDER BY e.ts DESC LIMIT ?",
                (project_id, threshold, fetch_limit),
            ).fetchall()
            agent_rows = conn.execute(
                "SELECT a.id, a.seq, a.created_at, a.type, a.status, a.role, a.title, a.content_json, a.thread_id "
                f"FROM agent_items a JOIN threads t ON t.id=a.thread_id WHERE t.project_id=? AND a.created_at{sql_operator}? ORDER BY a.created_at DESC LIMIT ?",
                (project_id, threshold, fetch_limit),
            ).fetchall()
            notification_rows = conn.execute(
                "SELECT id, created_at, kind, title, message, object_type, object_id "
                f"FROM notifications WHERE project_id=? AND created_at{sql_operator}? ORDER BY created_at DESC LIMIT ?",
                (project_id, threshold, fetch_limit),
            ).fetchall()
            quality_rows = conn.execute(
                "SELECT id, updated_at, gate, severity, status, message, object_type, object_id "
                f"FROM quality_items WHERE project_id=? AND updated_at{sql_operator}? ORDER BY updated_at DESC LIMIT ?",
                (project_id, threshold, fetch_limit),
            ).fetchall()
            artifact_rows = conn.execute(
                "SELECT id, updated_at, artifact_path, status, version "
                f"FROM artifact_reviews WHERE project_id=? AND updated_at{sql_operator}? ORDER BY updated_at DESC LIMIT ?",
                (project_id, threshold, fetch_limit),
            ).fetchall()
        for row in task_rows:
            payload = self._json_value(row["payload_json"])
            items.append({"id": f"task-event:{row['task_id']}:{row['seq']}", "kind": "task", "ts": row["ts"], "title": str(payload.get("type") or row["type"]), "message": str(payload.get("message") or row["query"]), "object_type": "task", "object_id": row["task_id"], "status": payload.get("status")})
        for row in agent_rows:
            content = self._json_value(row["content_json"])
            items.append({"id": f"agent-item:{row['id']}", "kind": "agent", "ts": row["created_at"], "title": row["title"] or row["type"], "message": str(content.get("message") or content.get("text") or row["role"] or "Agent activity"), "object_type": "thread", "object_id": row["thread_id"], "status": row["status"]})
        for row in notification_rows:
            items.append({"id": f"notification:{row['id']}", "kind": "notification", "ts": row["created_at"], "title": row["title"], "message": row["message"], "object_type": row["object_type"], "object_id": row["object_id"]})
        for row in quality_rows:
            items.append({"id": f"quality:{row['id']}", "kind": "quality", "ts": row["updated_at"], "title": row["gate"], "message": row["message"], "object_type": row["object_type"], "object_id": row["object_id"], "status": row["status"], "severity": row["severity"]})
        for row in artifact_rows:
            items.append({"id": f"artifact:{row['id']}", "kind": "artifact", "ts": row["updated_at"], "title": row["artifact_path"], "message": f"v{row['version']} · {row['status']}", "object_type": "artifact_review", "object_id": row["id"], "status": row["status"]})
        items.sort(key=lambda item: (float(item.get("ts") or 0), str(item.get("id"))), reverse=True)
        if cursor_ts is not None:
            items = [
                item for item in items
                if (float(item.get("ts") or 0), str(item.get("id"))) < (cursor_ts, cursor_id)
            ]
        items = items[:limit]
        next_cursor = cursor or str(after)
        if items:
            next_cursor = f"{float(items[-1]['ts']):.17g}|{items[-1]['id']}"
        return {"items": items, "next_cursor": next_cursor}

    def project_home(self, project_id: str) -> dict[str, Any]:
        project = None
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                return {}
            project = dict(row)
        overview = self.research_overview(project_id)
        quality = self.research_quality_report(project_id)
        return {
            "project": project,
            "overview": overview,
            "quality": quality,
            "threads": self.list_threads(project_id, limit=8),
            "tasks": self.list_tasks(project_id, limit=8),
            "quality_items": self.list_quality_items(project_id, status="open", limit=8),
            "artifacts": self.list_artifact_reviews(project_id, status="pending", limit=8),
            "decisions": self.list_decisions(project_id, limit=8),
            "usage": self.resource_usage(project_id),
            "notifications": self.list_notifications(project_id, unread_only=True, limit=8),
            "activity": self.project_activity(project_id, limit=20)["items"],
        }

    def create_research_item(
        self, *, project_id: str, kind: str, title: str, body: str = "",
        status: str = "open", metadata: dict[str, Any] | None = None,
        item_id: str | None = None,
    ) -> dict[str, Any]:
        if kind not in {"question", "hypothesis", "objective", "note"}:
            raise ValueError("kind must be question, hypothesis, objective, or note")
        now, item_id = time.time(), item_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO research_items(id, project_id, kind, title, body, status, metadata_json, created_at, updated_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item_id, project_id, kind, title.strip(), body, status,
                 json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
            row = conn.execute("SELECT * FROM research_items WHERE id = ?", (item_id,)).fetchone()
        return self._decode_research_row(row) or {}

    def list_research_items(self, project_id: str, *, kind: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        query, args = "SELECT * FROM research_items WHERE project_id = ?", [project_id]
        if kind:
            query += " AND kind = ?"
            args.append(kind)
        query += " ORDER BY updated_at DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [self._decode_research_row(row) or {} for row in rows]

    def update_research_item(self, item_id: str, *, title: str | None = None, body: str | None = None,
                             status: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
        fields, values = ["updated_at = ?", "version = version + 1"], [time.time()]
        for field, value in (("title", title), ("body", body), ("status", status)):
            if value is not None:
                fields.append(f"{field} = ?")
                values.append(value)
        if metadata is not None:
            fields.append("metadata_json = ?")
            values.append(json.dumps(metadata, ensure_ascii=False))
        values.append(item_id)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE research_items SET {', '.join(fields)} WHERE id = ?", values)
            row = conn.execute("SELECT * FROM research_items WHERE id = ?", (item_id,)).fetchone()
        return self._decode_research_row(row)

    def create_claim(self, *, project_id: str, text: str, status: str = "proposed",
                     confidence: float | None = None, metadata: dict[str, Any] | None = None,
                     claim_id: str | None = None) -> dict[str, Any]:
        now, claim_id = time.time(), claim_id or uuid.uuid4().hex
        if confidence is not None and not 0 <= float(confidence) <= 1:
            raise ValueError("confidence must be between 0 and 1")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO claims(id, project_id, text, status, confidence, metadata_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (claim_id, project_id, text.strip(), status, confidence, json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
            row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return self._decode_research_row(row) or {}

    def list_claims(self, project_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM claims WHERE project_id = ? ORDER BY updated_at DESC LIMIT ?", (project_id, limit)).fetchall()
            links = conn.execute(
                "SELECT el.claim_id, el.evidence_id, el.relation, el.strength FROM evidence_links el "
                "JOIN claims c ON c.id = el.claim_id WHERE c.project_id = ? ORDER BY el.created_at", (project_id,),
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            grouped.setdefault(str(link["claim_id"]), []).append({"evidence_id": link["evidence_id"], "relation": link["relation"], "strength": link["strength"]})
        result = []
        for row in rows:
            item = self._decode_research_row(row) or {}
            item["evidence_links"] = grouped.get(item.get("id"), [])
            result.append(item)
        return result

    def create_evidence(self, *, project_id: str, source_id: str | None = None,
                        source_anchor: str = "", excerpt: str = "", artifact_path: str | None = None,
                        kind: str = "source", metadata: dict[str, Any] | None = None,
                        evidence_id: str | None = None) -> dict[str, Any]:
        now, evidence_id = time.time(), evidence_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO evidence(id, project_id, source_id, source_anchor, excerpt, artifact_path, kind, metadata_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (evidence_id, project_id, source_id, source_anchor, excerpt, artifact_path, kind, json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
            row = conn.execute("SELECT * FROM evidence WHERE id = ?", (evidence_id,)).fetchone()
        return self._decode_research_row(row) or {}

    def list_evidence(self, project_id: str, *, claim_id: str | None = None, limit: int = 300) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        query = "SELECT e.* FROM evidence e WHERE e.project_id = ?"
        args: list[Any] = [project_id]
        if claim_id:
            query += " AND EXISTS (SELECT 1 FROM evidence_links l WHERE l.evidence_id = e.id AND l.claim_id = ?)"
            args.append(claim_id)
        query += " ORDER BY e.updated_at DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [self._decode_research_row(row) or {} for row in rows]

    def mark_source_stale(self, *, project_id: str, source_id: str, reason: str = "资料已删除或发生变化") -> dict[str, int]:
        """Invalidate claims backed by a changed source and leave an auditable quality trail."""
        with self._lock, self._connect() as conn:
            claim_rows = conn.execute(
                "SELECT DISTINCT c.id FROM claims c JOIN evidence_links l ON l.claim_id = c.id "
                "JOIN evidence e ON e.id = l.evidence_id WHERE c.project_id = ? AND e.source_id = ?",
                (project_id, source_id),
            ).fetchall()
            evidence_count = int(conn.execute(
                "SELECT COUNT(*) FROM evidence WHERE project_id = ? AND source_id = ?",
                (project_id, source_id),
            ).fetchone()[0])
        for row in claim_rows:
            self.create_quality_item(
                project_id=project_id, object_type="claim", object_id=str(row[0]),
                gate="source_integrity", severity="warning", status="open",
                message=reason, details={"source_id": source_id},
            )
        return {"claims": len(claim_rows), "evidence": evidence_count}

    def link_evidence(self, *, project_id: str, claim_id: str, evidence_id: str,
                      relation: str = "supports", strength: float | None = None) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as conn:
            valid = conn.execute(
                "SELECT (SELECT project_id FROM claims WHERE id = ?) AS claim_project, (SELECT project_id FROM evidence WHERE id = ?) AS evidence_project",
                (claim_id, evidence_id),
            ).fetchone()
            if valid is None or valid["claim_project"] != project_id or valid["evidence_project"] != project_id:
                raise ValueError("claim/evidence 不属于当前项目")
            conn.execute(
                "INSERT OR REPLACE INTO evidence_links(claim_id, evidence_id, relation, strength, created_at) VALUES(?, ?, ?, ?, ?)",
                (claim_id, evidence_id, relation, strength, now),
            )
        return {"claim_id": claim_id, "evidence_id": evidence_id, "relation": relation, "strength": strength, "created_at": now}

    def create_decision(self, *, project_id: str, title: str, rationale: str = "", status: str = "active",
                        metadata: dict[str, Any] | None = None, decision_id: str | None = None) -> dict[str, Any]:
        now, decision_id = time.time(), decision_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO decisions(id, project_id, title, rationale, status, metadata_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (decision_id, project_id, title.strip(), rationale, status, json.dumps(metadata or {}, ensure_ascii=False), now, now),
            )
            row = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        return self._decode_research_row(row) or {}

    def list_decisions(self, project_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM decisions WHERE project_id = ? ORDER BY updated_at DESC LIMIT ?", (project_id, limit)).fetchall()
        return [self._decode_research_row(row) or {} for row in rows]

    def create_research_run(self, *, project_id: str, task_id: str | None = None, workflow_id: str | None = None,
                            inputs: dict[str, Any] | None = None, environment: dict[str, Any] | None = None,
                            run_id: str | None = None) -> dict[str, Any]:
        now, run_id = time.time(), run_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO research_runs(id, project_id, task_id, workflow_id, status, inputs_json, environment_json, started_at, created_at) VALUES(?, ?, ?, ?, 'running', ?, ?, ?, ?)",
                (run_id, project_id, task_id, workflow_id, json.dumps(inputs or {}, ensure_ascii=False), json.dumps(environment or {}, ensure_ascii=False), now, now),
            )
            row = conn.execute("SELECT * FROM research_runs WHERE id = ?", (run_id,)).fetchone()
        return self._decode_research_row(row) or {}

    def finish_research_run(self, run_id: str, *, status: str, outputs: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE research_runs SET status = ?, outputs_json = ?, finished_at = ? WHERE id = ?", (status, json.dumps(outputs or {}, ensure_ascii=False), time.time(), run_id))
            row = conn.execute("SELECT * FROM research_runs WHERE id = ?", (run_id,)).fetchone()
        return self._decode_research_row(row)

    def list_research_runs(self, project_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM research_runs WHERE project_id = ? ORDER BY started_at DESC LIMIT ?", (project_id, limit)).fetchall()
        return [self._decode_research_row(row) or {} for row in rows]

    @staticmethod
    def file_sha256(path: str | Path) -> str | None:
        target = Path(path)
        if not target.is_file():
            return None
        digest = hashlib.sha256()
        try:
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()

    def create_analysis_run(self, *, project_id: str, script_path: str | None = None,
                            inputs: dict[str, Any] | None = None, parameters: dict[str, Any] | None = None,
                            environment: dict[str, Any] | None = None, research_run_id: str | None = None,
                            task_id: str | None = None, run_id: str | None = None) -> dict[str, Any]:
        now, run_id = time.time(), run_id or uuid.uuid4().hex
        script_hash = self.file_sha256(script_path) if script_path else None
        with self._lock, self._connect() as conn:
            conn.execute("INSERT INTO analysis_runs(id, project_id, research_run_id, task_id, script_path, script_sha256, inputs_json, parameters_json, environment_json, started_at, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (run_id, project_id, research_run_id, task_id, script_path, script_hash, json.dumps(inputs or {}, ensure_ascii=False), json.dumps(parameters or {}, ensure_ascii=False), json.dumps(environment or {}, ensure_ascii=False), now, now))
            row = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
        return self._decode_research_row(row) or {}

    def finish_analysis_run(self, run_id: str, *, status: str, outputs: dict[str, Any] | None = None,
                            stdout: str = "", stderr: str = "", exit_code: int | None = None) -> dict[str, Any] | None:
        if status not in {"complete", "failed", "cancelled", "interrupted"}:
            raise ValueError("无效的分析运行状态")
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE analysis_runs SET status=?, outputs_json=?, stdout_preview=?, stderr_preview=?, exit_code=?, finished_at=? WHERE id = ?", (status, json.dumps(outputs or {}, ensure_ascii=False), stdout[-8000:], stderr[-8000:], exit_code, time.time(), run_id))
            row = conn.execute("SELECT * FROM analysis_runs WHERE id = ?", (run_id,)).fetchone()
        return self._decode_research_row(row)

    def list_analysis_runs(self, project_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM analysis_runs WHERE project_id = ? ORDER BY started_at DESC LIMIT ?", (project_id, limit)).fetchall()
        result = []
        for row in rows:
            result.append(self._decode_research_row(row) or {})
        return result

    def add_provenance_edge(self, *, project_id: str, from_type: str, from_id: str, to_type: str, to_id: str,
                            relation: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        edge_id = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO provenance_edges(id, project_id, from_type, from_id, to_type, to_id, relation, metadata_json, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(project_id, from_type, from_id, to_type, to_id, relation) DO UPDATE SET metadata_json = excluded.metadata_json",
                (edge_id, project_id, from_type, from_id, to_type, to_id, relation, json.dumps(metadata or {}, ensure_ascii=False), now),
            )
            row = conn.execute("SELECT * FROM provenance_edges WHERE project_id = ? AND from_type = ? AND from_id = ? AND to_type = ? AND to_id = ? AND relation = ?", (project_id, from_type, from_id, to_type, to_id, relation)).fetchone()
        return self._decode_research_row(row) or {}

    def list_provenance(self, project_id: str, *, object_type: str | None = None, object_id: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 2000))
        query, args = "SELECT * FROM provenance_edges WHERE project_id = ?", [project_id]
        if object_type and object_id:
            query += " AND ((from_type = ? AND from_id = ?) OR (to_type = ? AND to_id = ?))"
            args.extend([object_type, object_id, object_type, object_id])
        query += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        return [self._decode_research_row(row) or {} for row in rows]

    def research_overview(self, project_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            counts = {}
            for table in ("research_items", "claims", "evidence", "decisions", "research_runs", "provenance_edges"):
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", (project_id,)).fetchone()[0])
            uncovered = int(conn.execute(
                "SELECT COUNT(*) FROM claims c WHERE c.project_id = ? AND NOT EXISTS (SELECT 1 FROM evidence_links l WHERE l.claim_id = c.id AND l.relation = 'supports')",
                (project_id,),
            ).fetchone()[0])
        return {"counts": counts, "uncovered_claims": uncovered}

    def research_quality_report(self, project_id: str) -> dict[str, Any]:
        """Cheap, deterministic quality gate for incremental research work."""
        with self._lock, self._connect() as conn:
            claims = int(conn.execute("SELECT COUNT(*) FROM claims WHERE project_id = ?", (project_id,)).fetchone()[0])
            supported = int(conn.execute("SELECT COUNT(DISTINCT c.id) FROM claims c JOIN evidence_links l ON l.claim_id = c.id AND l.relation = 'supports' WHERE c.project_id = ?", (project_id,)).fetchone()[0])
            contradicted = int(conn.execute("SELECT COUNT(DISTINCT c.id) FROM claims c JOIN evidence_links l ON l.claim_id = c.id AND l.relation = 'contradicts' WHERE c.project_id = ?", (project_id,)).fetchone()[0])
            conflicted = int(conn.execute(
                "SELECT COUNT(*) FROM (SELECT c.id FROM claims c JOIN evidence_links l ON l.claim_id=c.id "
                "WHERE c.project_id=? GROUP BY c.id HAVING SUM(CASE WHEN l.relation='supports' THEN 1 ELSE 0 END)>0 "
                "AND SUM(CASE WHEN l.relation='contradicts' THEN 1 ELSE 0 END)>0)", (project_id,),
            ).fetchone()[0])
            orphan_evidence = int(conn.execute("SELECT COUNT(*) FROM evidence e WHERE e.project_id = ? AND NOT EXISTS (SELECT 1 FROM evidence_links l WHERE l.evidence_id = e.id)", (project_id,)).fetchone()[0])
            failed_runs = int(conn.execute("SELECT COUNT(*) FROM research_runs WHERE project_id = ? AND status IN ('failed', 'interrupted')", (project_id,)).fetchone()[0])
            stale_evidence = int(conn.execute(
                "SELECT COUNT(*) FROM evidence e WHERE e.project_id=? AND (json_extract(e.metadata_json, '$.stale') = 1 "
                "OR EXISTS (SELECT 1 FROM quality_items q WHERE q.project_id=? AND q.object_type='claim' "
                "AND q.gate='source_integrity' AND q.status='open' AND EXISTS (SELECT 1 FROM evidence_links l WHERE l.claim_id=q.object_id AND l.evidence_id=e.id)))",
                (project_id, project_id),
            ).fetchone()[0])
        uncovered = max(0, claims - supported)
        return {
            "claims": {"total": claims, "supported": supported, "contradicted": contradicted, "conflicted": conflicted, "uncovered": uncovered},
            "orphan_evidence": orphan_evidence,
            "stale_evidence": stale_evidence,
            "failed_runs": failed_runs,
            "ready_for_synthesis": claims > 0 and uncovered == 0 and conflicted == 0 and stale_evidence == 0 and failed_runs == 0,
        }

    def evidence_matrix(self, project_id: str, *, limit: int = 300) -> dict[str, Any]:
        """Return claims and evidence as a UI-friendly auditable matrix."""
        claims = self.list_claims(project_id, limit=limit)
        evidence = self.list_evidence(project_id, limit=limit)
        evidence_by_id = {item["id"]: item for item in evidence}
        rows = []
        for claim in claims:
            cells = []
            for link in claim.get("evidence_links", []):
                source = evidence_by_id.get(link["evidence_id"])
                if source is not None:
                    cells.append({**link, "evidence": source})
            rows.append({"claim": {k: v for k, v in claim.items() if k != "evidence_links"}, "cells": cells})
        return {
            "rows": rows,
            "unlinked_evidence": [item for item in evidence if not any(item["id"] == cell["evidence_id"] for row in rows for cell in row["cells"])],
            "summary": self.research_quality_report(project_id),
        }

    def update_claim(self, claim_id: str, *, project_id: str, status: str | None = None,
                     confidence: float | None = None, text: str | None = None) -> dict[str, Any] | None:
        fields, values = ["updated_at = ?"], [time.time()]
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if confidence is not None:
            if not 0 <= float(confidence) <= 1:
                raise ValueError("confidence must be between 0 and 1")
            fields.append("confidence = ?")
            values.append(float(confidence))
        if text is not None:
            fields.append("text = ?")
            values.append(text)
        values.extend([claim_id, project_id])
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE claims SET {', '.join(fields)} WHERE id = ? AND project_id = ?", values)
            row = conn.execute("SELECT * FROM claims WHERE id = ? AND project_id = ?", (claim_id, project_id)).fetchone()
        return self._decode_research_row(row)

    def search_project(self, project_id: str, query: str, *, limit: int = 30) -> list[dict[str, Any]]:
        """Search core project objects without requiring an external index."""
        term = f"%{query.strip()}%"
        if term == "%%":
            return []
        per_type = max(1, min(int(limit), 100))
        specs = (
            ("thread", "threads", "id", "title", "context_summary", "updated_at"),
            ("task", "tasks", "id", "query", "error", "updated_at"),
            ("research_item", "research_items", "id", "title", "body", "updated_at"),
            ("claim", "claims", "id", "text", "status", "updated_at"),
            ("decision", "decisions", "id", "title", "rationale", "updated_at"),
            ("artifact", "artifact_reviews", "id", "artifact_path", "comment", "updated_at"),
        )
        results: list[dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            for kind, table, id_col, title_col, detail_col, ts_col in specs:
                rows = conn.execute(
                    f"SELECT {id_col} AS id, {title_col} AS title, {detail_col} AS detail, {ts_col} AS updated_at FROM {table} WHERE project_id = ? AND ({title_col} LIKE ? OR {detail_col} LIKE ?) ORDER BY {ts_col} DESC LIMIT ?",
                    (project_id, term, term, per_type),
                ).fetchall()
                results.extend({"kind": kind, **dict(row)} for row in rows)
        return sorted(results, key=lambda item: float(item.get("updated_at") or 0), reverse=True)[:per_type]

    # Durable scheduler queue ------------------------------------------------
    def enqueue_job(self, *, project_id: str, workflow_id: str, payload: dict[str, Any] | None = None,
                    task_id: str | None = None, max_attempts: int = 3, run_after: float | None = None,
                    job_id: str | None = None, priority: int = 0,
                    estimated_seconds: float | None = None, resource_key: str = "") -> dict[str, Any]:
        now = time.time()
        job_id = job_id or uuid.uuid4().hex
        max_attempts = max(1, min(int(max_attempts), 20))
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO job_queue(id, project_id, task_id, workflow_id, payload_json, max_attempts, run_after, priority, estimated_seconds, resource_key, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, project_id, task_id, workflow_id, json.dumps(payload or {}, ensure_ascii=False), max_attempts, run_after or now, max(-100, min(int(priority), 100)), float(estimated_seconds) if estimated_seconds else None, str(resource_key)[:120], now, now),
            )
            row = conn.execute("SELECT * FROM job_queue WHERE id = ?", (job_id,)).fetchone()
        item = self._decode_research_row(row) or {}
        if row is not None:
            item["payload"] = self._json_value(row["payload_json"])
        return item

    def list_jobs(self, project_id: str, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        query, args = "SELECT * FROM job_queue WHERE project_id = ?", [project_id]
        if status:
            query += " AND status = ?"
            args.append(status)
        query += " ORDER BY priority DESC, created_at DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        result = []
        queued_wait = 0.0
        for row in rows:
            item = dict(row)
            item["payload"] = self._json_value(item.pop("payload_json"))
            item["estimated_wait_seconds"] = round(queued_wait, 1)
            if item.get("status") == "queued":
                queued_wait += float(item.get("estimated_seconds") or 0.0)
            result.append(item)
        return result

    def claim_job(self, *, worker_id: str, lease_seconds: float = 300) -> dict[str, Any] | None:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # A crashed worker's lease is safe to reclaim.  The worker id is
            # stored in payload rather than expanding the public schema.
            row = conn.execute(
                "SELECT * FROM job_queue WHERE (status = 'queued' OR (status = 'running' AND lease_until < ?)) AND run_after <= ? ORDER BY priority DESC, created_at LIMIT 1",
                (now, now),
            ).fetchone()
            if row is None:
                return None
            # 崩溃毒丸封顶：attempts 只在领取时 +1，硬崩溃（进程消失）走不到
            # fail_job 的终态判断，反复到期回收会让 attempts 无限膨胀并被无限
            # 重复派发。领取前发现预算已耗尽直接判失败，不再派出。
            if int(row["attempts"]) >= int(row["max_attempts"]):
                conn.execute(
                    "UPDATE job_queue SET status='failed', last_error=?, lease_until=NULL, updated_at=? WHERE id = ?",
                    ("超过最大尝试次数（疑似 worker 反复崩溃）", now, row["id"]),
                )
                return None
            payload = self._json_value(row["payload_json"])
            effective_lease = max(10.0, float(lease_seconds))
            payload["_worker_id"] = worker_id
            # 记录本次领取的租约长度：调度器按 min(lease/3, 60s) 节奏续期。
            payload["_lease_seconds"] = round(effective_lease, 3)
            conn.execute(
                "UPDATE job_queue SET status='running', attempts=attempts+1, lease_until=?, payload_json=?, updated_at=? WHERE id = ?",
                (now + effective_lease, json.dumps(payload, ensure_ascii=False), now, row["id"]),
            )
            claimed = conn.execute("SELECT * FROM job_queue WHERE id = ?", (row["id"],)).fetchone()
        item = dict(claimed) if claimed else None
        if item is not None:
            item["payload"] = self._json_value(item.pop("payload_json"))
        return item

    def complete_job(self, job_id: str) -> None:
        # 归属校验：只有仍处于 running 的作业才能被标记完成 —— 租约过期被
        # 回收（可能已被其它 worker 重领）后，旧持有者的迟到写回必须失效。
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE job_queue SET status='complete', lease_until=NULL, updated_at=? WHERE id = ? AND status='running'",
                (time.time(), job_id),
            )

    def attach_job_task(self, job_id: str, task_id: str) -> dict[str, Any] | None:
        """Associate a durable queue row with the in-process task it launched.

        The association is deliberately best-effort and project-neutral here;
        callers must only pass a task created for the same project.  Keeping it
        on the queue row makes the background run discoverable from the queue
        UI and gives crash recovery a stable hand-off point.
        """
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE job_queue SET task_id = ?, updated_at = ? WHERE id = ?",
                (str(task_id), time.time(), str(job_id)),
            )
            row = conn.execute("SELECT * FROM job_queue WHERE id = ?", (str(job_id),)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["payload"] = self._json_value(item.pop("payload_json"))
        return item

    def fail_job(self, job_id: str, *, error: str, retry_delay: float = 30.0) -> dict[str, Any] | None:
        now = time.time()
        with self._lock, self._connect() as conn:
            # 归属校验（同 complete_job / defer_job）：只对仍 running 的作业生效。
            row = conn.execute(
                "SELECT attempts, max_attempts FROM job_queue WHERE id = ? AND status='running'",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            terminal = int(row["attempts"]) >= int(row["max_attempts"])
            status = "failed" if terminal else "queued"
            conn.execute(
                "UPDATE job_queue SET status=?, lease_until=NULL, last_error=?, run_after=?, updated_at=? WHERE id = ? AND status='running'",
                (status, str(error)[:4000], now if terminal else now + max(1.0, float(retry_delay)), now, job_id),
            )
            result = conn.execute("SELECT * FROM job_queue WHERE id = ?", (job_id,)).fetchone()
        item = dict(result) if result else None
        if item is not None:
            item["payload"] = self._json_value(item.pop("payload_json"))
        return item

    def defer_job(self, job_id: str, *, delay: float = 2.0, reason: str = "") -> dict[str, Any] | None:
        """Return a claimed job to the queue without consuming an attempt.

        Resource contention is scheduling back-pressure, not a task failure.
        Keeping it separate from ``fail_job`` prevents a busy provider from
        exhausting retry budgets while another worker holds its slots.
        """
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE job_queue SET status='queued', lease_until=NULL, last_error=?, run_after=?, updated_at=? WHERE id=? AND status='running'",
                (str(reason)[:4000], now + max(0.25, float(delay)), now, str(job_id)),
            )
            row = conn.execute("SELECT * FROM job_queue WHERE id = ?", (str(job_id),)).fetchone()
        item = dict(row) if row else None
        if item is not None:
            item["payload"] = self._json_value(item.pop("payload_json"))
        return item

    def recover_expired_jobs(self) -> int:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("UPDATE job_queue SET status='queued', lease_until=NULL, updated_at=? WHERE status='running' AND lease_until < ?", (time.time(), time.time()))
            return int(cursor.rowcount)

    def renew_job_lease(self, job_id: str, *, worker_id: str | None = None,
                        lease_seconds: float = 300) -> bool:
        """续期运行中作业的租约；返回 False 表示已失去所有权。

        job_queue 没有 worker_id 列，领取时写入的 ``payload._worker_id``
        即归属标记：worker_id 不匹配与状态非 running 都按「租约丢失」处理，
        调用方（调度器心跳）应立即停止执行且不得把旧结果写回。
        """
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT payload_json FROM job_queue WHERE id = ? AND status='running'",
                (str(job_id),),
            ).fetchone()
            if row is None:
                return False
            if worker_id is not None:
                holder = (self._json_value(row["payload_json"]) or {}).get("_worker_id")
                if holder != str(worker_id):
                    return False
            cursor = conn.execute(
                "UPDATE job_queue SET lease_until=?, updated_at=? WHERE id=? AND status='running'",
                (now + max(10.0, float(lease_seconds)), now, str(job_id)),
            )
            return cursor.rowcount > 0

    def recover_expired_resource_leases(self) -> int:
        """Remove leases left behind by a crashed scheduler process."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM resource_leases WHERE lease_until < ?", (time.time(),)
            )
            return int(cursor.rowcount)

    def acquire_resource_lease(
        self, *, resource_key: str, worker_id: str, job_id: str,
        max_slots: int, lease_seconds: float = 3600.0,
    ) -> dict[str, Any] | None:
        """Atomically reserve one cross-process resource slot.

        SQLite's write transaction makes this safe for multiple scheduler
        processes sharing the same project database. The returned lease must
        be released when the job finishes; expiry covers hard crashes.
        """
        resource_key = str(resource_key or "default")[:120]
        now = time.time()
        lease_id = uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM resource_leases WHERE lease_until < ?", (now,))
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM resource_leases WHERE resource_key = ? AND lease_until >= ?",
                (resource_key, now),
            ).fetchone()
            if int(row["n"] if row else 0) >= max(1, min(int(max_slots), 128)):
                return None
            conn.execute(
                "INSERT INTO resource_leases(id, resource_key, worker_id, job_id, lease_until, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (lease_id, resource_key, str(worker_id), str(job_id), now + max(10.0, float(lease_seconds)), now, now),
            )
        return {"id": lease_id, "resource_key": resource_key, "worker_id": str(worker_id), "job_id": str(job_id), "lease_until": now + max(10.0, float(lease_seconds))}

    def renew_resource_lease(self, lease_id: str, *, lease_seconds: float = 3600.0) -> bool:
        now = time.time()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE resource_leases SET lease_until=?, updated_at=? WHERE id=?",
                (now + max(10.0, float(lease_seconds)), now, str(lease_id)),
            )
            return cursor.rowcount > 0

    def release_resource_lease(self, lease_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM resource_leases WHERE id = ?", (str(lease_id),))
            return cursor.rowcount > 0

    def list_resource_leases(self, *, resource_key: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM resource_leases WHERE lease_until >= ?"
        args: list[Any] = [time.time()]
        if resource_key:
            query += " AND resource_key = ?"
            args.append(str(resource_key))
        query += " ORDER BY resource_key, created_at"
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(query, args).fetchall()]

    # Versioned workflow definitions and interval triggers ------------------
    def save_workflow_definition(self, *, project_id: str, workflow_id: str,
                                 definition: dict[str, Any], enabled: bool = True,
                                 version: int | None = None) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as conn:
            if version is None:
                row = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM workflow_definitions WHERE project_id = ? AND id = ?", (project_id, workflow_id)).fetchone()
                version = int(row[0])
            conn.execute(
                "INSERT INTO workflow_definitions(id, project_id, version, definition_json, enabled, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (workflow_id, project_id, int(version), json.dumps(definition, ensure_ascii=False), int(bool(enabled)), now, now),
            )
            row = conn.execute("SELECT * FROM workflow_definitions WHERE project_id = ? AND id = ? AND version = ?", (project_id, workflow_id, int(version))).fetchone()
        item = dict(row) if row else {}
        item["definition"] = self._json_value(item.pop("definition_json"))
        item["enabled"] = bool(item.get("enabled"))
        return item

    def list_workflow_definitions(self, project_id: str, *, workflow_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        query, args = "SELECT * FROM workflow_definitions WHERE project_id = ?", [project_id]
        if workflow_id:
            query += " AND id = ?"
            args.append(workflow_id)
        query += " ORDER BY id, version DESC LIMIT ?"
        args.append(limit)
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, args).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["definition"] = self._json_value(item.pop("definition_json"))
            item["enabled"] = bool(item.get("enabled"))
            result.append(item)
        return result

    def create_workflow_trigger(self, *, project_id: str, workflow_id: str, interval_seconds: float,
                                payload: dict[str, Any] | None = None, next_run: float | None = None,
                                trigger_id: str | None = None) -> dict[str, Any]:
        if float(interval_seconds) < 10:
            raise ValueError("interval_seconds 不能小于 10 秒")
        now = time.time()
        trigger_id = trigger_id or uuid.uuid4().hex
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO workflow_triggers(id, project_id, workflow_id, interval_seconds, payload_json, next_run, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (trigger_id, project_id, workflow_id, float(interval_seconds), json.dumps(payload or {}, ensure_ascii=False), next_run or now, now, now),
            )
            row = conn.execute("SELECT * FROM workflow_triggers WHERE id = ?", (trigger_id,)).fetchone()
        item = dict(row) if row else {}
        item["payload"] = self._json_value(item.pop("payload_json"))
        item["enabled"] = bool(item.get("enabled"))
        return item

    def list_workflow_triggers(self, project_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM workflow_triggers WHERE project_id = ? ORDER BY next_run LIMIT ?", (project_id, limit)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = self._json_value(item.pop("payload_json"))
            item["enabled"] = bool(item.get("enabled"))
            result.append(item)
        return result

    def release_due_triggers(self, *, limit: int = 50) -> int:
        """Materialize due interval triggers into queue jobs atomically."""
        now = time.time()
        created = 0
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT * FROM workflow_triggers WHERE enabled = 1 AND next_run <= ? ORDER BY next_run LIMIT ?", (now, max(1, int(limit)))).fetchall()
            for row in rows:
                payload = self._json_value(row["payload_json"])
                job_id = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO job_queue(id, project_id, workflow_id, payload_json, run_after, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (job_id, row["project_id"], row["workflow_id"], json.dumps(payload, ensure_ascii=False), now, now, now),
                )
                next_run = max(now, float(row["next_run"])) + float(row["interval_seconds"])
                conn.execute("UPDATE workflow_triggers SET last_run=?, next_run=?, updated_at=? WHERE id = ?", (now, next_run, now, row["id"]))
                created += 1
        return created
