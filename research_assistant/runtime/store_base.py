"""PlatformStore 公共设施：连接、事务、schema 初始化与 JSON 解码。

工程债拆分（2026-08-31）：从 platform_store.py 抽出。
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

from .platform_schema import initialize_schema


class StoreBase:
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
        # busy_timeout 与 timeout=30.0 等价，显式写出以说明意图：多线程
        # （scheduler/janitor/UI 线程）并发写时等锁而不是立刻抛 SQLITE_BUSY。
        # 注：未采用线程本地持久连接——那会让 sqlite 文件句柄常驻，Windows
        # 上 pytest tmp_path 清理会因文件被锁而失败（影响 200+ 用例）。
        # 降低建连开销的正解是调用方合并事务（见 task_hub._persist_frame）。
        conn.execute("PRAGMA busy_timeout = 30000")
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
        """DDL 与迁移见 platform_schema.initialize_schema（P2-4 拆分）。"""
        with self._lock, self._connect() as conn:
            initialize_schema(conn)

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

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """把多次写操作合并为**一次建连 + 一个事务**（P2-2）。

        典型调用方是 task_hub._persist_frame：一帧要更新 step + 追加 event，
        旧实现每个操作各自 `_connect()`，一帧最多 4-5 次建连。现在调用方在
        本上下文内用 *_conn 系列方法复用同一个连接，退出时统一 commit
        （_connect 的既有语义），异常统一 rollback。

        锁语义：整个事务期间持有 self._lock（RLock 可重入，嵌套调用安全）。
        """
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            yield conn

    def purge_old_db_events(self, days: float) -> dict[str, int]:
        """P2-6：清理超过保留期的 DB 行，返回各表删除行数。

        - ``task_events``：按 ``ts`` 清。事件流是回放用增量，任务终态后只
          有近期回放价值；90 天前的回放窗口已无意义（断线续播靠环形缓冲
          与近期事件，恢复任务走 checkpoint/history，不依赖陈旧事件）。
        - ``notifications``：已读超期删除；**未读**超期同样删除——90 天未读
          的通知已无行动价值，留着只会让列表无限膨胀（此前两表只增不删，
          是 DB 单调增长的直接来源）。
        - ``tasks``（工程债扩展）：**仅**终态任务（complete/failed/cancelled/
          interrupted）且 ``finished_at`` 超期时整任务删除。子表经 FK 级联
          清理（task_events/task_steps/agent_runs CASCADE，approvals/runs/
          threads/reviews SET NULL）；``job_queue.task_id`` 无外键，先置空。
          运行中（queued/running/stopping）任务永不触碰。
        - ``artifacts``（工程债扩展）：产物索引按 ``mtime``（文件修改时间）
          超期删除——索引是派生视图，删行不影响文件与 artifact_reviews。
        """
        cutoff = time.time() - max(days, 0.0) * 86400.0
        removed = {"task_events": 0, "notifications": 0, "tasks": 0, "artifacts": 0}
        with self._lock, self._connect() as conn:
            removed["task_events"] = conn.execute(
                "DELETE FROM task_events WHERE ts < ?", (cutoff,)
            ).rowcount
            removed["notifications"] = conn.execute(
                "DELETE FROM notifications WHERE "
                "(read_at IS NOT NULL AND read_at < ?) OR created_at < ?",
                (cutoff, cutoff),
            ).rowcount
            rows = conn.execute(
                "SELECT id FROM tasks WHERE status IN "
                "('complete','failed','cancelled','interrupted') "
                "AND finished_at IS NOT NULL AND finished_at < ?",
                (cutoff,),
            ).fetchall()
            task_ids = [str(row["id"]) for row in rows]
            if task_ids:
                # job_queue.task_id 是纯文本列（无 FK）：先置空防悬挂引用。
                conn.executemany(
                    "UPDATE job_queue SET task_id = NULL WHERE task_id = ?",
                    [(tid,) for tid in task_ids],
                )
                for task_id in task_ids:
                    conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                removed["tasks"] = len(task_ids)
            removed["artifacts"] = conn.execute(
                "DELETE FROM artifacts WHERE mtime < ?", (cutoff,)
            ).rowcount
        return removed

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        """R17：跨端 UI 设置（verbosity 等），存 meta 表，key 带 ``setting.`` 前缀。"""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?", (f"setting.{key}",),
            ).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                (f"setting.{key}", str(value)),
            )

    @staticmethod
    def _json_value(raw: str | None) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

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
