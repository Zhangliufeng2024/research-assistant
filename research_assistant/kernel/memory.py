"""跨会话记忆（A+ 阶段 5 / G-1）。

设计取向（刻意保持最小）：
- **显式工具化**而非自动抽取：模型经 ``save_memory`` / ``recall_memory``
  工具自主写入与检索。自动抽取（"每回合让 LLM 总结该记什么"）需要额外
  LLM 调用、阈值调参与误记治理，收益/成本比差；显式存取的可信度高得多。
- **存储**：``<workspace>/.ra/memory.json`` 单文件（原子写），随工作区
  走——换会话不丢，换工作区不串。条目带 ``created_at`` / ``hits``
  （命中计数，供后续淘汰策略）。
- **注入**：会话系统提示尾部追加 render_prompt() 的记忆摘要（按
  updated_at 倒序、截断到 max_chars），让新会话"开场即知道"。
- **淘汰**：满 ``max_entries`` 时丢弃 hits 最低且最旧的一条（先试
  最少使用，平局取最旧）——不做 LLM 参与的摘要合并，保持零额外调用。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ..core import atomic_write_text

MEMORY_FILENAME = "memory.json"
#: 记忆条目的默认条数上限（防止无限膨胀；超限按 LRU+LFU 淘汰）
DEFAULT_MAX_ENTRIES = 200
#: 注入系统提示的记忆摘要字符上限
PROMPT_CHARS_LIMIT = 4_000


class MemoryStore:
    """工作区级持久记忆（单文件 JSON，原子写，进程内即改即落盘）。"""

    def __init__(self, workspace: str | Path, *, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self.workspace = Path(workspace)
        self.path = self.workspace / ".ra" / MEMORY_FILENAME
        self.max_entries = max_entries
        self._entries: list[dict[str, Any]] = self._load()

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self) -> list[dict[str, Any]]:
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, ValueError):
            return []  # 首次使用 / 文件损坏 → 空表起步（损坏不致命）
        if not isinstance(data, list):
            return []
        return [e for e in data if isinstance(e, dict) and e.get("text")]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self.path, json.dumps(
            self._entries, ensure_ascii=False, indent=1,
        ))

    # ------------------------------------------------------------------
    # 增删查
    # ------------------------------------------------------------------

    def add(self, text: str, *, tag: str = "fact") -> dict[str, Any]:
        """新增一条记忆。与现有条目**完全相同**（去空格比对）时不重复写。"""
        cleaned = " ".join(str(text).split())
        if not cleaned:
            raise ValueError("记忆内容不能为空")
        for e in self._entries:
            if e["text"] == cleaned:
                e["hits"] = int(e.get("hits", 0)) + 1
                e["updated_at"] = time.time()
                self._save()
                return e
        entry: dict[str, Any] = {
            "id": f"m{int(time.time() * 1000):x}",
            "text": cleaned,
            "tag": str(tag or "fact"),
            "created_at": time.time(),
            "updated_at": time.time(),
            "hits": 0,
        }
        self._entries.append(entry)
        while len(self._entries) > self.max_entries:
            self._evict_one()
        self._save()
        return entry

    def _evict_one(self) -> None:
        """淘汰一条：hits 最低者优先，平局取 created_at 最旧。"""
        victim = min(self._entries, key=lambda e: (int(e.get("hits", 0)), e.get("created_at", 0)))
        self._entries.remove(victim)

    def recall(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """按关键词检索：命中词数多的在前，同分按更新时间倒序。空查询返回最新。"""
        terms = [t for t in str(query).lower().split() if t]
        scored: list[tuple[int, float, dict[str, Any]]] = []
        for e in self._entries:
            hay = e["text"].lower()
            if terms:
                score = sum(1 for t in terms if t in hay)
                if score == 0:
                    continue
            else:
                score = 0
            scored.append((score, float(e.get("updated_at", 0)), e))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        out = []
        for score, _ts, e in scored[:limit]:
            hit = dict(e)
            e["hits"] = int(e.get("hits", 0)) + 1  # 命中计数（随下次落盘持久化）
            hit["score"] = score
            out.append(hit)
        if out:
            self._save()
        return out

    def delete(self, entry_id: str) -> bool:
        """按 id 删除；返回是否真的删了。"""
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.get("id") != entry_id]
        changed = len(self._entries) != before
        if changed:
            self._save()
        return changed

    def all_entries(self) -> list[dict[str, Any]]:
        """按更新时间倒序的全量快照（管理端点用）。"""
        return sorted(self._entries, key=lambda e: -float(e.get("updated_at", 0)))

    # ------------------------------------------------------------------
    # 系统提示注入
    # ------------------------------------------------------------------

    def render_prompt(self, *, max_chars: int = PROMPT_CHARS_LIMIT) -> str:
        """渲染注入系统提示的记忆摘要；无记忆时返回空串（不加空节）。"""
        if not self._entries:
            return ""
        entries = self.all_entries()  # updated_at 倒序
        lines: list[str] = []
        used = 0
        for e in entries:
            line = f"- [{e.get('tag', 'fact')}] {e['text']}"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line) + 1
        if not lines:
            return ""
        header = (
            f"## 跨会话记忆（{len(lines)}/{len(self._entries)} 条，"
            "由此前会话经 save_memory 沉淀）"
        )
        return f"{header}\n" + "\n".join(lines)


def build_memory_store(workspace: str | Path) -> MemoryStore:
    """便捷工厂：供 chat 装配与工具注册使用（缺 .ra 目录时惰性创建）。"""
    ws = Path(workspace)
    (ws / ".ra").mkdir(parents=True, exist_ok=True)
    return MemoryStore(ws)
