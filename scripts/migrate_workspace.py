"""工作区迁移脚本（R17 重构配套）。

用途：对存量工作区执行结构性迁移（如 writing_outputs/ → .ra/outputs/）。
安全模型：
- 默认 dry-run：只打印将执行的动作，不碰任何文件；``--apply`` 才真实执行。
- 执行前把受影响目录树复制到 ``.ra/migration_backup/<timestamp>/``。
- 迁移前检测运行中任务（platform.sqlite3 里 running 状态的 run），有则拒绝。

用法：
    python scripts/migrate_workspace.py <workspace> [--apply] [--step outputs]
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BACKUP_ROOT = ".ra/migration_backup"


def _running_runs(workspace: Path) -> int:
    """返回 platform.sqlite3 中 running 状态的任务数（无库则 0）。"""
    db = workspace / ".ra" / "platform.sqlite3"
    if not db.exists():
        return 0
    try:
        conn = sqlite3.connect(str(db))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE status IN ('running','queued')"
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except sqlite3.Error:
        # 库打不开时按有运行处理：宁可拒绝，不可误迁
        return -1


def _backup(workspace: Path, targets: list[Path], apply: bool) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = workspace / BACKUP_ROOT / stamp
    for t in targets:
        if not t.exists():
            continue
        rel = t.relative_to(workspace)
        print(f"  backup: {rel} -> {dest / rel}")
        if apply:
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(t, dest / rel)
    return dest


def step_outputs(workspace: Path, apply: bool) -> bool:
    """writing_outputs/<id>/ → .ra/outputs/<id>/（阶段2 任务 2.5 正式实现）。"""
    src = workspace / "writing_outputs"
    dst = workspace / ".ra" / "outputs"
    if not src.exists():
        print("  writing_outputs/ 不存在，跳过")
        return True
    entries = [p for p in src.iterdir() if p.is_dir()]
    print(f"  将迁移 {len(entries)} 个产物目录: {src} -> {dst}")
    for p in entries[:10]:
        print(f"    - {p.name}")
    if len(entries) > 10:
        print(f"    ... 其余 {len(entries) - 10} 个")
    if not apply:
        return True
    _backup(workspace, [src], apply=True)
    dst.mkdir(parents=True, exist_ok=True)
    for p in entries:
        target = dst / p.name
        if target.exists():
            print(f"  !! 目标已存在，跳过: {p.name}")
            continue
        shutil.move(str(p), str(target))
    print("  迁移完成（旧目录保留为空壳，请人工确认后删除）")
    return True


STEPS = {"outputs": step_outputs}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("workspace", type=Path)
    ap.add_argument("--apply", action="store_true", help="真实执行（默认 dry-run）")
    ap.add_argument("--step", choices=list(STEPS), default="outputs")
    args = ap.parse_args()

    ws = args.workspace.resolve()
    if not ws.is_dir():
        print(f"工作区不存在: {ws}", file=sys.stderr)
        return 2

    running = _running_runs(ws)
    if running != 0:
        print(
            f"拒绝迁移：检测到 {running if running > 0 else '未知数量'} 个运行中/排队任务。"
            "请先停止所有任务再迁移。",
            file=sys.stderr,
        )
        return 3

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] workspace={ws} step={args.step}")
    ok = STEPS[args.step](ws, apply=args.apply)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
