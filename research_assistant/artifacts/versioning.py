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
        return {**record, "binary": False, "diff": "\n".join(lines)}

    def restore(self, change_id: str, side: str = "before") -> dict[str, Any]:
        record = self.get(change_id)
        if record is None:
            raise KeyError(change_id)
        target = safe_resolve(self.workspace / record["path"], self.workspace)
        data = self._snapshot(change_id, side)
        current = target.read_bytes() if target.is_file() else None
        if data is None:
            if target.exists():
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        restored = target.read_bytes() if target.is_file() else None
        rollback = self.record(target, current, restored, tool=f"restore:{change_id}:{side}")
        return rollback or record
