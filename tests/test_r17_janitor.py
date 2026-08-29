"""R17 Janitor 分层清理测试。

红线用例：热层数据零触碰；一切删除/压缩先写审计日志。
会话年龄通过 run.json 的 updated_at 注入（_session_age_days 的权威来源）。
"""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path

from research_assistant.runtime.janitor import (
    AUDIT_FILE,
    JanitorConfig,
    run_janitor,
)
from research_assistant.runtime.platform_store import PlatformStore

NOW = time.time()
DAY = 86400.0


def _make_session(cwd: Path, name: str, *, age_days: float) -> Path:
    run_dir = cwd / ".ra" / "sessions" / name
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text(
        json.dumps({
            "query": name, "mode": "chat",
            "created_at": NOW - age_days * DAY,
            "updated_at": NOW - age_days * DAY,
        }),
        encoding="utf-8",
    )
    return run_dir


def _audit_records(cwd: Path) -> list[dict]:
    path = cwd / ".ra" / AUDIT_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _cfg(**kw) -> JanitorConfig:
    defaults = dict(
        warm_days=30, cold_days=90, changes_cap_mb=500,
        events_rotate_mb=10, events_keep=3, tmp_days=7,
        tool_outputs_days=7, audit_rotate_mb=5, audit_keep=3,
    )
    defaults.update(kw)
    return JanitorConfig(**defaults)


class TestWarmLayer:
    def test_old_session_archived(self, tmp_path):
        store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
        _make_session(tmp_path, "old_sess", age_days=45)
        stats = run_janitor(tmp_path, store, _cfg())
        assert stats["archived"] == 1
        flags = store.get_session_flags_map(["old_sess"])["old_sess"]
        assert flags["archived"] is True

    def test_hot_session_untouched(self, tmp_path):
        """红线：热层零触碰。"""
        store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
        run_dir = _make_session(tmp_path, "hot_sess", age_days=2)
        (run_dir / "events.jsonl").write_text("x" * 100, encoding="utf-8")
        stats = run_janitor(tmp_path, store, _cfg())
        assert stats["archived"] == 0
        assert (run_dir / "events.jsonl").exists()
        assert "hot_sess" not in store.get_session_flags_map(["hot_sess"])

    def test_already_archived_not_duplicated(self, tmp_path):
        store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
        _make_session(tmp_path, "s", age_days=45)
        store.set_session_flags("s", archived=True)
        stats = run_janitor(tmp_path, store, _cfg())
        assert stats["archived"] == 0


class TestColdLayer:
    def test_cold_archived_gzipped_and_drafts_removed(self, tmp_path):
        store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
        run_dir = _make_session(tmp_path, "cold_sess", age_days=120)
        (run_dir / "events.jsonl").write_text('{"k":1}\n' * 10, encoding="utf-8")
        store.set_session_flags("cold_sess", archived=True)
        drafts = tmp_path / "outputs" / "cold_sess" / "drafts"
        drafts.mkdir(parents=True)
        (drafts / "tmp.md").write_text("draft", encoding="utf-8")
        artifacts = tmp_path / "outputs" / "cold_sess" / "artifacts"
        artifacts.mkdir(parents=True)
        (artifacts / "final.docx").write_text("keep", encoding="utf-8")

        stats = run_janitor(tmp_path, store, _cfg())
        assert stats["gzipped"] == 1
        assert stats["drafts_removed"] == 1
        assert not (run_dir / "events.jsonl").exists()
        with gzip.open(run_dir / "events.jsonl.gz", "rt") as fh:
            assert fh.read().startswith('{"k":1}')
        assert not drafts.exists()
        assert (artifacts / "final.docx").exists()  # artifacts 保留

    def test_cold_but_not_archived_untouched(self, tmp_path):
        """冷层只处理已归档会话：未归档的超龄会话不压缩（等温层先标记）。"""
        store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
        run_dir = _make_session(tmp_path, "s", age_days=120)
        (run_dir / "events.jsonl").write_text("data", encoding="utf-8")
        stats = run_janitor(tmp_path, store, _cfg())
        assert stats["gzipped"] == 0
        assert (run_dir / "events.jsonl").exists()


