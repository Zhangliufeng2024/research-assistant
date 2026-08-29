"""A+ 阶段 2：文件治理（产物版本覆盖的可见性）。

F-4 —— 执行快照（bash / run_python / apply_patch 的间接写入）在文件数或
字节数超限时**静默丢弃**：原来到 512 个文件直接 return、超 32MB 直接 continue，
回执只报「已记录 N 个变更」。用户看到的是「都记下了」，实际漏掉的那部分
根本无法恢复。

本文件锁定两件事：
  1. 丢弃被**准确计数**；
  2. 计数被**呈现到工具回执**里，让模型和用户知道哪些产物不在版本跟踪内。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research_assistant.tools import registry as registry_mod
from research_assistant.tools.registry import (
    SnapshotStats,
    ToolRegistry,
    _snapshot_exec_outputs,
)

# ---------------------------------------------------------------------------
# SnapshotStats：提示文案
# ---------------------------------------------------------------------------


class TestSnapshotStatsNotice:
    def test_no_gaps_means_empty_notice(self):
        assert SnapshotStats(files_captured=3).notice() == ""
        assert SnapshotStats(files_captured=3).has_gaps is False

    def test_truncation_is_reported(self):
        stats = SnapshotStats(files_captured=512, truncated=True)
        assert stats.has_gaps is True
        text = stats.notice()
        assert "上限" in text and "未被扫描" in text

    def test_oversized_is_reported_with_count(self):
        stats = SnapshotStats(files_captured=1, oversized_skipped=7)
        text = stats.notice()
        assert "7" in text
        assert "MB" in text

    def test_exec_scripts_are_not_treated_as_gaps(self):
        """`_ra_exec_*.py` 是有意排除的执行中间脚本，不该报成「漏网」。"""
        stats = SnapshotStats(files_captured=2, exec_scripts_skipped=5)
        assert stats.has_gaps is False
        assert stats.notice() == ""

    def test_both_gaps_are_combined(self):
        stats = SnapshotStats(files_captured=1, truncated=True, oversized_skipped=2)
        text = stats.notice()
        assert "未被扫描" in text and "2" in text


# ---------------------------------------------------------------------------
# _snapshot_exec_outputs：计数准确性
# ---------------------------------------------------------------------------


class TestSnapshotExecOutputs:
    def test_captures_normal_files(self, tmp_path):
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")
        snap, stats = _snapshot_exec_outputs([tmp_path], tmp_path)

        assert len(snap) == 2
        assert stats.files_captured == 2
        assert stats.has_gaps is False

    def test_exec_scripts_counted_separately(self, tmp_path):
        (tmp_path / "_ra_exec_ab12.py").write_text("code", encoding="utf-8")
        (tmp_path / "keep.txt").write_text("x", encoding="utf-8")
        _snap, stats = _snapshot_exec_outputs([tmp_path], tmp_path)

        assert stats.exec_scripts_skipped == 1
        assert stats.files_captured == 1
        assert stats.has_gaps is False

    def test_oversized_file_is_counted_as_gap(self, tmp_path, monkeypatch):
        """单个文件超过字节上限 → 计入 oversized_skipped，并算作缺口。"""
        monkeypatch.setattr(registry_mod, "_EXEC_SNAPSHOT_MAX_BYTES", 10)
        (tmp_path / "big.txt").write_text("x" * 100, encoding="utf-8")
        (tmp_path / "small.txt").write_text("ok", encoding="utf-8")

        snap, stats = _snapshot_exec_outputs([tmp_path], tmp_path)

        assert stats.oversized_skipped == 1
        assert stats.has_gaps is True
        assert "small.txt" in {p.name for p in snap}
        assert "big.txt" not in {p.name for p in snap}

    def test_cumulative_byte_cap_is_counted(self, tmp_path, monkeypatch):
        """累计超限（每个文件都不大但总量超）同样要计数。"""
        monkeypatch.setattr(registry_mod, "_EXEC_SNAPSHOT_MAX_BYTES", 25)
        for i in range(10):
            (tmp_path / f"f{i}.txt").write_text("x" * 10, encoding="utf-8")

        _snap, stats = _snapshot_exec_outputs([tmp_path], tmp_path)

        assert stats.oversized_skipped > 0, "累计超限未被计数"
        assert stats.has_gaps is True

    def test_file_count_cap_sets_truncated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(registry_mod, "_EXEC_SNAPSHOT_MAX_FILES", 3)
        for i in range(20):
            (tmp_path / f"f{i:02d}.txt").write_text("x", encoding="utf-8")

        snap, stats = _snapshot_exec_outputs([tmp_path], tmp_path)

        assert stats.truncated is True
        assert stats.has_gaps is True
        assert len(snap) == 3

    def test_excluded_dirs_are_not_counted_as_gaps(self, tmp_path):
        """`.ra` / `.git` / `__pycache__` 等是有意排除，不算漏网。"""
        (tmp_path / ".ra").mkdir()
        (tmp_path / ".ra" / "state.json").write_text("{}", encoding="utf-8")
        (tmp_path / "keep.txt").write_text("x", encoding="utf-8")

        _snap, stats = _snapshot_exec_outputs([tmp_path], tmp_path)

        assert stats.has_gaps is False
        assert stats.files_captured == 1


# ---------------------------------------------------------------------------
# 回执：缺口必须出现在模型可见的文本里
# ---------------------------------------------------------------------------


class _NoopProvider:
    """不真正执行命令，只返回一个固定结果（用于回执断言）。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def run_bash(self, **kwargs):
        self.calls.append(kwargs)
        return "done"

    async def run_python(self, **kwargs):
        self.calls.append(kwargs)
        return "done"


