"""A+ 阶段 5 / G-1：跨会话记忆（MemoryStore + 工具三件套 + 系统提示注入）。

设计要点（均有对应测试锁定）：
- 显式工具化（save/recall/forget），不做自动抽取；
- 存储 = <workspace>/.ra/memory.json，原子写，损坏起步为空（不致命）；
- 幂等：完全相同的文本不重复写，改为 hits+1；
- 淘汰：超上限时 hits 最低者优先、平局取最旧；
- 注入：render_prompt 无记忆返回空串（不加空节），超限截断；
- 工具经 ToolExtension 注册，schema 齐全，模型可见。
"""

from __future__ import annotations

import json

import pytest

from research_assistant.kernel.memory import (
    DEFAULT_MAX_ENTRIES,
    MemoryStore,
    build_memory_store,
)
from research_assistant.tools.memory_tools import (
    build_memory_extensions,
    memory_prompt_section,
)


@pytest.fixture()
def ws(tmp_path):
    return tmp_path


class TestMemoryStore:
    def test_add_and_persist_across_instances(self, ws):
        """跨会话语义：新实例（≈新会话）能读到先前实例写入的记忆。"""
        MemoryStore(ws).add("用户偏好中文回复", tag="preference")
        reopened = MemoryStore(ws)
        entries = reopened.all_entries()
        assert len(entries) == 1
        assert entries[0]["text"] == "用户偏好中文回复"
        assert entries[0]["tag"] == "preference"

    def test_duplicate_text_is_idempotent(self, ws):
        store = MemoryStore(ws)
        store.add("事实A")
        again = store.add("  事实A  ")  # 空白归一后相同 → 不重复
        assert len(store.all_entries()) == 1
        assert again["hits"] == 1, "重复保存应计为一次命中"

    def test_empty_text_is_rejected(self, ws):
        with pytest.raises(ValueError):
            MemoryStore(ws).add("   ")

    def test_recall_matches_keywords(self, ws):
        store = MemoryStore(ws)
        store.add("论文投稿目标是 Applied Energy")
        store.add("泰/Shopee 店铺主营家居")
        hits = store.recall("applied energy")
        assert len(hits) == 1
        assert "Applied Energy" in hits[0]["text"]
        # 无命中词的条目不出现
        assert all("Shopee" not in h["text"] for h in hits)

    def test_recall_empty_query_returns_recent(self, ws):
        store = MemoryStore(ws)
        store.add("旧记忆")
        store.add("新记忆")
        hits = store.recall("")
        assert hits[0]["text"] == "新记忆"  # updated_at 倒序

    def test_recall_miss_returns_empty(self, ws):
        store = MemoryStore(ws)
        store.add("完全不相关的记忆")
        assert store.recall("quantum-xyz") == []

    def test_delete_by_id(self, ws):
        store = MemoryStore(ws)
        entry = store.add("将被遗忘的记忆")
        assert store.delete(entry["id"]) is True
        assert store.all_entries() == []
        assert store.delete(entry["id"]) is False  # 幂等：再删不报错

    def test_eviction_prefers_lowest_hits_then_oldest(self, ws):
        """淘汰策略：hits 最低者优先，平局取最旧——高频使用的记忆存活。"""
        store = MemoryStore(ws, max_entries=3)
        a = store.add("A")           # 最旧，0 hits
        store.add("B")
        store.add("C")
        store.recall("B")            # B 命中 1 次
        store.recall("C")            # C 命中 1 次
        store.add("D")               # 满 → 淘汰 A（0 hits 且最旧）
        texts = {e["text"] for e in store.all_entries()}
        assert texts == {"B", "C", "D"}
        assert a["id"] not in {e["id"] for e in store.all_entries()}

    def test_default_cap_is_bounded(self, ws):
        store = MemoryStore(ws)
        for i in range(DEFAULT_MAX_ENTRIES + 20):
            store.add(f"记忆 {i}（唯一内容 {i}）")
        assert len(store.all_entries()) == DEFAULT_MAX_ENTRIES

    def test_corrupted_file_starts_empty(self, ws):
        """损坏的存储文件不致命：按空表起步（下次保存覆盖）。"""
        (ws / ".ra").mkdir()
        (ws / ".ra" / "memory.json").write_text("{broken json", encoding="utf-8")
        store = MemoryStore(ws)
        assert store.all_entries() == []
        store.add("恢复后仍可写")
        assert len(store.all_entries()) == 1

    def test_storage_is_atomic_json_at_expected_path(self, ws):
        store = MemoryStore(ws)
        store.add("落盘位置固定")
        raw = json.loads((ws / ".ra" / "memory.json").read_text(encoding="utf-8"))
        assert any(e["text"] == "落盘位置固定" for e in raw)


class TestPromptInjection:
    def test_render_prompt_empty_store_returns_empty(self, ws):
        assert MemoryStore(ws).render_prompt() == ""

    def test_render_prompt_lists_entries_with_header(self, ws):
        store = MemoryStore(ws)
        store.add("事实一", tag="decision")
        store.add("事实二")
        rendered = store.render_prompt()
        assert "跨会话记忆" in rendered
        assert "[decision] 事实一" in rendered
        assert "事实二" in rendered

    def test_render_prompt_respects_char_limit(self, ws):
        store = MemoryStore(ws, max_entries=50)
        for i in range(20):
            store.add("很长的记忆条目内容" * 20 + str(i))
        rendered = store.render_prompt(max_chars=500)
        assert len(rendered) < 500 + 200  # 头部留量
        assert "跨会话记忆" in rendered

    def test_memory_prompt_section_wrapper(self, ws):
        store = MemoryStore(ws)
        assert memory_prompt_section(store) == ""  # 空库 → 不拼空节
        store.add("有条目")
        section = memory_prompt_section(store)
        assert section.startswith("\n\n")  # 调用方直接拼接


class TestMemoryTools:
    def test_builds_three_extensions(self, ws):
        exts = build_memory_extensions(ws)
        assert [e.name for e in exts] == ["save_memory", "recall_memory", "forget_memory"]

    def test_save_and_recall_roundtrip_via_handlers(self, ws):
        exts = {e.name: e for e in build_memory_extensions(ws)}
        out = exts["save_memory"].handler(text="会议决定采用方案B", tag="decision")
        assert "已保存" in out
        out = exts["recall_memory"].handler(query="方案B")
        assert "方案B" in out

    def test_save_empty_text_returns_error_string(self, ws):
        exts = {e.name: e for e in build_memory_extensions(ws)}
        out = exts["save_memory"].handler(text="   ")
        assert out.startswith("Error:")  # 工具错误以字符串返回（模型可读）

    def test_forget_unknown_id_returns_error(self, ws):
        exts = {e.name: e for e in build_memory_extensions(ws)}
        assert exts["forget_memory"].handler(entry_id="mDeadBeef").startswith("Error:")

    def test_recall_counts_as_hit_and_persists(self, ws):
        exts = {e.name: e for e in build_memory_extensions(ws, store=None)}
        exts["save_memory"].handler(text="计数记忆")
        exts["recall_memory"].handler(query="计数")
        reopened = MemoryStore(ws)
        assert reopened.all_entries()[0]["hits"] == 1  # 命中计数持久化

    def test_schemas_are_model_visible(self, ws):
        for ext in build_memory_extensions(ws):
            definition = ext.to_definition()
            assert definition["name"] == ext.name
            assert definition["parameters"]["type"] == "object"

    def test_build_memory_store_creates_ra_dir(self, ws):
        build_memory_store(ws / "deep" / "nested")
        assert (ws / "deep" / "nested" / ".ra").is_dir()
