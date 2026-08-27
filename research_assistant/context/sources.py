"""SQLite FTS5-backed project source library with stable retrieval anchors.

Files (PDF/DOCX/MD/TXT/BibTeX) are parsed into page/paragraph chunks and made
searchable.  Every chunk carries a stable anchor (file, page, index, hash) so
agents and the UI can cite exactly where evidence came from.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


EMBEDDING_DIMENSIONS = 128
MAX_VECTOR_CANDIDATES = 8_000


def _embedding(text: str) -> list[float]:
    """Build a deterministic local lexical embedding without extra packages."""
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for term in (part.lower() for part in text.split() if part.strip()):
        digest = hashlib.sha256(term.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [round(value / norm, 6) for value in vector] if norm else vector


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def _chunk_units(units: list[tuple[int | None, str]]) -> list[tuple[int | None, str]]:
    """Merge paragraph/page units into ~1500-char chunks (no mid-sentence cuts)."""
    chunks: list[tuple[int | None, str]] = []
    buf: list[str] = []
    buf_page: int | None = None
    size = 0

    def flush() -> None:
        nonlocal size
        if buf:
            chunks.append((buf_page, "\n".join(buf)))
            buf.clear()
            size = 0

    for page, text in units:
        for para in text.split("\n"):
            para = para.strip()
            if not para:
                continue
            if size + len(para) > 1500 and size > 0:
                flush()
                buf_page = page
            if buf_page is None:
                buf_page = page
            buf.append(para)
            size += len(para)
    flush()
    return chunks


class SourceStore:
    """Per-project source library stored next to the platform database."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS source_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                    idx INTEGER NOT NULL,
                    page INTEGER,
                    text TEXT NOT NULL,
                    hash TEXT NOT NULL,
                    embedding_json TEXT NOT NULL DEFAULT ''
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS source_fts USING fts5(
                    text, source_id UNINDEXED, idx UNINDEXED, page UNINDEXED
                );
                """
            )
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(source_chunks)")
            }
            if "embedding_json" not in columns:
                conn.execute(
                    "ALTER TABLE source_chunks ADD COLUMN embedding_json TEXT NOT NULL DEFAULT ''"
                )

    # ------------------------------------------------------------------ ingest

    def ingest_file(self, file_path: str | Path, name: str | None = None) -> dict[str, Any]:
        """Parse a supported file into searchable chunks."""
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            units = self._extract_pdf(path)
            kind = "pdf"
        elif suffix == ".docx":
            units = self._extract_docx(path)
            kind = "docx"
        else:
            units = [(None, path.read_text(encoding="utf-8", errors="replace"))]
            kind = "text"
        chunks = _chunk_units(units)
        source_id = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN")
            conn.execute(
                "INSERT INTO sources(id, name, kind, created_at, chunk_count) "
                "VALUES(?,?,?,?,?)",
                (source_id, name or path.name, kind, now, len(chunks)),
            )
            for idx, (page, text) in enumerate(chunks):
                conn.execute(
                    "INSERT INTO source_chunks(source_id, idx, page, text, hash, embedding_json) "
                    "VALUES(?,?,?,?,?,?)",
                    (source_id, idx, page, text, _sha(text), json.dumps(_embedding(text))),
                )
                conn.execute(
                    "INSERT INTO source_fts(text, source_id, idx, page) VALUES(?,?,?,?)",
                    (text, source_id, idx, page),
                )
        return {"id": source_id, "name": name or path.name, "kind": kind, "chunks": len(chunks)}

    @staticmethod
    def _extract_pdf(path: Path) -> list[tuple[int | None, str]]:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        units: list[tuple[int | None, str]] = []
        for i, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            if text:
                units.append((i + 1, text))
        return units

    @staticmethod
    def _extract_docx(path: Path) -> list[tuple[int | None, str]]:
        import docx

        document = docx.Document(str(path))
        paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        return [(None, "\n".join(paragraphs))] if paragraphs else []

    # ------------------------------------------------------------------ search

    def search(
        self,
        query: str,
        limit: int = 8,
        *,
        mode: str = "hybrid",
        lexical_weight: float = 0.65,
    ) -> list[dict[str, Any]]:
        """Search with keyword, local semantic, or hybrid ranking.

        The local hashed vector keeps semantic retrieval available offline;
        deployments can replace the embedding implementation later without
        changing the stable source-anchor contract.
        """
        query = (query or "").strip()
        if not query:
            return []
        mode = str(mode or "hybrid").lower()
        if mode not in {"keyword", "semantic", "hybrid"}:
            raise ValueError("search mode must be keyword, semantic, or hybrid")
        limit = max(1, min(int(limit), 50))
        lexical_weight = max(0.0, min(1.0, float(lexical_weight)))
        query_vector = _embedding(query)
        with self._lock, self._connect() as conn:
            safe_query = " OR ".join(
                '"' + term.replace('"', '""') + '"'
                for term in query.split()[:12]
            )
            try:
                lexical_rows = conn.execute(
                    """
                    SELECT f.source_id AS sid, f.idx AS cidx, f.page AS page,
                        snippet(source_fts, 0, '[', ']', '…', 24) AS snip,
                        s.name AS name, s.kind AS kind, c.hash AS hash
                    FROM source_fts f
                    JOIN sources s ON s.id = f.source_id
                    JOIN source_chunks c ON c.source_id = f.source_id AND c.idx = f.idx
                    WHERE source_fts MATCH ?
                    ORDER BY bm25(source_fts) LIMIT ?""",
                    (safe_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                # FTS syntax varies for punctuation and quoted user input;
                # fall through to the bounded LIKE path instead of returning 500.
                lexical_rows = []
            if not lexical_rows:
                like = f"%{query}%"
                lexical_rows = conn.execute(
                    """
                    SELECT c.source_id AS sid, c.idx AS cidx, c.page AS page,
                        substr(c.text, max(1, instr(lower(c.text), lower(?)) - 60), 400) AS snip,
                        s.name AS name, s.kind AS kind, c.hash AS hash
                    FROM source_chunks c JOIN sources s ON s.id = c.source_id
                    WHERE c.text LIKE ? LIMIT ?""",
                    (query, like, limit),
                ).fetchall()
            vector_rows = conn.execute(
                """
                SELECT c.source_id AS sid, c.idx AS cidx, c.page AS page,
                    c.text AS text, c.hash AS hash, c.embedding_json AS embedding,
                    s.name AS name, s.kind AS kind
                FROM source_chunks c JOIN sources s ON s.id = c.source_id
                WHERE c.embedding_json != '' LIMIT ?""",
                (MAX_VECTOR_CANDIDATES,),
            ).fetchall()

        candidates: dict[tuple[str, int], dict[str, Any]] = {}
        for rank, row in enumerate(lexical_rows):
            candidates[(row["sid"], int(row["cidx"]))] = {
                "anchor": {
                    "file": row["name"], "source_id": row["sid"], "kind": row["kind"],
                    "page": row["page"], "chunk": row["cidx"], "hash": row["hash"],
                },
                "snippet": row["snip"],
                "lexical_score": 1.0 / (rank + 1),
            }
        for row in vector_rows:
            key = (row["sid"], int(row["cidx"]))
            try:
                semantic_score = _cosine(query_vector, json.loads(row["embedding"]))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            item = candidates.setdefault(key, {
                "anchor": {
                    "file": row["name"], "source_id": row["sid"], "kind": row["kind"],
                    "page": row["page"], "chunk": row["cidx"], "hash": row["hash"],
                },
                "snippet": str(row["text"])[:400],
                "lexical_score": 0.0,
            })
            item["semantic_score"] = semantic_score

        if mode == "keyword":
            ranked = sorted(
                (item for item in candidates.values() if item.get("lexical_score", 0) > 0),
                key=lambda item: item.get("lexical_score", 0), reverse=True,
            )
        elif mode == "semantic":
            ranked = sorted(
                candidates.values(), key=lambda item: item.get("semantic_score", -1), reverse=True,
            )
        else:
            ranked = sorted(
                candidates.values(),
                key=lambda item: lexical_weight * item.get("lexical_score", 0)
                + (1 - lexical_weight) * max(0.0, item.get("semantic_score", 0)),
                reverse=True,
            )
        results: list[dict[str, Any]] = []
        for item in ranked[:limit]:
            if mode == "keyword":
                score = item.get("lexical_score", 0)
            elif mode == "semantic":
                score = max(0.0, item.get("semantic_score", 0))
            else:
                score = lexical_weight * item.get("lexical_score", 0) + (
                    1 - lexical_weight
                ) * max(0.0, item.get("semantic_score", 0))
            item["score"] = round(score, 6)
            item["mode"] = mode
            item.pop("lexical_score", None)
            item.pop("semantic_score", None)
            results.append(item)
        return results

    def list_sources(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, kind, created_at, chunk_count FROM sources "
                "ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_source(self, source_id: str) -> bool:
        with self._lock, self._connect() as conn:
            # FTS5 virtual tables do not participate in FK cascades; remove
            # their rows explicitly or a long-lived project accumulates stale
            # searchable text after users delete a source.
            conn.execute("DELETE FROM source_fts WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM source_chunks WHERE source_id = ?", (source_id,))
            cursor = conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            return cursor.rowcount > 0

    def export_context_block(self, queries: list[str], per_query: int = 3) -> str:
        """Compact retrieval block for injection into agent prompts."""
        seen: set[str] = set()
        lines: list[str] = []
        cap = max(per_query, 1) * max(len(queries), 1)
        for q in queries:
            for hit in self.search(q, limit=per_query):
                key = hit["anchor"]["hash"]
                if key in seen:
                    continue
                seen.add(key)
                a = hit["anchor"]
                loc = f"p.{a['page']}" if a.get("page") else f"chunk#{a['chunk']}"
                lines.append(f"- [{a['file']} {loc}] {hit['snippet']}")
                if len(lines) >= cap:
                    break
        if not lines:
            return ""
        return "\n# 项目资料库检索结果（引用时标注来源锚点）\n" + "\n".join(lines)