class TestChangesLru:
    def test_evicts_oldest_over_cap(self, tmp_path):
        """LRU 淘汰最旧的快照 bin（经版本存储，同步维护索引）。

        构造改为**真实的变更结构**（``<change_id>/{before,after}.bin`` +
        ``index.json``）——旧用例直接在 ``changes/`` 下丢裸 .json 文件，
        那既不是实际布局，也测不出"可能顺带删掉 index.json"的隐患。
        """
        import os

        from research_assistant.artifacts import ArtifactVersionStore

        store = ArtifactVersionStore(tmp_path)
        target = tmp_path / "paper.md"
        target.write_text("v0", encoding="utf-8")

        # 每侧 1KB，3 条记录共 6KB；cap 4KB → 需淘汰约 2KB（即 2 个 bin）
        ids: list[str] = []
        for i in range(3):
            before = (f"v{i}" * 512).encode()       # 1024 bytes
            after = (f"v{i + 1}" * 512).encode()    # 1024 bytes
            rec = store.record(target, before, after, tool="write_file")
            assert rec is not None
            ids.append(rec["id"])
            # 让 before.bin 的 mtime 拉开梯度：越早创建的越旧
            old = NOW - (3 - i) * 100
            os.utime(store.root / rec["id"] / "before.bin", (old, old))

        stats = run_janitor(tmp_path, None, _cfg(changes_cap_mb=4 / 1024))

        assert stats["changes_evicted"] >= 1
        assert not (store.root / ids[0] / "before.bin").exists(), "最旧的快照未被淘汰"
        assert (store.root / ids[2] / "before.bin").exists()
        # index.json 安然无恙（旧实现的 rglob("*") 在极端排序下可能把它删掉）
        assert (tmp_path / ".ra" / "changes" / "index.json").exists()

    def test_eviction_marks_index_so_restore_refuses(self, tmp_path):
        """F-1 核心回归：淘汰 bin 必须同步标记索引。

        旧实现只 unlink 不动索引，留下"索引说有、磁盘没有"的悬空记录，
        用户点「恢复」时 restore 读不到快照就会**删掉当前文件**。
        """
        from research_assistant.artifacts import ArtifactVersionStore
        from research_assistant.artifacts.versioning import SnapshotMissingError

        store = ArtifactVersionStore(tmp_path)
        target = tmp_path / "data.txt"
        target.write_text("原始内容", encoding="utf-8")

        rec = store.record(target, "原始内容".encode(), "改后内容".encode(), tool="write_file")
        assert rec is not None
        cid = rec["id"]

        # 手工淘汰 before 快照（走与 Janitor 相同的方法）
        assert store.discard_snapshot(cid, "before") is True

        refreshed = store.get(cid)
        assert refreshed is not None
        assert refreshed["before_evicted"] is True
        # 历史事实字段不被改写（False 表示"当时不存在"，含义不同，不能混用）
        assert refreshed["before_exists"] is True

        try:
            store.restore(cid, "before")
        except SnapshotMissingError:
            pass
        else:  # pragma: no cover
            raise AssertionError("快照缺失时未拒绝恢复 —— 会删掉用户文件（F-1 回归）")

        assert target.read_text(encoding="utf-8") == "原始内容", "文件被误删"

    def test_reconcile_flags_pre_existing_dangling_records(self, tmp_path):
        """存量修复：老工作区里已被淘汰但索引未标记的记录要能被补齐。"""
        from research_assistant.artifacts import ArtifactVersionStore
        from research_assistant.artifacts.versioning import SnapshotMissingError

        store = ArtifactVersionStore(tmp_path)
        target = tmp_path / "old.md"
        target.write_text("x", encoding="utf-8")
        rec = store.record(target, b"x", b"y", tool="write_file")
        assert rec is not None

        # 模拟 F-1 修复前 Janitor 的行为：只删 bin，不动索引
        (store.root / rec["id"] / "after.bin").unlink()

        assert store.reconcile_snapshots() == 1
        assert store.get(rec["id"])["after_evicted"] is True

        try:
            store.restore(rec["id"], "after")
        except SnapshotMissingError:
            pass
        else:  # pragma: no cover
            raise AssertionError("存量悬空记录仍可被恢复（F-1 回归）")

        # 幂等
        assert store.reconcile_snapshots() == 0

    def test_restore_still_deletes_when_side_never_existed(self, tmp_path):
        """反向断言：新建动作的 before 侧本就不存在，恢复它=撤销新建=删文件。

        收紧 F-1 不能把这个**正确**的删除语义一起堵死。
        """
        from research_assistant.artifacts import ArtifactVersionStore

        store = ArtifactVersionStore(tmp_path)
        new_file = tmp_path / "created.md"
        rec = store.record(new_file, None, "新建的内容".encode(), tool="write_file")
        assert rec is not None
        new_file.write_bytes("新建的内容".encode())

        store.restore(rec["id"], "before")

        assert not new_file.exists(), "撤销新建未能删除文件"


