"""R17 Janitor：工作区分层生命周期清理。

设计红线（与 docs/plans/2026-08-28-refactor-plan-detailed.md §3.4 一致）：
- 热层（近 ``warm_days`` 内有活动的会话）零触碰；
- 一切删除/压缩先写审计日志 ``.ra/janitor_audit.jsonl``（JSONL 逐条追加）；
- 只动数据文件，绝不动 ``run.json``/``history.json`` 等状态权威文件；
- 所有阈值走 ``RA_JANITOR_*`` 环境变量，默认保守。

分层策略：
- 温层：``warm_days``（默认 30）未动的会话 → session_meta 标记 archived
  （列表折叠，文件不动）；
- 冷层：``cold_days``（默认 90）未动且已归档 → events.jsonl gzip 压缩、
  产物 drafts/ 子目录删除（artifacts/ 保留）；
- 快照：.ra/changes/ 总量超 ``changes_cap_mb``（默认 500MB）→ 按 mtime
  LRU 淘汰最旧文件；
- 日志：单会话 events.jsonl 超 ``events_rotate_mb``（默认 10MB）→ 轮转
  .1/.2/.3 三代，最旧丢弃；
- 临时：tmp/ 下 ``tmp_days``（默认 7）前的条目删除。
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG = logging.getLogger("ra.runtime.janitor")

AUDIT_FILE = "janitor_audit.jsonl"


@dataclass(frozen=True)
class JanitorConfig:
    warm_days: float = 30.0
    cold_days: float = 90.0
    changes_cap_mb: float = 500.0
    events_rotate_mb: float = 10.0
    events_keep: int = 3
    tmp_days: float = 7.0

    @classmethod
    def from_env(cls) -> JanitorConfig:
        def _f(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, "") or default)
            except ValueError:
                return default

        return cls(
            warm_days=_f("RA_JANITOR_WARM_DAYS", 30.0),
            cold_days=_f("RA_JANITOR_COLD_DAYS", 90.0),
            changes_cap_mb=_f("RA_JANITOR_CHANGES_CAP_MB", 500.0),
            events_rotate_mb=_f("RA_JANITOR_EVENTS_ROTATE_MB", 10.0),
            events_keep=int(_f("RA_JANITOR_EVENTS_KEEP", 3)),
            tmp_days=_f("RA_JANITOR_TMP_DAYS", 7.0),
        )


def _audit(cwd: Path, action: str, path: Path, reason: str) -> None:
    """审计先行：任何动作落盘前写日志。日志写失败则放弃动作（fail-safe）。"""
    audit_dir = cwd / ".ra"
    audit_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": time.time(),
        "action": action,
        "path": str(path.relative_to(cwd)) if path.is_relative_to(cwd) else str(path),
        "reason": reason,
    }
    with (audit_dir / AUDIT_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _session_age_days(run_dir: Path) -> float:
    state_file = run_dir / "run.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        updated = float(state.get("updated_at") or 0)
    except (OSError, json.JSONDecodeError, ValueError):
        updated = 0.0
    if not updated:
        try:
            updated = run_dir.stat().st_mtime
        except OSError:
            return 0.0  # 读不到时间按热层处理：不碰
    return (time.time() - updated) / 86400.0


def _sweep_warm(cwd: Path, store: Any, cfg: JanitorConfig, stats: dict) -> None:
    """温层：超龄未动会话标记 archived（不动文件）。"""
    sessions_root = cwd / ".ra" / "sessions"
    if not sessions_root.is_dir() or store is None:
        return
    for child in sessions_root.iterdir():
        try:
            if not child.is_dir() or child.name.startswith("."):
                continue
            age = _session_age_days(child)
            if age < cfg.warm_days:
                continue  # 热层红线
            flags = store.get_session_flags_map([child.name]).get(child.name) or {}
            if flags.get("archived"):
                continue
            _audit(cwd, "archive", child, f"inactive {age:.0f}d >= warm {cfg.warm_days:.0f}d")
            store.set_session_flags(child.name, archived=True)
            stats["archived"] += 1
        except OSError:
            continue


def _outputs_dirs_for(cwd: Path, session_id: str) -> list[Path]:
    """会话产物目录的可能位置（迁移期新旧并存）。"""
    return [
        cwd / ".ra" / "outputs" / session_id,
        cwd / "outputs" / session_id,
        cwd / "writing_outputs" / session_id,
    ]


def _sweep_cold(cwd: Path, store: Any, cfg: JanitorConfig, stats: dict) -> None:
    """冷层：超龄且已归档 → events.jsonl gzip、产物 drafts/ 删除。"""
    sessions_root = cwd / ".ra" / "sessions"
    if not sessions_root.is_dir():
        return
    for child in sessions_root.iterdir():
        try:
            if not child.is_dir() or child.name.startswith("."):
                continue
            age = _session_age_days(child)
            if age < cfg.cold_days:
                continue
            if store is not None:
                flags = store.get_session_flags_map([child.name]).get(child.name) or {}
                if not flags.get("archived"):
                    continue  # 冷层只处理已归档的
            events = child / "events.jsonl"
            if events.is_file():
                _audit(cwd, "gzip", events, f"cold {age:.0f}d")
                gz_path = child / "events.jsonl.gz"
                with events.open("rb") as src, gzip.open(gz_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                events.unlink()
                stats["gzipped"] += 1
            for out_dir in _outputs_dirs_for(cwd, child.name):
                drafts = out_dir / "drafts"
                if drafts.is_dir():
                    _audit(cwd, "delete_drafts", drafts, f"cold {age:.0f}d")
                    shutil.rmtree(drafts, ignore_errors=True)
                    stats["drafts_removed"] += 1
        except OSError:
            continue


def _sweep_changes(cwd: Path, cfg: JanitorConfig, stats: dict) -> None:
    """.ra/changes/ 总量 LRU：超 cap 按 mtime 从旧到新淘汰。"""
    changes = cwd / ".ra" / "changes"
    if not changes.is_dir():
        return
    files: list[tuple[float, int, Path]] = []
    try:
        for p in changes.rglob("*"):
            if p.is_file():
                try:
                    st = p.stat()
                    files.append((st.st_mtime, st.st_size, p))
                except OSError:
                    continue
    except OSError:
        return
    total = sum(size for _, size, _ in files)
    cap = cfg.changes_cap_mb * 1024 * 1024
    if total <= cap:
        return
    files.sort()  # mtime 升序：最旧的先淘汰
    for _mtime, size, path in files:
        if total <= cap:
            break
        try:
            _audit(cwd, "evict_change", path, f"changes {total / 1048576:.0f}MB > cap {cfg.changes_cap_mb:.0f}MB")
            path.unlink()
            total -= size
            stats["changes_evicted"] += 1
        except OSError:
            continue


def _rotate_events(cwd: Path, cfg: JanitorConfig, stats: dict) -> None:
    """单会话 events.jsonl 超阈值轮转 N 代（.1 最新）。"""
    sessions_root = cwd / ".ra" / "sessions"
    if not sessions_root.is_dir():
        return
    limit = cfg.events_rotate_mb * 1024 * 1024
    for child in sessions_root.iterdir():
        events = child / "events.jsonl"
        try:
            if not events.is_file() or events.stat().st_size <= limit:
                continue
            _audit(cwd, "rotate", events, f"{events.stat().st_size / 1048576:.0f}MB > {cfg.events_rotate_mb:.0f}MB")
            oldest = child / f"events.jsonl.{cfg.events_keep}"
            oldest.unlink(missing_ok=True)
            for i in range(cfg.events_keep - 1, 0, -1):
                src = child / f"events.jsonl.{i}"
                if src.exists():
                    src.rename(child / f"events.jsonl.{i + 1}")
            events.rename(child / "events.jsonl.1")
            stats["rotated"] += 1
        except OSError:
            continue


def _sweep_tmp(cwd: Path, cfg: JanitorConfig, stats: dict) -> None:
    """tmp/ 超龄条目删除。"""
    tmp = cwd / "tmp"
    if not tmp.is_dir():
        return
    cutoff = time.time() - cfg.tmp_days * 86400.0
    for entry in tmp.iterdir():
        try:
            if entry.stat().st_mtime > cutoff:
                continue
            _audit(cwd, "delete_tmp", entry, f"tmp older than {cfg.tmp_days:.0f}d")
            if entry.is_dir():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
            stats["tmp_removed"] += 1
        except OSError:
            continue


def run_janitor(cwd: Path, store: Any = None, config: JanitorConfig | None = None) -> dict[str, int]:
    """执行一轮分层清理，返回动作计数。异常逐层隔离：单层失败不影响他层。"""
    cfg = config or JanitorConfig.from_env()
    cwd = Path(cwd)
    stats: dict[str, int] = {
        "archived": 0, "gzipped": 0, "drafts_removed": 0,
        "changes_evicted": 0, "rotated": 0, "tmp_removed": 0,
    }
    # 顺序即安全语义：cold 先于 warm——冷层只处理「上一轮就已归档」的会话，
    # 温层本轮新归档的要等下一轮才可能被压缩/清稿（先观察、后销毁）。
    for name, fn in (
        ("cold", _sweep_cold), ("warm", _sweep_warm),
        ("changes", _sweep_changes), ("rotate", _rotate_events),
        ("tmp", _sweep_tmp),
    ):
        try:
            fn(cwd, store, cfg, stats) if name in {"warm", "cold"} else fn(cwd, cfg, stats)
        except Exception:  # noqa: BLE001 —— 看门狗不许把调度器带崩
            LOG.exception("janitor 层 %s 失败（已跳过）", name)
    if any(stats.values()):
        LOG.info("janitor: %s", stats)
    return stats
