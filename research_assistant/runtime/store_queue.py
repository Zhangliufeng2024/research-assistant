"""PlatformStore 队列域：job_queue / resource_leases / workflow 定义与触发器。

工程债拆分（2026-08-31）：从 platform_store.py 抽出。
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any


class QueueMixin:
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
        #
        # A+ 阶段 1 / C-6：显式 BEGIN IMMEDIATE。Python 的 sqlite3 默认是
        # deferred 事务，读快照与其他进程的写并发时，升级为写会立刻拿到
        # SQLITE_BUSY_SNAPSHOT（**不等待** busy_timeout），导致这次状态转换
        # 被静默丢掉。取写锁在前可以彻底避免。与 claim_job 口径一致。
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
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
            # A+ 阶段 1 / C-6：**这个方法最需要** BEGIN IMMEDIATE。
            #
            # 它是典型的 read-modify-write：先 SELECT attempts/max_attempts 读
            # 出一个快照，再据其决定 status='failed' 还是回队重跑。deferred
            # 事务下，若读快照之后有别的进程（多 worker 场景）提交了对同一行
            # 的修改，升级写会立刻抛 SQLITE_BUSY_SNAPSHOT——不等待 busy_timeout
            # ——结果是这次失败/重试判定被整条丢掉，作业卡在 running 直到租约
            # 过期。取写锁在前才能让这三步真正原子。
            conn.execute("BEGIN IMMEDIATE")
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
            # A+ 阶段 1 / C-6：同 complete_job —— 先取写锁，避免 deferred
            # 事务在写回后立即读回时撞上并发提交。
            conn.execute("BEGIN IMMEDIATE")
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
            # A+ 阶段 1 / C-6：与 claim_job 同口径先取写锁。回收过期作业与
            # 并发领取是同一批行的竞争双方，两者都必须在写锁下判定。
            conn.execute("BEGIN IMMEDIATE")
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

    def set_workflow_trigger_enabled(
        self, trigger_id: str, project_id: str, *, enabled: bool,
    ) -> dict[str, Any] | None:
        """R17：触发器启停开关（此前 enabled 字段只读、UI 不可管理）。"""
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE workflow_triggers SET enabled = ?, updated_at = ? "
                "WHERE id = ? AND project_id = ?",
                (int(bool(enabled)), time.time(), trigger_id, project_id),
            )
            row = conn.execute(
                "SELECT * FROM workflow_triggers WHERE id = ? AND project_id = ?",
                (trigger_id, project_id),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["payload"] = self._json_value(item.pop("payload_json"))
        item["enabled"] = bool(item.get("enabled"))
        return item

    def delete_workflow_trigger(self, trigger_id: str, project_id: str) -> bool:
        """R17：删除触发器（此前 UI 无删除入口）。"""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM workflow_triggers WHERE id = ? AND project_id = ?",
                (trigger_id, project_id),
            )
            return cursor.rowcount > 0

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