class TestRotation:
    def test_oversized_events_rotated(self, tmp_path):
        run_dir = _make_session(tmp_path, "s", age_days=1)
        events = run_dir / "events.jsonl"
        events.write_text("x" * 2048, encoding="utf-8")
        stats = run_janitor(tmp_path, None, _cfg(events_rotate_mb=1 / 1024))
        assert stats["rotated"] == 1
        assert not events.exists()
        assert (run_dir / "events.jsonl.1").exists()

    def test_rotation_keeps_n_generations(self, tmp_path):
        run_dir = _make_session(tmp_path, "s", age_days=1)
        for i in (1, 2, 3):
            (run_dir / f"events.jsonl.{i}").write_text(f"gen{i}", encoding="utf-8")
        (run_dir / "events.jsonl").write_text("x" * 2048, encoding="utf-8")
        run_janitor(tmp_path, None, _cfg(events_rotate_mb=1 / 1024, events_keep=3))
        assert (run_dir / "events.jsonl.1").read_text().startswith("x")
        assert (run_dir / "events.jsonl.2").read_text() == "gen1"
        assert (run_dir / "events.jsonl.3").read_text() == "gen2"
        # gen3 被丢弃（超出代数）


class TestToolOutputsSweep:
    """A+ 阶段 2 / F-6：.ra/tool_outputs/ 此前没有任何清理路径。"""

    def _make_outputs(self, cwd: Path, age_days: float) -> Path:
        import os

        root = cwd / ".ra" / "tool_outputs"
        root.mkdir(parents=True, exist_ok=True)
        path = root / "ext_abc.txt"
        path.write_text("oversized tool result", encoding="utf-8")
        old = NOW - age_days * DAY
        os.utime(path, (old, old))
        return path

    def test_old_outputs_removed(self, tmp_path):
        path = self._make_outputs(tmp_path, age_days=30)
        stats = run_janitor(tmp_path, None, _cfg(tool_outputs_days=7))
        assert stats["tool_outputs_removed"] == 1
        assert not path.exists()

    def test_recent_outputs_kept(self, tmp_path):
        path = self._make_outputs(tmp_path, age_days=1)
        stats = run_janitor(tmp_path, None, _cfg(tool_outputs_days=7))
        assert stats["tool_outputs_removed"] == 0
        assert path.exists()

    def test_ttl_is_configurable(self, tmp_path):
        path = self._make_outputs(tmp_path, age_days=1)
        run_janitor(tmp_path, None, _cfg(tool_outputs_days=0.5))
        assert not path.exists(), "TTL 收紧后 1 天的产物应被清掉"

    def test_deletion_is_audited_before_delete(self, tmp_path):
        """红线：一切删除先写审计日志。"""
        self._make_outputs(tmp_path, age_days=30)
        run_janitor(tmp_path, None, _cfg(tool_outputs_days=7))
        actions = [r["action"] for r in _audit_records(tmp_path)]
        assert "delete_tool_output" in actions

    def test_missing_directory_is_noop(self, tmp_path):
        stats = run_janitor(tmp_path, None, _cfg(tool_outputs_days=7))
        assert stats["tool_outputs_removed"] == 0


