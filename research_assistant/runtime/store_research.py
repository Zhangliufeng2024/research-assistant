"""PlatformStore 科研对象域：线程/回合/主张/证据/决策/provenance、
分析运行、产物审阅与项目导出。

工程债拆分（2026-08-31）：从 platform_store.py 抽出。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from .platform_schema import PROJECT_OS_VERSION, SCHEMA_VERSION


class ResearchMixin:
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
        with self._lock, self._connect() as conn:
            resolved_id = self._append_agent_item_conn(
                conn, thread_id=thread_id, project_id=project_id,
                item_type=item_type, content=content, turn_id=turn_id,
                role=role, title=title, status=status, item_id=item_id,
            )
            result = conn.execute(
                "SELECT * FROM agent_items WHERE id = ?",
                (resolved_id,),
            ).fetchone()
        item = self._decode_research_row(result) or {}
        if "content_json" in item:
            item["content"] = self._json_value(item.pop("content_json"))
        return item

    def _append_agent_item_conn(
        self, conn: sqlite3.Connection, *, thread_id: str, project_id: str,
        item_type: str, content: dict[str, Any] | None = None,
        turn_id: str | None = None, role: str | None = None, title: str = "",
        status: str = "complete", item_id: str | None = None,
    ) -> str:
        """连接级 append_agent_item：事务归属调用方（task_hub 帧级合并用）。

        Returns:
            新 item_id。
        """
        if conn.execute(
            "SELECT 1 FROM threads WHERE id = ? AND project_id = ?",
            (thread_id, project_id),
        ).fetchone() is None:
            raise ValueError("线程不存在")
        now, item_id = time.time(), item_id or uuid.uuid4().hex
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_items WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        seq = int(row[0])
        conn.execute(
            "INSERT INTO agent_items(id, thread_id, turn_id, seq, type, status, role, title, content_json, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id, thread_id, turn_id, seq, item_type, status, role, title,
                json.dumps(content or {}, ensure_ascii=False), now, now,
            ),
        )
        conn.execute("UPDATE threads SET updated_at=? WHERE id = ?", (now, thread_id))
        return item_id

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
        # 工程债：有界惰性遍历替代 sorted(rglob) 全量物化（上限由下方
        # max_files 截断兜底；去掉排序只影响枚举顺序，不影响产物集合）。
        for path in target.rglob("*"):
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
