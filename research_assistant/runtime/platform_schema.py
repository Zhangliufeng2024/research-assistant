"""Platform schema：建表 DDL 与迁移（P2-4 从 platform_store._initialize 拆出）。

**只做机械搬移**：SQL 与迁移语句逐行原样保留（含注释里的版本背景），只是
从 409 行的 `_initialize` 方法体里搬出来，让 platform_store 退回「仓储门面」，
schema 演进有独立落点。版本常量一并迁到这里，由 platform_store 再导出——
`from ...platform_store import SCHEMA_VERSION` 的既有导入不受影响。
"""
from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 12
PROJECT_OS_VERSION = 1


def initialize_schema(conn: sqlite3.Connection) -> None:
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
            -- R17：会话级 UI 状态（置顶/归档）。会话事实源仍是
            -- .ra/sessions/<id>/ 目录，本表只存跨端持久的标志位——
            -- 替代原先 localStorage 归档（换浏览器即丢）。
            CREATE TABLE IF NOT EXISTS session_meta (
                session_id TEXT PRIMARY KEY,
                pinned INTEGER NOT NULL DEFAULT 0,
                archived INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            );
            -- 迭代2：产物清单索引（manifest 端点回填，artifacts 检索 scope 用）。
            CREATE TABLE IF NOT EXISTS artifacts (
                session_id TEXT NOT NULL,
                path TEXT NOT NULL,
                name TEXT NOT NULL,
                ext TEXT NOT NULL DEFAULT '',
                size INTEGER NOT NULL DEFAULT 0,
                mtime REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(session_id, path)
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_name
                ON artifacts(name);
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
        # R17 v11：任务记录来源会话（对话↔任务互链的锚点）。
        task_columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)")}
        if "source_session_id" not in task_columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN source_session_id TEXT")
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('project_os_version', ?)",
            (str(PROJECT_OS_VERSION),),
        )
