"""ArtifactStore — content-addressed stage outputs enabling resume.

Every pipeline stage writes its outputs through the store, which records
sha256 hashes in ``manifest.json``. On resume, a stage whose artifacts all
exist with unchanged hashes is skipped entirely.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..core import atomic_write_text


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class ArtifactEntry:
    key: str
    path: str
    sha256: str
    stage: str
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "key": self.key, "path": self.path, "sha256": self.sha256,
            "stage": self.stage, "created_at": self.created_at,
        }


class ArtifactStore:
    """Tracks stage outputs under ``<output_dir>/.ra/artifacts``."""

    MANIFEST = "manifest.json"

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self._dir = self.output_dir / ".ra" / "artifacts"
        self._manifest_path = self._dir / self.MANIFEST
        self._entries: dict[str, ArtifactEntry] = {}
        self._load()

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if not self._manifest_path.exists():
            return
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            for e in data.get("artifacts", []):
                self._entries[e["key"]] = ArtifactEntry(**e)
        except (json.JSONDecodeError, KeyError, OSError, TypeError):
            self._entries = {}

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        atomic_write_text(
            self._manifest_path,
            json.dumps({"artifacts": [e.to_dict() for e in self._entries.values()]},
                       indent=2, ensure_ascii=False),
        )

    # -- operations ----------------------------------------------------------

    def register(self, key: str, path: str | Path, stage: str) -> ArtifactEntry:
        """Register an existing file as the artifact for *key*."""
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"cannot register missing artifact: {p}")
        entry = ArtifactEntry(key=key, path=str(p), sha256=sha256_of(p), stage=stage)
        self._entries[key] = entry
        self._save()
        return entry

    def get(self, key: str) -> ArtifactEntry | None:
        return self._entries.get(key)

    def is_valid(self, key: str) -> bool:
        """True when the artifact exists and its content hash is unchanged."""
        entry = self._entries.get(key)
        if entry is None:
            return False
        p = Path(entry.path)
        if not p.exists():
            return False
        try:
            return sha256_of(p) == entry.sha256
        except OSError:
            return False

    def all_valid(self, *keys: str) -> bool:
        return all(self.is_valid(k) for k in keys)

    def entries_for_stage(self, stage: str) -> list[ArtifactEntry]:
        return [e for e in self._entries.values() if e.stage == stage]
