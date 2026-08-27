"""Tests for the FTS5 project source library."""

import json

from research_assistant.context import SourceStore


def _store(tmp_path):
    return SourceStore(tmp_path / "sources.sqlite3")


def test_ingest_and_search_with_anchors(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_text("# 钙钛矿\n钙钛矿太阳能电池效率已达 26.1%。\n\n# 方法\n我们采用溶液法制备薄膜。", encoding="utf-8")
    store = _store(tmp_path)
    result = store.ingest_file(doc)
    assert result["chunks"] >= 1
    hits = store.search("钙钛矿 效率")
    assert hits
    anchor = hits[0]["anchor"]
    assert anchor["file"] == "notes.md"
    assert anchor["hash"]
    assert "钙钛矿" in hits[0]["snippet"]


def test_like_fallback_for_long_phrase(tmp_path):
    doc = tmp_path / "a.txt"
    phrase = "perovskite solar cells reached 26.1 percent efficiency in 2024"
    doc.write_text(phrase, encoding="utf-8")
    store = _store(tmp_path)
    store.ingest_file(doc)
    hits = store.search(phrase)
    assert hits and "26.1" in hits[0]["snippet"]


def test_delete_source_removes_chunks(tmp_path):
    doc = tmp_path / "b.txt"
    doc.write_text("unique-zebra-token alpha beta", encoding="utf-8")
    store = _store(tmp_path)
    created = store.ingest_file(doc)
    assert store.search("zebra")
    assert store.delete_source(created["id"])
    assert not store.search("zebra")


def test_export_context_block_format(tmp_path):
    doc = tmp_path / "c.txt"
    doc.write_text("graphene superlattice thermal conductivity", encoding="utf-8")
    store = _store(tmp_path)
    store.ingest_file(doc)
    block = store.export_context_block(["thermal"])
    assert block.startswith("\n# 项目资料库检索结果")
    assert "[c.txt" in block
    # empty library -> empty block
    empty = SourceStore(tmp_path / "empty.sqlite3")
    assert empty.export_context_block(["x"]) == ""


def test_json_roundtrip_of_anchor(tmp_path):
    doc = tmp_path / "d.txt"
    doc.write_text("stable anchor serialization check", encoding="utf-8")
    store = _store(tmp_path)
    store.ingest_file(doc)
    hit = store.search("serialization")[0]
    parsed = json.loads(json.dumps(hit))
    assert parsed["anchor"]["hash"] == hit["anchor"]["hash"]


def test_search_modes_return_ranked_anchors(tmp_path):
    doc = tmp_path / "semantic.txt"
    doc.write_text("solar photovoltaic cell efficiency and degradation", encoding="utf-8")
    store = _store(tmp_path)
    store.ingest_file(doc)
    for mode in ("keyword", "semantic", "hybrid"):
        hits = store.search("photovoltaic efficiency", mode=mode)
        assert hits and hits[0]["anchor"]["file"] == "semantic.txt"
        assert hits[0]["mode"] == mode
        assert isinstance(hits[0]["score"], float)


def test_search_punctuation_falls_back_without_raising(tmp_path):
    doc = tmp_path / "punctuation.txt"
    doc.write_text("alpha beta gamma", encoding="utf-8")
    store = _store(tmp_path)
    store.ingest_file(doc)
    assert store.search('alpha:"beta"', mode="hybrid")


def test_source_store_migrates_embedding_column(tmp_path):
    import sqlite3

    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            "CREATE TABLE sources (id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, "
            "created_at REAL NOT NULL, chunk_count INTEGER NOT NULL DEFAULT 0);"
            "CREATE TABLE source_chunks (id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT, "
            "idx INTEGER, page INTEGER, text TEXT NOT NULL, hash TEXT NOT NULL);"
        )
    store = SourceStore(db)
    doc = tmp_path / "new.txt"
    doc.write_text("migration vector", encoding="utf-8")
    assert store.ingest_file(doc)["chunks"] == 1
    assert store.search("vector", mode="semantic")