class TestExecChangeReceipt:
    def _registry(self, tmp_path: Path) -> ToolRegistry:
        return ToolRegistry(
            work_dir=str(tmp_path),
            exec_provider=_NoopProvider(),  # type: ignore[arg-type]
        )

    async def test_receipt_reports_recorded_changes(self, tmp_path):
        reg = self._registry(tmp_path)
        out = await reg._record_exec_changes({}, [tmp_path], "bash", "done")
        assert "done" in out

    async def test_receipt_discloses_gaps(self, tmp_path, monkeypatch):
        """核心回归：扫描有缺口时，回执必须说出来。"""
        monkeypatch.setattr(registry_mod, "_EXEC_SNAPSHOT_MAX_FILES", 1)
        for i in range(5):
            (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")

        reg = self._registry(tmp_path)
        out = await reg._record_exec_changes({}, [tmp_path], "bash", "done")

        assert "未纳入版本跟踪" in out, f"回执未披露快照缺口：{out}"

    async def test_receipt_silent_when_no_gaps(self, tmp_path):
        """反向断言：没有缺口时不要乱加噪音提示。"""
        (tmp_path / "a.txt").write_text("a", encoding="utf-8")
        (tmp_path / "b.txt").write_text("b", encoding="utf-8")

        reg = self._registry(tmp_path)
        out = await reg._record_exec_changes({}, [tmp_path], "bash", "done")

        assert "未纳入版本跟踪" not in out

    async def test_receipt_discloses_gaps_even_when_nothing_changed(
        self, tmp_path, monkeypatch,
    ):
        """一个变更都没记录时更危险（用户会读成「没有变更」），仍须披露。"""
        monkeypatch.setattr(registry_mod, "_EXEC_SNAPSHOT_MAX_FILES", 1)
        for i in range(5):
            (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")

        reg = self._registry(tmp_path)
        # before 与 after 相同 → changed == 0
        before, _stats = _snapshot_exec_outputs([tmp_path], tmp_path)
        out = await reg._record_exec_changes(before, [tmp_path], "bash", "done")

        assert "已记录" not in out
        assert "未纳入版本跟踪" in out


# ---------------------------------------------------------------------------
# F-2：产物索引推模式（platform_store 为唯一权威源）
# ---------------------------------------------------------------------------


class _FakeArtifactStore:
    """替代 PlatformStore 的最小桩：只记录 upsert 调用。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    def upsert_artifact(self, session_id: str, path, *, workspace) -> bool:
        self.rows.append((session_id, Path(path).name))
        return True


class TestArtifactPushMode:
    """工具写成功即回填产物索引——此前是拉模式，没人调 manifest 就不记。"""

    def test_registry_defaults_do_not_push(self, tmp_path):
        """CLI / 单代理路径不注入 → 行为与现状一致（零改动）。"""
        reg = ToolRegistry(work_dir=str(tmp_path))
        assert reg.artifact_store is None
        assert reg.artifact_session == ""

    async def test_write_file_pushes_to_index(self, tmp_path):
        store = _FakeArtifactStore()
        reg = ToolRegistry(
            work_dir=str(tmp_path), artifact_store=store, artifact_session="s1",
        )
        out = await reg.execute("write_file", {"file_path": "a.txt", "content": "x"})
        assert not out.startswith("Error")
        assert ("s1", "a.txt") in store.rows

    async def test_edit_file_pushes_to_index(self, tmp_path):
        (tmp_path / "a.txt").write_text("old", encoding="utf-8")
        store = _FakeArtifactStore()
        reg = ToolRegistry(
            work_dir=str(tmp_path), artifact_store=store, artifact_session="s1",
        )
        out = await reg.execute(
            "edit_file",
            {"file_path": "a.txt", "old_string": "old", "new_string": "new"},
        )
        assert not out.startswith("Error")
        assert ("s1", "a.txt") in store.rows

    async def test_failed_write_does_not_push(self, tmp_path):
        """只有写成功才登记——失败的写入不能在索引里留下幻影条目。"""
        store = _FakeArtifactStore()
        reg = ToolRegistry(
            work_dir=str(tmp_path), artifact_store=store, artifact_session="s1",
        )
        await reg.execute("edit_file", {"file_path": "ghost.txt", "old_string": "x", "new_string": "y"})
        assert store.rows == []

    async def test_read_file_does_not_push(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        store = _FakeArtifactStore()
        reg = ToolRegistry(
            work_dir=str(tmp_path), artifact_store=store, artifact_session="s1",
        )
        await reg.execute("read_file", {"file_path": "a.txt"})
        assert store.rows == []

    async def test_bash_indirect_write_pushes(self, tmp_path, monkeypatch):
        """bash 的间接写入（脚本写文件）也要进索引——这正是"统一管理"的难点。"""
        (tmp_path / "make.py").write_text(
            "from pathlib import Path\nPath('made.txt').write_text('x')\n",
            encoding="utf-8",
        )
        store = _FakeArtifactStore()
        reg = ToolRegistry(
            work_dir=str(tmp_path), artifact_store=store, artifact_session="s1",
        )
        out = await reg.execute("bash", {"command": "python make.py"})
        assert not out.startswith("Error")
        assert ("s1", "made.txt") in store.rows

    async def test_index_failure_does_not_break_write(self, tmp_path):
        """红线：索引是旁路，抛错不能影响写入本身。"""
        class Exploding:
            def upsert_artifact(self, *args, **kwargs):
                raise RuntimeError("db gone")

        reg = ToolRegistry(
            work_dir=str(tmp_path), artifact_store=Exploding(), artifact_session="s1",
        )
        out = await reg.execute("write_file", {"file_path": "a.txt", "content": "x"})
        assert not out.startswith("Error"), "索引失败不应让写入报错"
        assert (tmp_path / "a.txt").exists()

    def test_upsert_artifact_uses_relative_posix_path(self, tmp_path):
        """真实 PlatformStore：path 必须以工作区为基准的 POSIX 相对路径落表，
        否则检索与前端树拼装会对不上。"""
        from research_assistant.runtime.platform_store import PlatformStore

        db = tmp_path / "p.sqlite3"
        store = PlatformStore(db)
        sub = tmp_path / "outputs" / "s1"
        sub.mkdir(parents=True)
        target = sub / "fig.png"
        target.write_bytes(b"\x89PNG")

        assert store.upsert_artifact("s1", target, workspace=tmp_path) is True
        with store._connect() as conn:  # noqa: SLF001 - 测试直读表
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM artifacts WHERE session_id='s1'",
            )]
        assert len(rows) == 1
        assert rows[0]["path"] == "outputs/s1/fig.png"
        assert rows[0]["ext"] == ".png"
        assert rows[0]["size"] == 4

    def test_upsert_outside_workspace_returns_false(self, tmp_path):
        from research_assistant.runtime.platform_store import PlatformStore

        store = PlatformStore(tmp_path / "p.sqlite3")
        outside = tmp_path.parent / "outside-push.txt"
        outside.write_text("x", encoding="utf-8")
        assert store.upsert_artifact("s1", outside, workspace=tmp_path) is False

    def test_upsert_is_idempotent_per_session_and_path(self, tmp_path):
        """同一 (session_id, path) 重复推应更新而不是堆重复行。"""
        from research_assistant.runtime.platform_store import PlatformStore

        store = PlatformStore(tmp_path / "p.sqlite3")
        target = tmp_path / "a.txt"
        target.write_text("x", encoding="utf-8")
        for _ in range(3):
            assert store.upsert_artifact("s1", target, workspace=tmp_path) is True
        with store._connect() as conn:  # noqa: SLF001 - 测试直读表
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM artifacts", ()).fetchone()["n"]
        assert count == 1


# ---------------------------------------------------------------------------
# 上限常量本身
# ---------------------------------------------------------------------------


class TestSnapshotLimits:
    def test_limits_are_positive(self):
        assert registry_mod._EXEC_SNAPSHOT_MAX_FILES > 0
        assert registry_mod._EXEC_SNAPSHOT_MAX_BYTES > 0

    def test_defaults_match_documented_values(self):
        """512 文件 / 32MB —— 文档与 UI 文案里可能出现这些数字。"""
        assert registry_mod._EXEC_SNAPSHOT_MAX_FILES == 512
        assert registry_mod._EXEC_SNAPSHOT_MAX_BYTES == 32 * 1024 * 1024


@pytest.mark.parametrize("missing_root", ["ghost-dir"])
async def test_missing_root_is_not_a_gap(tmp_path, missing_root):
    """不存在的根目录是常态（首次执行前产物目录还没建），不算缺口。"""
    _snap, stats = _snapshot_exec_outputs([tmp_path / missing_root], tmp_path)
    assert stats.has_gaps is False
    assert stats.files_captured == 0


# ---------------------------------------------------------------------------
# F-3：record_tree —— subprocess 写入路径的版本化收口
# ---------------------------------------------------------------------------


class TestRecordTree:
    """复现分析脚本经 subprocess 写文件，完全绕开 ToolRegistry，产物此前
    零版本覆盖。record_tree 是显式 opt-in 的收口（不能用 atomic_write_text
    全局钩子——版本存储自己就用它写 index.json，会无限递归）。"""

    def test_records_new_files(self, tmp_path):
        from research_assistant.artifacts import ArtifactVersionStore

        out = tmp_path / "writing_outputs" / "analysis-runs" / "r1"
        out.mkdir(parents=True)
        (out / "result.csv").write_text("a,b\n1,2", encoding="utf-8")
        (out / "fig.png").write_bytes(b"\x89PNG")

        scan = ArtifactVersionStore(tmp_path).record_tree(out, tool="analysis:r1")

        assert scan["recorded"] == 2
        assert scan["skipped_oversized"] == 0
        assert scan["truncated"] is False

    def test_recorded_files_are_restorable(self, tmp_path):
        """登记之后要真的能恢复——这是这次补齐的意义所在。"""
        from research_assistant.artifacts import ArtifactVersionStore

        out = tmp_path / "out"
        out.mkdir()
        target = out / "data.txt"
        target.write_text("v1", encoding="utf-8")

        store = ArtifactVersionStore(tmp_path)
        store.record_tree(out, tool="analysis:r1")

        assert target.exists()
        target.unlink()
        restored = store.list(limit=1)[0]
        store.restore(restored["id"], "after")
        assert target.read_text(encoding="utf-8") == "v1"

    def test_excludes_ra_and_exec_scripts(self, tmp_path):
        from research_assistant.artifacts import ArtifactVersionStore

        out = tmp_path / "out"
        out.mkdir()
        (out / ".ra").mkdir()
        (out / ".ra" / "x.json").write_text("{}", encoding="utf-8")
        (out / "_ra_tmp.py").write_text("code", encoding="utf-8")
        (out / "real.txt").write_text("real", encoding="utf-8")

        scan = ArtifactVersionStore(tmp_path).record_tree(out, tool="analysis:r1")

        assert scan["recorded"] == 1
        paths = {r["path"] for r in ArtifactVersionStore(tmp_path).list()}
        assert "out/real.txt" in paths

    def test_oversized_and_cap_are_counted(self, tmp_path):
        from research_assistant.artifacts import ArtifactVersionStore

        out = tmp_path / "out"
        out.mkdir()
        (out / "big.bin").write_bytes(b"x" * 100)
        for i in range(5):
            (out / f"f{i}.txt").write_text("x", encoding="utf-8")

        scan = ArtifactVersionStore(tmp_path).record_tree(
            out, tool="analysis:r1", max_files=3, max_bytes=50,
        )

        assert scan["skipped_oversized"] == 1
        assert scan["truncated"] is True

    def test_rerun_with_unchanged_output_does_not_duplicate(self, tmp_path):
        """复现脚本重跑且输出未变时，不得为同一文件堆一串相同记录。"""
        from research_assistant.artifacts import ArtifactVersionStore

        out = tmp_path / "out"
        out.mkdir()
        (out / "r.csv").write_text("1,2", encoding="utf-8")

        store = ArtifactVersionStore(tmp_path)
        first = store.record_tree(out, tool="analysis:r1")
        second = store.record_tree(out, tool="analysis:r1")

        assert first["recorded"] == 1
        assert second["recorded"] == 0, "重跑产生重复记录"
        assert len(store.list(limit=100)) == 1

    def test_rerun_with_changed_output_records_again(self, tmp_path):
        """输出真的变了则要重新登记（不能被幂等检查误伤）。"""
        from research_assistant.artifacts import ArtifactVersionStore

        out = tmp_path / "out"
        out.mkdir()
        path = out / "r.csv"
        path.write_text("1,2", encoding="utf-8")

        store = ArtifactVersionStore(tmp_path)
        store.record_tree(out, tool="analysis:r1")
        path.write_text("3,4", encoding="utf-8")
        second = store.record_tree(out, tool="analysis:r1")

        assert second["recorded"] == 1

    def test_missing_directory_is_noop(self, tmp_path):
        from research_assistant.artifacts import ArtifactVersionStore

        scan = ArtifactVersionStore(tmp_path).record_tree(
            tmp_path / "no-such-dir", tool="analysis:r1",
        )
        assert scan == {"recorded": 0, "skipped_oversized": 0, "truncated": False}

    def test_outside_workspace_directory_is_refused(self, tmp_path):
        """目录解析逃出工作区时必须拒绝，不得把别处文件登记进来。"""
        import pytest as _pytest

        from research_assistant.artifacts import ArtifactVersionStore
        from research_assistant.core import safe_resolve

        outside = tmp_path.parent / "outside-tree"
        outside.mkdir(exist_ok=True)
        (outside / "x.txt").write_text("y", encoding="utf-8")

        with _pytest.raises(ValueError):
            safe_resolve(outside, tmp_path)
        # record_tree 内部同样应抛出，而不是静默登记
        with _pytest.raises(ValueError):
            ArtifactVersionStore(tmp_path).record_tree(outside, tool="analysis:r1")
