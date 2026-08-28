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
        changes = tmp_path / ".ra" / "changes"
        changes.mkdir(parents=True)
        # 3 个 1KB 文件，cap 2KB → 淘汰最旧 1 个
        for i in range(3):
            f = changes / f"snap_{i}.json"
            f.write_text("x" * 1024, encoding="utf-8")
            old = NOW - (3 - i) * 100
            import os
            os.utime(f, (old, old))
        stats = run_janitor(tmp_path, None, _cfg(changes_cap_mb=2 / 1024))
        assert stats["changes_evicted"] >= 1
        remaining = sorted(p.name for p in changes.iterdir())
        assert "snap_0.json" not in remaining  # 最旧的被淘汰
        assert "snap_2.json" in remaining


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
