"""审计 .claude/skills/ 的重复文件（只读，不改任何文件）。

背景：A+ 阶段 2 / F-7。``.claude/skills`` 体积 7.9MB / 433 个文件，且存在
**整树级**的字节级重复。它是**运行时镜像源**（core.py 按内容哈希同步到每个
新建工作区），重复意味着：体积膨胀、同步变慢、以及"改了 A 处 B 处还是旧的"
这类静默分叉。

为什么只做审计不做删改：core.py 的 ``sync_tree`` 按**路径**镜像——直接删掉
副本会让所有新工作区缺文件，而 SKILL.md 里的命令行引用也可能指向旧路径。
去重必须先知道"谁引用谁"，这正是本脚本要回答的问题。

用法：
    PYTHONPATH= python scripts/audit_skills_duplication.py
    # 输出 markdown 到 stdout；--json 输出机器可读结果

退出码：0 = 无重复；1 = 存在重复（可用于 CI 守卫，阶段 2 完成后收紧）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
SKILLS = REPO / ".claude" / "skills"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_duplicate_groups() -> dict[str, list[Path]]:
    """返回 sha256 → 文件列表，只保留 ≥2 的组。"""
    by_hash: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(SKILLS.rglob("*")):
        if not path.is_file():
            continue
        by_hash[_sha(path)].append(path)
    return {h: paths for h, paths in by_hash.items() if len(paths) > 1}


def analyse_forks() -> list[dict[str, Any]]:
    """检测**同名分叉树**：``<name>/`` 与 ``document-skills/<name>/`` 并存。

    A+ 阶段 2 / F-7 的重要更正：字节级重复文件多 ≠ 整树可删。实测
    ``docx/`` 与 ``document-skills/docx/`` 只有 **1 个文件一致**、7 个内容
    不同、其余互不重叠——这是**两套独立实现共用同一技能名**（fork），
    任何一侧都不能按"重复"删除：一侧独有 ``accept_changes.py``/``comment.py``
    /``office/`` 助手，另一侧独有 ``ooxml/`` schema 与 ``docx-js.md``。

    fork 比重复更危险：模型可能任选其一执行，两者行为不一致且各自演化，
    改 A 处 B 处静默过期。唯一安全的解法是**人工合并**，本方法只负责发现。
    """
    ds = SKILLS / "document-skills"
    if not ds.is_dir():
        return []
    forks: list[dict[str, Any]] = []
    for child in sorted(p for p in ds.iterdir() if p.is_dir()):
        twin = SKILLS / child.name
        if not twin.is_dir() or not (twin / "SKILL.md").exists():
            continue
        a_files = {p.relative_to(twin).as_posix() for p in twin.rglob("*") if p.is_file()}
        b_files = {p.relative_to(child).as_posix() for p in child.rglob("*") if p.is_file()}
        common = a_files & b_files
        same = sum(1 for rel in common if _sha(twin / rel) == _sha(child / rel))
        forks.append({
            "standalone": twin.name,
            "nested": f"document-skills/{child.name}",
            "files_identical": same,
            "files_differ": len(common) - same,
            "only_in_standalone": len(a_files - b_files),
            "only_in_nested": len(b_files - a_files),
        })
    return forks


def referenced_paths() -> dict[Path, set[str]]:
    """每个 SKILL.md 里出现过的 ``skills/<...>`` 路径引用。"""
    refs: dict[Path, set[str]] = {}
    pattern = re.compile(r"skills/[A-Za-z0-9_\-./]+")
    for skill_md in sorted(SKILLS.rglob("SKILL.md")):
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        refs[skill_md] = set(pattern.findall(text))
    return refs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if not SKILLS.is_dir():
        print(f"[SKIP] 未找到 {SKILLS}", file=sys.stderr)
        return 0

    groups = find_duplicate_groups()
    all_files = [p for p in SKILLS.rglob("*") if p.is_file()]
    total_size = sum(p.stat().st_size for p in all_files)
    dup_files = sum(len(g) - 1 for g in groups.values())
    dup_bytes = sum(
        sum(p.stat().st_size for p in g[1:]) for g in groups.values()
    )

    refs = referenced_paths()
    forks = analyse_forks()

    if args.json:
        print(json.dumps({
            "total_files": len(all_files),
            "total_bytes": total_size,
            "duplicate_groups": len(groups),
            "redundant_files": dup_files,
            "redundant_bytes": dup_bytes,
            "forks": forks,
            "groups": {
                h: [str(p.relative_to(SKILLS)) for p in paths]
                for h, paths in groups.items()
            },
            "skillmd_references": {
                str(k.relative_to(SKILLS)): sorted(v) for k, v in refs.items() if v
            },
        }, ensure_ascii=False, indent=2))
        return 1 if groups else 0

    print("# `.claude/skills` 重复与分叉审计（只读）\n")
    print(f"- 文件总数：{len(all_files)}（{total_size / 1024 / 1024:.2f} MB）")
    print(f"- 字节级重复组：**{len(groups)}**")
    print(f"- 冗余文件数：{dup_files}")
    print(f"- 可省空间：**{dup_bytes / 1024:.1f} KB**\n")

    if forks:
        print("## ⚠️ 同名分叉树（**不可按重复删除**）\n")
        print("以下技能在顶层与 `document-skills/` 各有一份实现，且**内容已分叉**：\n")
        print("| 顶层 | 嵌套 | 一致 | 不同 | 仅顶层 | 仅嵌套 |")
        print("|---|---|---|---|---|---|")
        for f in forks:
            print(
                f"| {f['standalone']} | {f['nested']} | {f['files_identical']} "
                f"| {f['files_differ']} | {f['only_in_standalone']} "
                f"| {f['only_in_nested']} |"
            )
        print()
        print("**处理原则**：这是两套独立实现共用同一技能名，不是重复。")
        print("删除任何一侧都会销毁几十个独有文件。唯一安全解法是人工合并：")
        print("确认哪一侧是功能超集 → 迁移另一侧的独有脚本 → 保留旧路径一个")
        print("版本 → 新建测试工作区验证 sync_tree 镜像完整。合并前这两套")
        print("技能对模型来说是随机二选一，行为不一致——这是比体积更大的问题。\n")

    if not groups:
        print("无字节级重复。")
        return 0

    print("## 重复组\n")
    for _h, paths in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        print(f"- `{paths[0].name}` ×{len(paths)}")
        for p in paths:
            print(f"  - `{p.relative_to(SKILLS)}`")
    print()

    print("## SKILL.md 中的路径引用（去重前必须核对）\n")
    for skill_md, used in sorted(refs.items()):
        if used:
            print(f"- `{skill_md.relative_to(SKILLS)}`：{len(used)} 个引用")

    print("\n## 建议的去重顺序\n")
    print("1. **共享工具函数**（如 `qiniu_image.py` 出现在 4 个技能）→")
    print("   抽到 `.claude/skills/_shared/`，各技能改薄转发层，保留旧路径一版。")
    print("2. **document-skills/{docx,pdf,pptx} 与独立 docx/、pdf/** →")
    print("   先确认 SKILL.md 与 core.py 的引用面，再合并为单一权威路径。")
    print("3. 每合并一批：新建测试工作区验证 `sync_tree` 镜像完整 + 技能冒烟。")
    print("\n**红线**：core.py 的 sync_tree 按路径镜像，删除前必须保留旧路径")
    print("转发层至少一个版本，并在 CI 加重复守卫（本脚本退出码即守卫信号）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
