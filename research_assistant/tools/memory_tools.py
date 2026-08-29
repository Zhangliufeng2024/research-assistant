"""记忆工具（A+ 阶段 5 / G-1）：把 MemoryStore 暴露为模型可调用的工具。

以 ToolExtension 声明式扩展接入（见 registry.ToolExtension）——不改内置
handler 表，宿主（chat/cli）按需装配；CLI 单代理路径可以完全不注入。
"""

from __future__ import annotations

from pathlib import Path

from ..kernel.memory import MemoryStore, build_memory_store
from .registry import ToolExtension


def build_memory_extensions(
    workspace: str | Path, *, store: MemoryStore | None = None,
) -> list[ToolExtension]:
    """构建记忆三件套（save / recall / forget）。

    Args:
        workspace: 工作区根（记忆文件落在 ``<workspace>/.ra/memory.json``）。
        store: 显式传入的 MemoryStore（测试用）；缺省按 workspace 新建。
    """
    mem = store if store is not None else build_memory_store(workspace)

    def save_memory(text: str, tag: str = "fact") -> str:
        """(内部) 保存一条跨会话记忆。"""
        try:
            entry = mem.add(text, tag=tag)
        except ValueError as exc:
            return f"Error: {exc}"
        return (
            f"已保存记忆 {entry['id']}：{entry['text']}"
            f"（当前共 {len(mem.all_entries())} 条，新会话自动可见）"
        )

    def recall_memory(query: str = "", limit: int = 8) -> str:
        """(内部) 检索跨会话记忆；空 query 返回最近更新的记忆。"""
        hits = mem.recall(query, limit=max(1, min(int(limit), 20)))
        if not hits:
            return "没有匹配的记忆。可用 save_memory 保存重要事实供未来会话使用。"
        lines = [
            f"- [{h['id']}|{h.get('tag', 'fact')}] {h['text']}" for h in hits
        ]
        return f"命中 {len(hits)} 条：\n" + "\n".join(lines)

    def forget_memory(entry_id: str) -> str:
        """(内部) 删除一条记忆。"""
        return (
            f"已删除 {entry_id}" if mem.delete(entry_id)
            else f"Error: 未找到记忆 {entry_id}（用 recall_memory 查看现有 id）"
        )

    return [
        ToolExtension(
            name="save_memory",
            description=(
                "Save an important fact/preference/decision to persistent memory. "
                "Saved memories are injected into the system prompt of future "
                "sessions in this workspace. Use for durable facts only — not "
                "ephemeral task state. Max ~2 sentences per entry."
            ),
            schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The fact to remember"},
                    "tag": {"type": "string", "enum": ["fact", "preference", "decision", "todo"],
                            "description": "Memory category"},
                },
                "required": ["text"],
            },
            handler=save_memory,
        ),
        ToolExtension(
            name="recall_memory",
            description=(
                "Search persistent memories from previous sessions. Empty query "
                "returns the most recently updated memories."
            ),
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword query"},
                    "limit": {"type": "integer", "description": "Max results (default 8)"},
                },
            },
            handler=recall_memory,
        ),
        ToolExtension(
            name="forget_memory",
            description="Delete one memory by its id (see recall_memory output).",
            schema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "string", "description": "Memory id, e.g. m18f2a"},
                },
                "required": ["entry_id"],
            },
            handler=forget_memory,
        ),
    ]


def memory_prompt_section(store: MemoryStore) -> str:
    """系统提示追加段：有记忆才返回非空（调用方直接拼接）。"""
    rendered = store.render_prompt()
    return f"\n\n{rendered}" if rendered else ""
