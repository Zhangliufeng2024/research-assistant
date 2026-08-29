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

from ..artifacts.versioning import ArtifactVersionStore

LOG = logging.getLogger("ra.runtime.janitor")

AUDIT_FILE = "janitor_audit.jsonl"

#: 一天的秒数（与 tmp_days 等既有用 86400.0 内联的口径一致，这里提出来
#: 是因为 _sweep_tool_outputs / _rotate_audit 也需要）。生产代码不在仓库
#: 全局共享常量，避免把"时间单位"这种小事提升为跨模块依赖。
DAY_SECONDS = 86400.0


@dataclass(frozen=True)
class JanitorConfig:
    warm_days: float = 30.0
    cold_days: float = 90.0
    changes_cap_mb: float = 500.0
    events_rotate_mb: float = 10.0
    events_keep: int = 3
    tmp_days: float = 7.0
    #: A+ 阶段 2 / F-6：上下文外置产物（.ra/tool_outputs/）的保留天数。
    #: agent.py 把超大工具结果落盘到这里，只在历史里留指针，从不清理——
    #: 长跑项目里这个目录会单调增长。
    tool_outputs_days: float = 7.0
    #: 审计日志自身的大小上限（MB）与保留代数。此前只 append 不轮转。
    audit_rotate_mb: float = 5.0
    audit_keep: int = 3

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
            tool_outputs_days=_f("RA_JANITOR_TOOL_OUTPUTS_DAYS", 7.0),
            audit_rotate_mb=_f("RA_JANITOR_AUDIT_ROTATE_MB", 5.0),
            audit_keep=int(_f("RA_JANITOR_AUDIT_KEEP", 3)),
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
    """.ra/changes/ 总量 LRU：超 cap 按 mtime 从旧到新淘汰快照 .bin。

    A+ 阶段 1 / F-1：淘汰必须经 ``ArtifactVersionStore.discard_snapshot()``——
    它删 .bin 的同时会在索引里置 ``<side>_evicted``，两者是一个动作。

    修复前这里直接 ``path.unlink()``：bin 没了但 index.json 里的记录仍在，
    于是变更页照常显示这条记录、「恢复」按钮照常可点，而 restore() 读不到
    快照就走「删除目标文件」的分支——**恢复按钮变成销毁按钮**。

    另外这里只扫 ``*.bin``，绝不碰 index.json：旧实现的 ``rglob("*")``
    在极端 mtime 排序下理论上会把索引本身也当成最旧文件删掉。
    """
    changes = cwd / ".ra" / "changes"
    if not changes.is_dir():
        return
    bins: list[tuple[float, int, Path]] = []
    try:
        for p in changes.rglob("*.bin"):
            if p.is_file():
                try:
                    st = p.stat()
                    bins.append((st.st_mtime, st.st_size, p))
                except OSError:
                    continue
    except OSError:
        return
    total = sum(size for _, size, _ in bins)
    cap = cfg.changes_cap_mb * 1024 * 1024
    if total <= cap:
        return
    bins.sort()  # mtime 升序：最旧的先淘汰

    store = ArtifactVersionStore(cwd)
    for _mtime, size, path in bins:
        if total <= cap:
            break
        change_id = path.parent.name
        side = path.stem
        if side not in {"before", "after"}:
            continue
        try:
            _audit(
                cwd, "evict_change", path,
                f"changes {total / 1048576:.0f}MB > cap {cfg.changes_cap_mb:.0f}MB",
            )
            if store.discard_snapshot(change_id, side):
                total -= size
                stats["changes_evicted"] += 1
        except OSError:
            continue


def _sweep_tool_outputs(cwd: Path, cfg: JanitorConfig, stats: dict) -> None:
    """A+ 阶段 2 / F-6：清理过期的上下文外置产物。

    agent.py 把超过阈值的工具结果落到 ``.ra/tool_outputs/``，只在会话历史里
    留一个指针。但**从来没有任何清理路径**——指针会随会话压缩/删除而消失，
    文件却永久留在工作区里，长期项目上单调增长。

    保留 ``tool_outputs_days``（默认 7）天：外置产物是"可重得的中间态"，
    真正需要长期留存的产物会经 write_file 进入产物目录并纳入版本跟踪，
    与这里不是同一回事。
    """
    root = cwd / ".ra" / "tool_outputs"
    if not root.is_dir():
        return
    cutoff = time.time() - cfg.tool_outputs_days * DAY_SECONDS
    try:
        for path in list(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            try:
                _audit(cwd, "delete_tool_output", path, f"older than {cfg.tool_outputs_days}d")
                path.unlink()
                stats["tool_outputs_removed"] += 1
            except OSError:
                continue
    except OSError:
        return


def _rotate_audit(cwd: Path, cfg: JanitorConfig, stats: dict) -> None:
    """A+ 阶段 2 / F-6：审计日志自身轮转。

    ``_audit`` 是"删除前先留证"的 fail-safe 机制，它自己却**只增不减**——
    一个跑了半年的工作区，审计日志会无限膨胀，反而拖慢每一次删除动作
    （每次都要 append 到一个越来越大的文件上）。

    轮转放**在其它清理层之后**执行（见 run_janitor 的顺序）：本轮产生的
    审计记录先完整落盘，再滚动，绝不丢失"刚刚删了什么"的证据。
    """
    audit_path = cwd / ".ra" / AUDIT_FILE
    if not audit_path.is_file():
        return
    cap = cfg.audit_rotate_mb * 1024 * 1024
    try:
        if audit_path.stat().st_size < cap:
            return
    except OSError:
        return

    try:
        # 依次把 .N 推到 .N+1，最旧的一代丢弃
        for gen in range(cfg.audit_keep, 0, -1):
            src = audit_path.with_name(f"{AUDIT_FILE}.{gen}")
            if not src.exists():
                continue
            if gen >= cfg.audit_keep:
                src.unlink()
                continue
            src.rename(audit_path.with_name(f"{AUDIT_FILE}.{gen + 1}"))
        audit_path.rename(audit_path.with_name(f"{AUDIT_FILE}.1"))
        stats["audit_rotated"] += 1
    except OSError:
        LOG.warning("审计日志轮转失败（不影响清理）", exc_info=True)


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
        "tool_outputs_removed": 0, "audit_rotated": 0,
    }
    # 顺序即安全语义：cold 先于 warm——冷层只处理「上一轮就已归档」的会话，
    # 温层本轮新归档的要等下一轮才可能被压缩/清稿（先观察、后销毁）。
    # tool_outputs 与 audit 放最后：前者是最"可丢"的层；后者必须等其他层
    # 的审计记录都写完再滚动，否则会丢「刚刚删了什么」的证据。
    for name, fn in (
        ("cold", _sweep_cold), ("warm", _sweep_warm),
        ("changes", _sweep_changes), ("rotate", _rotate_events),
        ("tmp", _sweep_tmp),
        ("tool_outputs", _sweep_tool_outputs),
        ("audit", _rotate_audit),
    ):
        try:
            fn(cwd, store, cfg, stats) if name in {"warm", "cold"} else fn(cwd, cfg, stats)
        except Exception:  # noqa: BLE001 —— 看门狗不许把调度器带崩
            LOG.exception("janitor 层 %s 失败（已跳过）", name)
    if any(stats.values()):
        LOG.info("janitor: %s", stats)
    return stats
