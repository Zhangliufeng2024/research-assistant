"""Recoverable file changes produced by agent file tools."""

from __future__ import annotations

import difflib
import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from ..core import atomic_write_text, safe_resolve


def _sha(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


class SnapshotMissingError(RuntimeError):
    """版本快照缺失：索引声称这一侧有快照，但对应的 .bin 已不在磁盘上。

    这必须与「该侧当时本来就没有文件」严格区分：

    * ``before_exists=False`` 表示变更发生时文件还不存在（新建动作）——
      恢复 before 侧 = 删掉这个文件，这是**正确**语义；
    * 索引说 ``exists=True`` 但 .bin 没了，说明快照是被 Janitor 淘汰或
      手工清理掉的——此时若沿用「读不到就删」的旧逻辑，恢复按钮会把用户
      当前的真实文件删掉，**恢复变成销毁**。这种情况必须拒绝并报错。

    调用方（REST 层）应把它映射为 409 + 明确文案，而不是当作成功。
    """

    def __init__(self, change_id: str, side: str) -> None:
        self.change_id = change_id
        self.side = side
        super().__init__(
            f"变更 {change_id} 的 {side} 快照已不存在（可能已被清理），无法恢复"
        )


class ArtifactVersionStore:
    """Append-only changeset store scoped to one project workspace."""

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace).resolve()
        self.root = self.workspace / ".ra" / "changes"
        self.index_path = self.root / "index.json"

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, records: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self.index_path, json.dumps(records, ensure_ascii=False, indent=2),
        )

    def record(
        self, path: str | Path, before: bytes | None, after: bytes | None, *, tool: str,
    ) -> dict[str, Any] | None:
        target = safe_resolve(Path(path), self.workspace)
        if before == after:
            return None
        change_id = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        rel = target.relative_to(self.workspace).as_posix()
        change_dir = self.root / change_id
        change_dir.mkdir(parents=True, exist_ok=True)
        if before is not None:
            (change_dir / "before.bin").write_bytes(before)
        if after is not None:
            (change_dir / "after.bin").write_bytes(after)
        record = {
            "id": change_id, "path": rel, "tool": tool, "created_at": time.time(),
            "before_sha256": _sha(before), "after_sha256": _sha(after),
            "before_exists": before is not None, "after_exists": after is not None,
            "size_before": len(before) if before is not None else 0,
            "size_after": len(after) if after is not None else 0,
            "status": "applied",
        }
        records = self._load()
        records.append(record)
        self._save(records)
        return record

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        return list(reversed(self._load()))[:max(1, min(limit, 1000))]

    def get(self, change_id: str) -> dict[str, Any] | None:
        return next((r for r in self._load() if r.get("id") == change_id), None)

    def _snapshot(self, change_id: str, side: str) -> bytes | None:
        if side not in {"before", "after"}:
            raise ValueError("side must be before or after")
        path = self.root / change_id / f"{side}.bin"
        return path.read_bytes() if path.exists() else None

    def snapshot_available(self, change_id: str, side: str) -> bool:
        """这一侧的快照当前是否可取（供 UI 决定是否禁用「恢复」按钮）。"""
        if side not in {"before", "after"}:
            raise ValueError("side must be before or after")
        return (self.root / change_id / f"{side}.bin").exists()

    def discard_snapshot(self, change_id: str, side: str) -> bool:
        """丢弃一侧快照，并**同步**在索引里标记 ``<side>_evicted``。

        两件事必须同做：只删 .bin 而不改索引，会留下"索引说有、磁盘没有"
        的悬空记录——UI 上依然可点「恢复」，而恢复时读不到快照。这正是
        F-1 数据丢失的成因。Janitor 的容量淘汰必须走这里，不要直接 unlink。

        ⚠️ 这里**不改** ``<side>_exists``：那是"变更发生时该侧是否存在"的
        历史事实（False = 当时文件还不存在，恢复它=删除，是正确语义）。
        若把「已被清理」也写成 False，两种含义就会混淆，restore 又会退化成
        删除用户文件。可用性用独立的 ``<side>_evicted`` 表示。

        Returns:
            是否真的丢弃了一份快照（记录不存在或该侧本就无快照时返回 False）。
        """
        if side not in {"before", "after"}:
            raise ValueError("side must be before or after")

        records = self._load()
        for rec in records:
            if rec.get("id") != change_id:
                continue
            bin_path = self.root / change_id / f"{side}.bin"
            existed = bin_path.exists()
            if existed:
                bin_path.unlink()
            if not rec.get(f"{side}_evicted"):
                rec[f"{side}_evicted"] = True
                self._save(records)
            return existed
        return False

    def snapshot_restorable(self, change_id: str, side: str) -> bool:
        """该侧现在是否可以安全恢复（供 UI 决定是否禁用「恢复」按钮）。

        = 历史上存在过这一侧 **且** 快照没有被清理掉。
        """
        record = self.get(change_id)
        if record is None:
            return False
        if not bool(record.get(f"{side}_exists")):
            # 当时就没有这一侧：恢复它意味着删除文件——这是合法操作，
            # 但语义上叫「撤销新建」而不是「恢复快照」，UI 应区别呈现。
            return False
        return not bool(record.get(f"{side}_evicted"))

    def reconcile_snapshots(self) -> int:
        """修复存量悬空记录：把 .bin 已丢失的记录标记为已清理。

        F-1 修复**之前**，Janitor 淘汰 .bin 时没有同步改索引，因此已存在的
        工作区里可能已经留下了一批"点了恢复就会删文件"的记录。本方法把它们
        显性化，使 UI 能禁用、restore 能报明确错误而不是删文件。

        Returns:
            被修正的记录条数。幂等，可重复调用。
        """
        records = self._load()
        fixed = 0
        for rec in records:
            changed = False
            for side in ("before", "after"):
                if rec.get(f"{side}_evicted"):
                    continue
                if not (self.root / str(rec.get("id")) / f"{side}.bin").exists():
                    rec[f"{side}_evicted"] = True
                    changed = True
            if changed:
                fixed += 1
        if fixed:
            self._save(records)
        return fixed

    def record_tree(
        self,
        directory: str | Path,
        *,
        tool: str,
        max_files: int = 512,
        max_bytes: int = 32 * 1024 * 1024,
    ) -> dict[str, Any]:
        """把 *directory* 下现有文件作为「新增」记录进版本历史。

        A+ 阶段 2 / F-3：``subprocess`` 写入路径（如复现分析脚本）完全绕开
        ToolRegistry，此前产物**零版本覆盖**——它们只出现在 analysis_runs 的
        outputs_json 里，出错后既无法 diff 也无法恢复。

        为什么做成**显式 opt-in** 而不是把钩子下沉到 ``atomic_write_text``：
        版本存储自身就用 ``atomic_write_text`` 写 ``index.json``，全局挂钩会
        造成「写索引 → 记录变更 → 又写索引」的无限递归，且会把 run.json、
        events.jsonl 等内部状态文件也卷进版本历史。

        Args:
            directory: 要登记的目录（须位于工作区内，经 ``safe_resolve`` 校验）。
            tool: 变更记录的 tool 标签（如 ``"analysis:<run_id>"``）。
            max_files / max_bytes: 扫描上限，语义与 ``registry`` 的执行快照一致。

        Returns:
            ``{"recorded": int, "skipped_oversized": int, "truncated": bool}``。
            调用方应把缺口如实上报（不要静默吞掉）。
        """
        directory = safe_resolve(Path(directory), self.workspace)
        if not directory.is_dir():
            return {"recorded": 0, "skipped_oversized": 0, "truncated": False}

        # 幂等：内容与该路径最后一次登记的结果一致就跳过。
        # 复现脚本重跑（同一 run_id、输出未变）时若不去重，会为同一文件
        # 堆出一串完全相同的「新增」记录，把变更页刷成噪音。
        last_hash: dict[str, str | None] = {}
        for rec in self._load():
            last_hash.setdefault(str(rec.get("path")), rec.get("after_sha256"))

        stats: dict[str, Any] = {
            "recorded": 0, "skipped_oversized": 0, "truncated": False,
        }
        total = 0
        count = 0
        # 工程债：惰性遍历替代 sorted(rglob) 全量物化——巨型目录下不再
        # 一次性构造全部 Path；max_files 截断兜底，枚举顺序变化不影响集合。
        try:
            for path in directory.rglob("*"):
                if count >= max_files:
                    stats["truncated"] = True
                    break
                if not path.is_file():
                    continue
                # 排除版本存储自身的目录与执行中间脚本，避免自我索引/噪音
                if ".ra" in path.parts or path.name.startswith("_ra_"):
                    continue
                try:
                    resolved = safe_resolve(path, self.workspace)
                    size = resolved.stat().st_size
                    if size > max_bytes or total + size > max_bytes:
                        stats["skipped_oversized"] += 1
                        continue
                    data = resolved.read_bytes()
                except (OSError, ValueError):
                    continue
                rel = resolved.relative_to(self.workspace).as_posix()
                if _sha(data) == last_hash.get(rel):
                    continue        # 内容未变，不重复登记
                try:
                    if self.record(resolved, None, data, tool=tool) is not None:
                        stats["recorded"] += 1
                        count += 1
                        total += size
                        last_hash[rel] = _sha(data)
                except (OSError, ValueError):
                    continue
        except OSError:
            return stats
        return stats

    def diff(self, change_id: str) -> dict[str, Any]:
        record = self.get(change_id)
        if record is None:
            raise KeyError(change_id)
        before = self._snapshot(change_id, "before")
        after = self._snapshot(change_id, "after")
        try:
            before_text = (before or b"").decode("utf-8")
            after_text = (after or b"").decode("utf-8")
        except UnicodeDecodeError:
            return {**record, "binary": True, "diff": ""}
        lines = difflib.unified_diff(
            before_text.splitlines(), after_text.splitlines(),
            fromfile=f"a/{record['path']}", tofile=f"b/{record['path']}", lineterm="",
        )
        return {
            **record,
            "binary": False,
            "diff": "\n".join(lines),
            # 供 UI 提示「快照已被清理」——不加这两个键时旧前端行为不变。
            "before_available": self.snapshot_available(change_id, "before"),
            "after_available": self.snapshot_available(change_id, "after"),
        }

    def restore(self, change_id: str, side: str = "before") -> dict[str, Any]:
        """把文件恢复到 *side* 指定的一侧。

        Raises:
            KeyError: 变更记录不存在。
            ValueError: side 不是 before/after。
            SnapshotMissingError: 索引声称有快照但 .bin 已被清理——
                此时**绝不**删除目标文件（否则恢复即销毁，见 F-1）。
        """
        record = self.get(change_id)
        if record is None:
            raise KeyError(change_id)
        if side not in {"before", "after"}:
            raise ValueError("side must be before or after")

        target = safe_resolve(self.workspace / record["path"], self.workspace)
        data = self._snapshot(change_id, side)

        # 关键判定（F-1）：读不到快照有两种截然不同的含义，不能一律当删除。
        #
        #   * ``<side>_evicted`` 为真 → 快照曾经存在、后来被清理掉了。
        #     此时删文件等于销毁用户当前数据，**必须拒绝**。
        #   * 否则 → 这一侧历史上就不存在（新建动作的 before、删除动作的
        #     after），删掉文件才是正确语义。
        if data is None and bool(record.get(f"{side}_evicted")):
            raise SnapshotMissingError(change_id, side)

        current = target.read_bytes() if target.is_file() else None
        if data is None:
            # 该侧当时就不存在（新建动作的 before / 删除动作的 after）→
            # 删除是**正确**语义：撤销新建、或还原一次删除。
            if target.exists():
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        restored = target.read_bytes() if target.is_file() else None
        rollback = self.record(target, current, restored, tool=f"restore:{change_id}:{side}")
        return rollback or record
