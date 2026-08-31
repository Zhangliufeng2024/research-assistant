"""PlatformStore 任务域：tasks / task_events / task_steps / agent_runs
、审批、通知、会话标志与产物索引。

工程债拆分（2026-08-31）：从 platform_store.py 抽出。
"""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class TaskMixin:
    def create_task(
        self,
        *,
        task_id: str,
        project_id: str,
        query: str,
        mode: str,
        output_dir: str | None = None,
        metadata: dict[str, Any] | None = None,
        source_session_id: str | None = None,
    ) -> dict[str, Any]:
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO tasks(id, project_id, query, mode, status, output_dir, "
                "metadata_json, created_at, updated_at, started_at, source_session_id) "
                "VALUES(?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)",
                (
                    task_id, project_id, query, mode, output_dir,
                    json.dumps(metadata or {}, ensure_ascii=False), now, now, now,
                    source_session_id,
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

    def _update_step_conn(
        self, conn: sqlite3.Connection, task_id: str, step_id: str, *,
        status: str, error: str = "",
    ) -> None:
        """连接级 update_step：事务归属由调用方（transaction/各公开方法）管理。"""
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
        conn.execute(f"UPDATE task_steps SET {', '.join(fields)} WHERE task_id = ? AND id = ?", values)
        run_status = "complete" if status == "done" else status
        conn.execute(
            "UPDATE agent_runs SET status=?, error=?, started_at=CASE WHEN ?='running' THEN COALESCE(started_at, ?) ELSE started_at END, "
            "finished_at=CASE WHEN ? IN ('complete','failed','cancelled','skipped') THEN ? ELSE finished_at END, updated_at=? "
            "WHERE task_id=? AND agent_id=?",
            (run_status, error, status, now, run_status, now, now, task_id, step_id),
        )

    def update_step(self, task_id: str, step_id: str, *, status: str, error: str = "") -> None:
        with self._lock, self._connect() as conn:
            self._update_step_conn(conn, task_id, step_id, status=status, error=error)

    def _list_steps_conn(self, conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
        rows = conn.execute("SELECT * FROM task_steps WHERE task_id = ? ORDER BY rowid", (task_id,)).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["depends_on"] = json.loads(item.pop("depends_on_json"))
            result.append(item)
        return result

    def list_steps(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            return self._list_steps_conn(conn, task_id)

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
        with self._lock, self._connect() as conn:
            self._update_agent_run_conn(
                conn, task_id, agent_id, status=status, role=role, model=model,
                budget=budget, outputs=outputs, error=error,
            )
            row = conn.execute(
                "SELECT * FROM agent_runs WHERE task_id = ? AND agent_id = ?",
                (task_id, agent_id),
            ).fetchone()
        return self._decode_research_row(row)

    def _update_agent_run_conn(
        self, conn: sqlite3.Connection, task_id: str, agent_id: str, *,
        status: str | None = None, role: str | None = None, model: str | None = None,
        budget: dict[str, Any] | None = None, outputs: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """连接级 update_agent_run：事务归属调用方（task_hub 帧级合并用）。"""
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
        conn.execute(
            f"UPDATE agent_runs SET {', '.join(fields)} "
            "WHERE task_id = ? AND agent_id = ?",
            values,
        )

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

    def _append_event_conn(
        self, conn: sqlite3.Connection, task_id: str, payload: dict[str, Any],
    ) -> int:
        """连接级 append_event：不自带 BEGIN，事务归属调用方管理。"""
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

    def append_event(self, task_id: str, payload: dict[str, Any]) -> int:
        with self._lock, self._connect() as conn:
            # BEGIN IMMEDIATE：先拿写锁再读 MAX(seq)，避免并发追加拿到相同序号。
            conn.execute("BEGIN IMMEDIATE")
            return self._append_event_conn(conn, task_id, payload)

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

    def upsert_artifact(
        self, session_id: str, path: str | Path, *, workspace: str | Path,
    ) -> bool:
        """A+ 阶段 2 / F-2：**推模式**回填单条产物索引。

        此前 artifacts 表只在有人调用 ``/chat/sessions/{id}/manifest`` 时才被
        整体重建（拉模式）——没人查就不记，导致它与其他 5 套产物记录互不一致。
        推模式让工具写入成功即落表，这张表因此可成为**唯一权威源**；
        manifest.json 与 artifact_reviews 降为派生视图。

        语义上是 ``replace_artifacts`` 的单行增量版：同一 (session_id, path)
        重复写入即更新（与文件系统的最新状态对齐），不会堆重复行。

        Returns:
            是否成功登记（path 不在工作区内 / 文件已消失 / DB 错误均返回 False）。
        """
        try:
            resolved = Path(path).resolve()
            root = Path(workspace).resolve()
            rel = resolved.relative_to(root).as_posix()
            stat = resolved.stat()
        except (ValueError, OSError):
            return False
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO artifacts(session_id, path, name, ext, size, mtime) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    session_id, rel, resolved.name, resolved.suffix.lower(),
                    int(stat.st_size), float(stat.st_mtime),
                ),
            )
        return True

    def replace_artifacts(
        self, session_id: str, entries: list[dict[str, Any]],
    ) -> int:
        """整会话替换产物索引（manifest 重建时调用；幂等）。"""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM artifacts WHERE session_id = ?", (session_id,))
            conn.executemany(
                "INSERT OR REPLACE INTO artifacts(session_id, path, name, ext, size, mtime) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                [
                    (
                        session_id,
                        str(e.get("path") or ""),
                        str(e.get("name") or ""),
                        str(e.get("ext") or ""),
                        int(e.get("size") or 0),
                        float(e.get("mtime") or 0.0),
                    )
                    for e in entries
                ],
            )
            return len(entries)

    def drop_artifacts(self, session_id: str) -> None:
        """会话删除时同步清索引（防幽灵命中）。"""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM artifacts WHERE session_id = ?", (session_id,))

    def search_artifacts(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """产物文件名/路径子串检索（前端 Ctrl+K 与 /api/search 的 artifacts scope）。"""
        needle = f"%{query.strip()}%"
        limit = max(1, min(int(limit), 100))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, path, name, ext, size, mtime FROM artifacts "
                "WHERE name LIKE ? OR path LIKE ? ORDER BY mtime DESC LIMIT ?",
                (needle, needle, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def artifacts_overview(self) -> dict[str, Any]:
        """artifacts 表只读汇总：总数、去重会话数与按扩展名分布（overview 端点用）。"""
        with self._lock, self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0])
            sessions = int(
                conn.execute("SELECT COUNT(DISTINCT session_id) FROM artifacts").fetchone()[0]
            )
            by_ext = {
                row["ext"] or "(none)": int(row["n"])
                for row in conn.execute(
                    "SELECT ext, COUNT(*) AS n FROM artifacts GROUP BY ext ORDER BY n DESC"
                ).fetchall()
            }
        return {"total": total, "sessions": sessions, "by_ext": by_ext}

    def recent_project_events(self, project_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """跨任务最近事件若干条（overview 端点只读聚合，不区分任务逐条拉取）。"""
        limit = max(1, min(int(limit), 100))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT e.task_id, e.seq, e.ts, e.type, e.payload_json FROM task_events e "
                "JOIN tasks t ON t.id = e.task_id WHERE t.project_id = ? "
                "ORDER BY e.ts DESC, e.task_id DESC, e.seq DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except json.JSONDecodeError:
                continue
            events.append({
                "task_id": row["task_id"],
                "seq": row["seq"],
                "ts": row["ts"],
                "type": row["type"],
                "payload": payload,
            })
        return events

    def set_session_flags(
        self,
        session_id: str,
        *,
        pinned: bool | None = None,
        archived: bool | None = None,
    ) -> dict[str, Any]:
        """设置/清除会话的置顶、归档标志（跨端持久，替代 localStorage 归档）。"""
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT pinned, archived FROM session_meta WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            cur_pinned = bool(row["pinned"]) if row else False
            cur_archived = bool(row["archived"]) if row else False
            new_pinned = cur_pinned if pinned is None else bool(pinned)
            new_archived = cur_archived if archived is None else bool(archived)
            conn.execute(
                "INSERT OR REPLACE INTO session_meta(session_id, pinned, archived, updated_at) "
                "VALUES(?, ?, ?, ?)",
                (session_id, int(new_pinned), int(new_archived), now),
            )
            return {"session_id": session_id, "pinned": new_pinned, "archived": new_archived}

    def get_session_flags_map(self, session_ids: list[str]) -> dict[str, dict[str, bool]]:
        """批量取会话标志；无记录的会话不出现（调用方按默认 False 处理）。"""
        if not session_ids:
            return {}
        placeholders = ",".join("?" for _ in session_ids)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT session_id, pinned, archived FROM session_meta "
                f"WHERE session_id IN ({placeholders})",
                session_ids,
            ).fetchall()
        return {
            str(r["session_id"]): {
                "pinned": bool(r["pinned"]),
                "archived": bool(r["archived"]),
            }
            for r in rows
        }

    def count_tasks_for_sessions(self, session_ids: list[str]) -> dict[str, int]:
        """每个会话派生的任务数（会话列表徽标用）。"""
        if not session_ids:
            return {}
        placeholders = ",".join("?" for _ in session_ids)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT source_session_id, COUNT(*) AS n FROM tasks "
                f"WHERE source_session_id IN ({placeholders}) GROUP BY source_session_id",
                session_ids,
            ).fetchall()
        return {str(r["source_session_id"]): int(r["n"]) for r in rows}

    def search_runs(
        self,
        project_id: str | None = None,
        *,
        query: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """历史运行检索：标题子串 + 状态过滤 + 分页（替换前端 slice(0,20) 硬截断）。"""
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        where: list[str] = []
        args: list[Any] = []
        if project_id:
            where.append("project_id = ?")
            args.append(project_id)
        if query:
            where.append("query LIKE ?")
            args.append(f"%{query}%")
        if status:
            where.append("status = ?")
            args.append(status)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        with self._lock, self._connect() as conn:
            total = int(
                conn.execute(f"SELECT COUNT(*) AS n FROM tasks {clause}", args).fetchone()["n"]
            )
            rows = conn.execute(
                f"SELECT * FROM tasks {clause} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            ).fetchall()
        return {
            "total": total,
            "items": [self._decode_task(row) or {} for row in rows],
            "limit": limit,
            "offset": offset,
        }