class TestAuditRotation:
    """A+ 阶段 2 / F-6：审计日志此前只 append 不轮转。"""

    def _make_audit(self, cwd: Path, size_bytes: int) -> Path:
        path = cwd / ".ra" / AUDIT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x" * size_bytes, encoding="utf-8")
        return path

    def test_oversized_audit_rotated(self, tmp_path):
        path = self._make_audit(tmp_path, 4096)
        stats = run_janitor(tmp_path, None, _cfg(audit_rotate_mb=1 / 1024))
        assert stats["audit_rotated"] == 1
        assert not path.exists()
        assert path.with_name(f"{AUDIT_FILE}.1").exists()

    def test_small_audit_untouched(self, tmp_path):
        path = self._make_audit(tmp_path, 128)
        stats = run_janitor(tmp_path, None, _cfg(audit_rotate_mb=5))
        assert stats["audit_rotated"] == 0
        assert path.exists()

    def test_rotation_keeps_n_generations(self, tmp_path):
        path = self._make_audit(tmp_path, 4096)
        # 预置两代，cap=2 → 最旧一代（.2）应被丢弃
        (path.with_name(f"{AUDIT_FILE}.1")).write_text("g1", encoding="utf-8")
        (path.with_name(f"{AUDIT_FILE}.2")).write_text("g2", encoding="utf-8")
        stats = run_janitor(
            tmp_path, None, _cfg(audit_rotate_mb=1 / 1024, audit_keep=2),
        )

        assert stats["audit_rotated"] == 1
        assert (path.with_name(f"{AUDIT_FILE}.2")).read_text() == "g1"
        assert not (path.with_name(f"{AUDIT_FILE}.3")).exists()

    def test_rotation_does_not_lose_this_rounds_audit(self, tmp_path):
        """轮转在其它清理层之后执行，本轮回滚的审计记录不能被自己吞掉。"""
        import os

        self._make_audit(tmp_path, 4096)
        old = NOW - 30 * DAY
        stale = tmp_path / ".ra" / "tool_outputs" / "ext_old.txt"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text("y", encoding="utf-8")
        os.utime(stale, (old, old))

        run_janitor(tmp_path, None, _cfg(tool_outputs_days=7, audit_rotate_mb=1 / 1024))

        # 轮转后主文件可能不存在（本轮无后续写入），逐代聚合所有仍在的审计内容
        joined = ""
        for gen in ("", ".1", ".2", ".3"):
            p = tmp_path / ".ra" / f"{AUDIT_FILE}{gen}"
            if p.exists():
                joined += p.read_text(encoding="utf-8")
        assert "delete_tool_output" in joined, "本轮审计记录在轮转中丢失"


class TestTmpSweep:
    def test_old_tmp_removed_fresh_kept(self, tmp_path):
        import os
        tmp = tmp_path / "tmp"
        tmp.mkdir()
        old_file = tmp / "old.txt"
        old_file.write_text("old", encoding="utf-8")
        os.utime(old_file, (NOW - 10 * DAY, NOW - 10 * DAY))
        fresh = tmp / "fresh.txt"
        fresh.write_text("fresh", encoding="utf-8")
        stats = run_janitor(tmp_path, None, _cfg())
        assert stats["tmp_removed"] == 1
        assert not old_file.exists() and fresh.exists()


class TestAudit:
    def test_every_action_logged(self, tmp_path):
        store = PlatformStore(tmp_path / ".ra" / "platform.sqlite3")
        _make_session(tmp_path, "s1", age_days=45)
        _make_session(tmp_path, "s2", age_days=50)
        run_janitor(tmp_path, store, _cfg())
        records = _audit_records(tmp_path)
        assert len(records) == 2
        assert all(r["action"] == "archive" for r in records)
        assert all("reason" in r and "ts" in r for r in records)

    def test_no_action_no_audit(self, tmp_path):
        run_janitor(tmp_path, None, _cfg())
        assert _audit_records(tmp_path) == []
