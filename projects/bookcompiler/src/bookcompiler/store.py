from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .models import Chunk, ParsedBook, utc_now
from .utils import stable_id


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def query_terms(query: str) -> list[str]:
    query = (query or "").lower()
    terms: list[str] = []
    terms.extend(re.findall(r"[a-z0-9_]+", query))
    for block in re.findall(r"[\u4e00-\u9fff]+", query):
        if len(block) <= 2:
            terms.append(block)
        else:
            terms.extend(block[i : i + 2] for i in range(len(block) - 1))
            terms.extend(block[i : i + 3] for i in range(len(block) - 2))
    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        term = term.strip()
        if not term or term in seen:
            continue
        seen.add(term)
        unique.append(term)
        if len(unique) >= 30:
            break
    return unique


def _fts_query(terms: list[str]) -> str:
    return " OR ".join(f'"{t.replace(chr(34), chr(34) * 2)}"' for t in terms if t)


class Store:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.fts_enabled = True
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        columns = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS books (
                book_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                path TEXT NOT NULL,
                format TEXT NOT NULL,
                disciplines TEXT NOT NULL,
                chapters INTEGER NOT NULL,
                pages INTEGER,
                ingested_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ingested'
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                book_id TEXT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
                chapter_index INTEGER NOT NULL,
                chapter_title TEXT NOT NULL,
                position INTEGER NOT NULL,
                text TEXT NOT NULL,
                page_start INTEGER,
                page_end INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_book ON chunks(book_id);
            CREATE TABLE IF NOT EXISTS book_cards (
                book_id TEXT PRIMARY KEY REFERENCES books(book_id) ON DELETE CASCADE,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS frameworks (
                framework_id TEXT PRIMARY KEY,
                book_id TEXT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                lenses TEXT NOT NULL,
                data TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS edges (
                edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_type TEXT NOT NULL,
                src_id TEXT NOT NULL,
                dst_type TEXT NOT NULL,
                dst_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                evidence TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                UNIQUE(src_type, src_id, dst_type, dst_id, relation)
            );
            CREATE TABLE IF NOT EXISTS analyses (
                analysis_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
                feedback_id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                rating INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                error_labels TEXT NOT NULL DEFAULT '[]',
                preferred_book_ids TEXT NOT NULL DEFAULT '[]',
                preferred_framework_ids TEXT NOT NULL DEFAULT '[]',
                missing_evidence TEXT NOT NULL DEFAULT '',
                outcome TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS reading_evaluations (
                evaluation_id TEXT PRIMARY KEY,
                analysis_id TEXT NOT NULL,
                evaluator TEXT NOT NULL,
                rubric_version TEXT NOT NULL,
                total REAL NOT NULL,
                scores TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reading_evaluations_analysis ON reading_evaluations(analysis_id);
            CREATE TABLE IF NOT EXISTS memory (
                memory_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evolution_proposals (
                proposal_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'proposed',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunk_embeddings (
                chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
                model TEXT NOT NULL,
                dim INTEGER NOT NULL,
                vector BLOB NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (chunk_id, model)
            );
            CREATE INDEX IF NOT EXISTS idx_embeddings_model ON chunk_embeddings(model);
            CREATE TABLE IF NOT EXISTS entities (
                entity_id TEXT PRIMARY KEY,
                canonical_name TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'concept',
                aliases TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS entity_mentions (
                entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
                chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
                book_id TEXT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
                surface TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                PRIMARY KEY (entity_id, chunk_id, surface)
            );
            CREATE INDEX IF NOT EXISTS idx_mentions_entity ON entity_mentions(entity_id);
            CREATE INDEX IF NOT EXISTS idx_mentions_chunk ON entity_mentions(chunk_id);
            CREATE TABLE IF NOT EXISTS entity_relations (
                relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
                dst_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
                relation TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                evidence TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                UNIQUE(src_entity_id, dst_entity_id, relation)
            );
            CREATE TABLE IF NOT EXISTS evolution_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evolution_runs (
                run_id TEXT PRIMARY KEY,
                proposal_id TEXT NOT NULL,
                mode TEXT NOT NULL,
                metrics TEXT NOT NULL DEFAULT '{}',
                snapshot TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY,
                claim_key TEXT NOT NULL,
                base_key TEXT NOT NULL,
                subject TEXT NOT NULL,
                subject_entity_id TEXT NOT NULL DEFAULT '',
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                polarity INTEGER NOT NULL DEFAULT 1,
                conditions TEXT NOT NULL DEFAULT '[]',
                book_id TEXT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
                chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
                page INTEGER,
                quote TEXT NOT NULL,
                valid_from TEXT,
                valid_to TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                resolution TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_claims_base_key ON claims(base_key);
            CREATE INDEX IF NOT EXISTS idx_claims_book ON claims(book_id);
            CREATE INDEX IF NOT EXISTS idx_claims_status ON claims(status);
            CREATE TABLE IF NOT EXISTS claim_relations (
                relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
                dst_claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
                relation TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(src_claim_id, dst_claim_id, relation)
            );
            CREATE TABLE IF NOT EXISTS claim_evidence (
                claim_id TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
                chunk_id TEXT NOT NULL REFERENCES chunks(chunk_id) ON DELETE CASCADE,
                book_id TEXT NOT NULL REFERENCES books(book_id) ON DELETE CASCADE,
                quote TEXT NOT NULL,
                page INTEGER,
                PRIMARY KEY (claim_id, chunk_id, quote)
            );
            CREATE TABLE IF NOT EXISTS entity_merge_candidates (
                candidate_id TEXT PRIMARY KEY,
                left_id TEXT NOT NULL,
                right_id TEXT NOT NULL,
                left_name TEXT NOT NULL,
                right_name TEXT NOT NULL,
                similarity REAL NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                shared_books TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                decision_note TEXT NOT NULL DEFAULT '',
                snapshot TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                decided_at TEXT NOT NULL DEFAULT '',
                UNIQUE(left_id, right_id)
            );
            """
        )
        for column, ddl in [
            ("error_labels", "TEXT NOT NULL DEFAULT '[]'"),
            ("preferred_book_ids", "TEXT NOT NULL DEFAULT '[]'"),
            ("preferred_framework_ids", "TEXT NOT NULL DEFAULT '[]'"),
            ("missing_evidence", "TEXT NOT NULL DEFAULT ''"),
            ("outcome", "TEXT NOT NULL DEFAULT ''"),
        ]:
            self._ensure_column("feedback", column, ddl)
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, book_id UNINDEXED, chapter_title, text, tokenize='unicode61')"
            )
        except sqlite3.OperationalError:
            self.fts_enabled = False
        self.conn.commit()

    @staticmethod
    def _chunk_signature(rows: list[tuple[str, str]]) -> str:
        digest = hashlib.sha256()
        for chunk_id, text in rows:
            digest.update(chunk_id.encode("utf-8"))
            digest.update(b"\x00")
            digest.update(text.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()

    def _drop_edges_for_nodes(self, node_type: str, node_ids: list[str]) -> None:
        for start in range(0, len(node_ids), 400):
            batch = node_ids[start : start + 400]
            placeholders = ",".join("?" for _ in batch)
            self.conn.execute(
                f"DELETE FROM edges WHERE (src_type = ? AND src_id IN ({placeholders})) OR (dst_type = ? AND dst_id IN ({placeholders}))",
                [node_type, *batch, node_type, *batch],
            )

    def invalidate_compilation(self, book_id: str, drop_chunks: bool = True) -> None:
        """Remove derived artifacts whose provenance points at this book.

        Re-ingesting changed text invalidates compiled cards, frameworks, and edges.
        Leaving them in place would let the agent cite stale chunk IDs or stale claims.
        Metadata-only changes keep the chunks but still invalidate cards/frameworks.
        """
        old_frameworks = [row["framework_id"] for row in self.conn.execute("SELECT framework_id FROM frameworks WHERE book_id = ?", (book_id,)).fetchall()]
        old_chunks = [row["chunk_id"] for row in self.conn.execute("SELECT chunk_id FROM chunks WHERE book_id = ?", (book_id,)).fetchall()]
        self.conn.execute("DELETE FROM frameworks WHERE book_id = ?", (book_id,))
        self.conn.execute("DELETE FROM book_cards WHERE book_id = ?", (book_id,))
        self._drop_edges_for_nodes("framework", old_frameworks)
        self._drop_edges_for_nodes("chunk", old_chunks)
        self.conn.execute(
            "DELETE FROM edges WHERE (src_type = 'book' AND src_id = ?) OR (dst_type = 'book' AND dst_id = ?)",
            (book_id, book_id),
        )
        if drop_chunks:
            self.conn.execute("DELETE FROM chunks WHERE book_id = ?", (book_id,))
            if self.fts_enabled:
                self.conn.execute("DELETE FROM chunks_fts WHERE book_id = ?", (book_id,))
        self.conn.execute("UPDATE books SET status = 'ingested' WHERE book_id = ?", (book_id,))

    def add_book(self, parsed: ParsedBook) -> None:
        existing = self.get_book(parsed.book_id)
        new_rows = [(chunk.chunk_id, chunk.text) for chunk in parsed.chunks]
        content_changed = True
        metadata_changed = False
        if existing:
            metadata_changed = (
                existing.get("title") != parsed.title
                or existing.get("author") != parsed.author
                or set(existing.get("disciplines", [])) != set(parsed.disciplines)
            )
            old_rows = [
                (row["chunk_id"], row["text"])
                for row in self.conn.execute(
                    "SELECT chunk_id, text FROM chunks WHERE book_id = ? ORDER BY chapter_index, position",
                    (parsed.book_id,),
                ).fetchall()
            ]
            content_changed = self._chunk_signature(old_rows) != self._chunk_signature(new_rows)

        if existing:
            self.conn.execute(
                "UPDATE books SET title = ?, author = ?, path = ?, format = ?, disciplines = ?, chapters = ?, pages = ? WHERE book_id = ?",
                (parsed.title, parsed.author, parsed.path, parsed.format, _json(parsed.disciplines), len(parsed.chapters), parsed.pages, parsed.book_id),
            )
            if content_changed or metadata_changed:
                self.invalidate_compilation(parsed.book_id, drop_chunks=content_changed)
        else:
            self.conn.execute(
                "INSERT INTO books (book_id, title, author, path, format, disciplines, chapters, pages, ingested_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (parsed.book_id, parsed.title, parsed.author, parsed.path, parsed.format, _json(parsed.disciplines), len(parsed.chapters), parsed.pages, utc_now(), "ingested"),
            )

        if content_changed:
            for chunk in parsed.chunks:
                self.conn.execute(
                    "INSERT INTO chunks (chunk_id, book_id, chapter_index, chapter_title, position, text, page_start, page_end) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (chunk.chunk_id, chunk.book_id, chunk.chapter_index, chunk.chapter_title, chunk.position, chunk.text, chunk.page_start, chunk.page_end),
                )
                if self.fts_enabled:
                    self.conn.execute(
                        "INSERT INTO chunks_fts (chunk_id, book_id, chapter_title, text) VALUES (?, ?, ?, ?)",
                        (chunk.chunk_id, chunk.book_id, chunk.chapter_title, chunk.text),
                    )
        self.conn.commit()
        if parsed.chunks:
            try:
                self.embed_pending(book_id=parsed.book_id)
            except Exception:
                # Ingestion must still succeed if an optional remote embedding
                # backend is unavailable; the local backend is retried lazily.
                pass

    def list_books(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM books ORDER BY ingested_at DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["disciplines"] = _loads(item.get("disciplines"), [])
            result.append(item)
        return result

    def get_book(self, book_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM books WHERE book_id = ?", (book_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["disciplines"] = _loads(item.get("disciplines"), [])
        return item

    def learned_book_ids(self) -> set[str]:
        """Books whose book card was actually verified.

        A compiled artifact is not the same thing as learned knowledge.  A
        heuristic/draft card can contain citations, but it has not been
        reviewed.  Agent-facing selection and recall only use books whose card
        status is ``verified`` or ``complete`` and that have at least one
        framework.  This is the second line of defence behind
        ``save_book_card``: legacy databases may still contain rows whose book
        status says compiled after a heuristic compile.
        """
        rows = self.conn.execute(
            "SELECT b.book_id, c.data FROM books b "
            "JOIN book_cards c ON c.book_id = b.book_id "
            "WHERE b.status = 'compiled' "
            "AND EXISTS (SELECT 1 FROM frameworks f WHERE f.book_id = b.book_id)"
        ).fetchall()
        learned: set[str] = set()
        for row in rows:
            card = _loads(row["data"], {})
            if isinstance(card, dict) and str(card.get("status", "")).lower() in {"verified", "complete"}:
                learned.add(row["book_id"])
        return learned

    def get_chunks(self, book_id: str) -> list[Chunk]:
        rows = self.conn.execute("SELECT * FROM chunks WHERE book_id = ? ORDER BY chapter_index, position", (book_id,)).fetchall()
        return [Chunk(**dict(row)) for row in rows]

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        row = self.conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,)).fetchone()
        return Chunk(**dict(row)) if row else None
    def search_chunks(self, query: str, book_ids: list[str] | None = None, limit: int = 12, mode: str = "hybrid") -> list[dict[str, Any]]:
        """Search chunks with hybrid retrieval by default.

        `mode="lexical"` keeps the original BM25-style behavior for diagnostics
        and replay comparisons.
        """
        if mode == "hybrid":
            from .retrieval import hybrid_search
            return hybrid_search(self, query, book_ids=book_ids, limit=limit, mode="hybrid")
        return self._search_chunks_lexical(query, book_ids=book_ids, limit=limit)

    def _search_chunks_lexical(self, query: str, book_ids: list[str] | None = None, limit: int = 12) -> list[dict[str, Any]]:
        terms = query_terms(query)
        if not terms:
            return []
        params: list[Any] = []
        where = ""
        if book_ids:
            placeholders = ",".join("?" for _ in book_ids)
            where = f"WHERE book_id IN ({placeholders})"
            params.extend(book_ids)
        rows = self.conn.execute(f"SELECT * FROM chunks {where}", params).fetchall()
        fts_ids: set[str] = set()
        if self.fts_enabled:
            try:
                fts_rows = self.conn.execute(
                    "SELECT chunk_id FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT 200",
                    (_fts_query(terms),),
                ).fetchall()
                fts_ids = {row["chunk_id"] for row in fts_rows}
            except sqlite3.OperationalError:
                fts_ids = set()
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            item = dict(row)
            text_l = item["text"].lower()
            title_l = item["chapter_title"].lower()
            score = 0.0
            for term in terms:
                if re.fullmatch(r"[a-z0-9_]+", term):
                    score += min(text_l.count(term), 5)
                    if term in title_l:
                        score += 2
                else:
                    score += min(item["text"].count(term), 5)
                    if term in item["chapter_title"]:
                        score += 2
            if item["chunk_id"] in fts_ids:
                score += 3
            if score > 0:
                item["score"] = score
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["book_id"], pair[1]["chapter_index"], pair[1]["position"]))
        return [item for _, item in scored[:limit]]

    def save_book_card(self, book_id: str, card: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO book_cards (book_id, data, created_at) VALUES (?, ?, ?)",
            (book_id, _json(card), utc_now()),
        )
        card_status = str(card.get("status", "draft")).lower()
        # Importing or heuristically compiling a book is not learning it.  Only
        # a verified/complete card may enter the learned set that book_plan and
        # book_recall use.  Keeping the shallow card visible in the library is
        # still useful, but it must not masquerade as reviewed knowledge.
        book_status = "compiled" if card_status in {"verified", "complete"} else "ingested"
        self.conn.execute("UPDATE books SET status = ? WHERE book_id = ?", (book_status, book_id))
        self.conn.commit()

    def get_book_card(self, book_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM book_cards WHERE book_id = ?", (book_id,)).fetchone()
        return _loads(row["data"], None) if row else None

    def replace_frameworks(self, book_id: str, frameworks: list[dict[str, Any]]) -> None:
        old = self.conn.execute("SELECT framework_id FROM frameworks WHERE book_id = ?", (book_id,)).fetchall()
        old_ids = [row["framework_id"] for row in old]
        self.conn.execute("DELETE FROM frameworks WHERE book_id = ?", (book_id,))
        for framework_id in old_ids:
            self.conn.execute(
                "DELETE FROM edges WHERE (src_type = 'framework' AND src_id = ?) OR (dst_type = 'framework' AND dst_id = ?)",
                (framework_id, framework_id),
            )
        for framework in frameworks:
            self.conn.execute(
                "INSERT OR REPLACE INTO frameworks (framework_id, book_id, name, lenses, data, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    framework["framework_id"],
                    book_id,
                    framework.get("name", "Untitled framework"),
                    _json(framework.get("lenses", [])),
                    _json(framework),
                    framework.get("status", "draft"),
                    utc_now(),
                ),
            )
        self.conn.commit()

    def list_frameworks(self, book_ids: list[str] | None = None, lenses: list[str] | None = None) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT data FROM frameworks ORDER BY created_at DESC").fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = _loads(row["data"], None)
            if not item:
                continue
            if book_ids and item.get("book_id") not in book_ids:
                continue
            if lenses and not set(lenses).intersection(set(item.get("lenses", []))):
                continue
            result.append(item)
        return result

    def get_framework(self, framework_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM frameworks WHERE framework_id = ?", (framework_id,)).fetchone()
        return _loads(row["data"], None) if row else None

    def add_edge(self, src_type: str, src_id: str, dst_type: str, dst_id: str, relation: str, evidence: list[dict[str, Any]] | None = None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO edges (src_type, src_id, dst_type, dst_id, relation, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (src_type, src_id, dst_type, dst_id, relation, _json(evidence or []), utc_now()),
        )
        self.conn.commit()

    def list_edges(self, src_id: str | None = None, dst_id: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if src_id:
            clauses.append("src_id = ?")
            params.append(src_id)
        if dst_id:
            clauses.append("dst_id = ?")
            params.append(dst_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(f"SELECT * FROM edges {where} ORDER BY edge_id", params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["evidence"] = _loads(item.get("evidence"), [])
            result.append(item)
        return result
    def _index_analysis_edges(self, packet: dict[str, Any]) -> None:
        analysis_id = packet.get("analysis_id", "")
        if not analysis_id:
            return
        self.conn.execute("DELETE FROM edges WHERE src_type = 'analysis' AND src_id = ?", (analysis_id,))
        selection = packet.get("selection", {})
        books = selection.get("books", []) if isinstance(selection, dict) else []
        for book in books:
            book_id = book.get("book_id") if isinstance(book, dict) else None
            if book_id:
                self.conn.execute(
                    "INSERT OR IGNORE INTO edges (src_type, src_id, dst_type, dst_id, relation, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("analysis", analysis_id, "book", book_id, "uses", _json([book]), utc_now()),
                )
        for framework in packet.get("frameworks", []):
            framework_id = framework.get("framework_id")
            if framework_id:
                self.conn.execute(
                    "INSERT OR IGNORE INTO edges (src_type, src_id, dst_type, dst_id, relation, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("analysis", analysis_id, "framework", framework_id, "uses", "[]", utc_now()),
                )
        for hypothesis in packet.get("hypotheses", []):
            framework_id = hypothesis.get("framework_id")
            if framework_id:
                self.conn.execute(
                    "INSERT OR IGNORE INTO edges (src_type, src_id, dst_type, dst_id, relation, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("analysis", analysis_id, "framework", framework_id, "tests", "[]", utc_now()),
                )
        for citation in packet.get("citations", []):
            chunk_id = citation.get("chunk_id")
            if chunk_id:
                self.conn.execute(
                    "INSERT OR IGNORE INTO edges (src_type, src_id, dst_type, dst_id, relation, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ("analysis", analysis_id, "chunk", chunk_id, "cites", _json([citation]), utc_now()),
                )
        self.conn.commit()

    def save_analysis(self, packet: Any) -> None:
        data = packet.to_dict()
        self.conn.execute(
            "INSERT OR REPLACE INTO analyses (analysis_id, data, created_at) VALUES (?, ?, ?)",
            (packet.analysis_id, _json(data), packet.created_at),
        )
        self.conn.commit()
        self._index_analysis_edges(data)

    def get_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM analyses WHERE analysis_id = ?", (analysis_id,)).fetchone()
        return _loads(row["data"], None) if row else None

    def list_analyses(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT data FROM analyses ORDER BY created_at DESC").fetchall()
        return [_loads(row["data"], {}) for row in rows]

    def add_feedback(
        self,
        analysis_id: str,
        rating: int,
        note: str = "",
        error_labels: list[str] | None = None,
        preferred_book_ids: list[str] | None = None,
        preferred_framework_ids: list[str] | None = None,
        missing_evidence: str = "",
        outcome: str = "",
    ) -> str:
        created_at = utc_now()
        feedback_id = stable_id(
            analysis_id,
            str(rating),
            note,
            ",".join(error_labels or []),
            ",".join(preferred_book_ids or []),
            ",".join(preferred_framework_ids or []),
            missing_evidence,
            outcome,
            created_at,
        )
        self.conn.execute(
            "INSERT INTO feedback (feedback_id, analysis_id, rating, note, created_at, error_labels, preferred_book_ids, preferred_framework_ids, missing_evidence, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                feedback_id,
                analysis_id,
                rating,
                note,
                created_at,
                _json(error_labels or []),
                _json(preferred_book_ids or []),
                _json(preferred_framework_ids or []),
                missing_evidence,
                outcome,
            ),
        )
        self.conn.commit()
        return feedback_id

    def list_feedback(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM feedback ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            for column in ("error_labels", "preferred_book_ids", "preferred_framework_ids"):
                item[column] = _loads(item.get(column), [])
            result.append(item)
        return result

    def save_reading_evaluation(self, evaluation: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO reading_evaluations "
            "(evaluation_id, analysis_id, evaluator, rubric_version, total, scores, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                evaluation["evaluation_id"],
                evaluation.get("analysis_id", ""),
                evaluation.get("evaluator", ""),
                evaluation.get("rubric_version", ""),
                float(evaluation.get("total", 0.0)),
                _json(evaluation.get("scores", {})),
                _json(evaluation),
                evaluation.get("created_at", utc_now()),
            ),
        )
        self.conn.commit()

    def list_reading_evaluations(self, analysis_id: str = "", limit: int = 500) -> list[dict[str, Any]]:
        if analysis_id:
            rows = self.conn.execute(
                "SELECT data FROM reading_evaluations WHERE analysis_id = ? ORDER BY created_at DESC LIMIT ?",
                (analysis_id, max(1, int(limit))),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT data FROM reading_evaluations ORDER BY created_at DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
        return [_loads(row["data"], {}) for row in rows]

    def preference_weights(self) -> dict[str, dict[str, float]]:
        books: dict[str, float] = {}
        frameworks: dict[str, float] = {}
        for feedback in self.list_feedback():
            for book_id in feedback.get("preferred_book_ids", []):
                books[book_id] = books.get(book_id, 0.0) + 1.0
            for framework_id in feedback.get("preferred_framework_ids", []):
                frameworks[framework_id] = frameworks.get(framework_id, 0.0) + 1.0
        return {"books": books, "frameworks": frameworks}

    def add_memory(self, kind: str, key: str, value: Any) -> str:
        memory_id = stable_id(kind, key, utc_now())
        self.conn.execute(
            "INSERT INTO memory (memory_id, kind, key, value, created_at) VALUES (?, ?, ?, ?, ?)",
            (memory_id, kind, key, _json(value), utc_now()),
        )
        self.conn.commit()
        return memory_id

    def list_memory(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM memory ORDER BY created_at DESC").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["value"] = _loads(item.get("value"), None)
            result.append(item)
        return result

    def save_evolution_proposal(self, proposal: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO evolution_proposals (proposal_id, data, status, created_at) VALUES (?, ?, ?, ?)",
            (proposal["proposal_id"], _json(proposal), proposal.get("status", "proposed"), proposal.get("created_at", utc_now())),
        )
        self.conn.commit()

    def get_evolution_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT data FROM evolution_proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
        return _loads(row["data"], None) if row else None

    def list_evolution_proposals(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.conn.execute("SELECT data FROM evolution_proposals WHERE status = ? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = self.conn.execute("SELECT data FROM evolution_proposals ORDER BY created_at DESC").fetchall()
        return [_loads(row["data"], {}) for row in rows]

    def set_evolution_status(self, proposal_id: str, status: str, note: str = "") -> dict[str, Any]:
        proposal = self.get_evolution_proposal(proposal_id)
        if not proposal:
            raise ValueError(f"Unknown proposal_id: {proposal_id}")
        proposal["status"] = status
        proposal["decision_note"] = note
        proposal["decided_at"] = utc_now()
        self.save_evolution_proposal(proposal)
        return proposal

    # ---- embeddings -----------------------------------------------------
    def save_embeddings(self, vectors: dict[str, list[float]], model: str, dim: int) -> int:
        from .embeddings import pack_vector
        now = utc_now()
        count = 0
        for chunk_id, vector in vectors.items():
            self.conn.execute(
                "INSERT OR REPLACE INTO chunk_embeddings (chunk_id, model, dim, vector, updated_at) VALUES (?, ?, ?, ?, ?)",
                (chunk_id, model, len(vector), pack_vector(vector), now),
            )
            count += 1
        self.conn.commit()
        return count

    def get_embeddings(self, model: str, chunk_ids: list[str] | None = None) -> dict[str, list[float]]:
        from .embeddings import unpack_vector
        params: list[Any] = [model]
        where = "WHERE model = ?"
        if chunk_ids:
            placeholders = ",".join("?" for _ in chunk_ids)
            where += f" AND chunk_id IN ({placeholders})"
            params.extend(chunk_ids)
        rows = self.conn.execute(f"SELECT chunk_id, vector FROM chunk_embeddings {where}", params).fetchall()
        return {row["chunk_id"]: unpack_vector(row["vector"]) for row in rows}

    def embedding_stats(self, active_model: str = "") -> dict[str, Any]:
        """Return coverage for the model retrieval will actually use.

        The database can contain several vector spaces (for example a local
        fallback plus a remote model). Reporting the largest table as "active"
        can hide a partially embedded remote index, so callers may pin the
        model name and get truthful ``missing_chunks`` for that space.
        """
        rows = self.conn.execute(
            "SELECT model, COUNT(*) AS embedded, MAX(dim) AS dim "
            "FROM chunk_embeddings GROUP BY model ORDER BY embedded DESC, model ASC"
        ).fetchall()
        total = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        models = [dict(row) for row in rows]
        selected = next((item for item in models if item["model"] == active_model), None)
        if selected is None:
            selected = {} if active_model else (models[0] if models else {})
        selected_model = active_model or selected.get("model", "")
        embedded = int(selected.get("embedded", 0)) if selected else 0
        return {
            "total_chunks": total,
            "models": models,
            "active_model": selected_model,
            "embedded_chunks": embedded,
            "missing_chunks": max(0, total - embedded),
            "coverage": round(float(embedded) / total, 4) if total else 0.0,
        }

    def embed_pending(
        self,
        backend=None,
        book_id: str | None = None,
        force: bool = False,
        chunk_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Embed chunks that do not have a vector for the active model.

        ``chunk_ids`` lets retrieval fill only the rows it is about to search
        instead of rebuilding the whole library. A failed remote backend falls
        back to the local backend, but the persisted model name and the returned
        vector space always agree.
        """
        from .embeddings import embed_texts, get_embedder
        backend = backend or get_embedder()
        params: list[Any] = []
        where = "WHERE 1=1"
        if book_id:
            where += " AND book_id = ?"
            params.append(book_id)
        rows = self.conn.execute(
            f"SELECT chunk_id, text FROM chunks {where} ORDER BY book_id, chapter_index, position",
            params,
        ).fetchall()
        if chunk_ids is not None:
            wanted = set(chunk_ids)
            rows = [row for row in rows if row["chunk_id"] in wanted]
        if not rows:
            return {
                "model": backend.model,
                "kind": backend.kind,
                "dim": backend.dim,
                "embedded": 0,
                "skipped": 0,
                "total": 0,
                "fallback": False,
            }
        existing = set()
        if not force:
            existing = {
                row["chunk_id"]
                for row in self.conn.execute(
                    "SELECT chunk_id FROM chunk_embeddings WHERE model = ?",
                    (backend.model,),
                ).fetchall()
            }
        pending = [(row["chunk_id"], row["text"]) for row in rows if row["chunk_id"] not in existing]
        vectors: dict[str, list[float]] = {}
        fallback = False
        fallback_error = ""
        if pending:
            try:
                embedded = embed_texts([text for _, text in pending], backend)
            except Exception as exc:
                # Never mix vectors from two model spaces. If a remote backend
                # fails, re-embed the pending rows with the local model and use
                # that model name from here on.
                restarted = get_embedder(allow_remote=False)
                embedded = embed_texts([text for _, text in pending], restarted)
                backend = restarted
                fallback = True
                fallback_error = f"{type(exc).__name__}: {exc}"
            vectors = {chunk_id: vector for (chunk_id, _), vector in zip(pending, embedded)}
            self.save_embeddings(vectors, backend.model, backend.dim)
        result = {
            "model": backend.model,
            "kind": backend.kind,
            "dim": backend.dim,
            "embedded": len(vectors),
            "skipped": len(rows) - len(pending),
            "total": len(rows),
            "fallback": fallback,
        }
        if fallback_error:
            result["fallback_error"] = fallback_error
        return result

    # ---- cross-book entities -------------------------------------------
    def replace_entity_graph(
        self,
        entities: list[dict[str, Any]],
        mentions: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> None:
        self.conn.execute("DELETE FROM entity_relations")
        self.conn.execute("DELETE FROM entity_mentions")
        self.conn.execute("DELETE FROM entities")
        for entity in entities:
            self.conn.execute(
                "INSERT INTO entities (entity_id, canonical_name, entity_type, aliases, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    entity["entity_id"],
                    entity["canonical_name"],
                    entity.get("entity_type", "concept"),
                    _json(entity.get("aliases", [])),
                    entity.get("summary", ""),
                    utc_now(),
                ),
            )
        for mention in mentions:
            self.conn.execute(
                "INSERT OR IGNORE INTO entity_mentions (entity_id, chunk_id, book_id, surface, confidence) VALUES (?, ?, ?, ?, ?)",
                (
                    mention["entity_id"],
                    mention["chunk_id"],
                    mention["book_id"],
                    mention["surface"],
                    float(mention.get("confidence", 1.0)),
                ),
            )
        for relation in relations:
            self.conn.execute(
                "INSERT OR REPLACE INTO entity_relations (src_entity_id, dst_entity_id, relation, weight, evidence, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    relation["src_entity_id"],
                    relation["dst_entity_id"],
                    relation.get("relation", "co_occurs"),
                    float(relation.get("weight", 1.0)),
                    _json(relation.get("evidence", [])),
                    utc_now(),
                ),
            )
        self.conn.commit()

    def list_entities(self, query: str = "", cross_book_only: bool = False, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM entities ORDER BY canonical_name").fetchall()
        result: list[dict[str, Any]] = []
        needle = query.strip().lower()
        for row in rows:
            item = dict(row)
            item["aliases"] = _loads(item.get("aliases"), [])
            stats = self.conn.execute(
                "SELECT COUNT(*) AS mentions, COUNT(DISTINCT book_id) AS books FROM entity_mentions WHERE entity_id = ?",
                (item["entity_id"],),
            ).fetchone()
            item["mentions"] = stats["mentions"]
            item["book_count"] = stats["books"]
            if cross_book_only and item["book_count"] < 2:
                continue
            if needle:
                haystack = " ".join([item["canonical_name"], *item.get("aliases", [])]).lower()
                if needle not in haystack:
                    continue
            result.append(item)
        result.sort(key=lambda item: (-item["book_count"], -item["mentions"], item["canonical_name"]))
        return result[:limit]

    def get_entity(self, entity_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM entities WHERE entity_id = ?", (entity_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["aliases"] = _loads(item.get("aliases"), [])
        mentions = self.conn.execute(
            "SELECT m.*, b.title AS book_title, c.chapter_title, c.page_start, c.position, c.text "
            "FROM entity_mentions m JOIN books b ON b.book_id = m.book_id JOIN chunks c ON c.chunk_id = m.chunk_id "
            "WHERE m.entity_id = ? ORDER BY b.title, c.chapter_index, c.position",
            (entity_id,),
        ).fetchall()
        item["mentions"] = [dict(mention) for mention in mentions]
        item["book_count"] = len({mention["book_id"] for mention in mentions})
        relations = self.conn.execute(
            "SELECT * FROM entity_relations WHERE src_entity_id = ? OR dst_entity_id = ? ORDER BY weight DESC",
            (entity_id, entity_id),
        ).fetchall()
        item["relations"] = []
        for relation in relations:
            rel = dict(relation)
            rel["evidence"] = _loads(rel.get("evidence"), [])
            other_id = rel["dst_entity_id"] if rel["src_entity_id"] == entity_id else rel["src_entity_id"]
            other = self.conn.execute("SELECT canonical_name FROM entities WHERE entity_id = ?", (other_id,)).fetchone()
            rel["other_name"] = other["canonical_name"] if other else other_id
            item["relations"].append(rel)
        return item

    def entity_stats(self) -> dict[str, Any]:
        entities = self.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        mentions = self.conn.execute("SELECT COUNT(*) FROM entity_mentions").fetchone()[0]
        relations = self.conn.execute("SELECT COUNT(*) FROM entity_relations").fetchone()[0]
        cross_book = self.conn.execute(
            "SELECT COUNT(*) FROM (SELECT entity_id FROM entity_mentions GROUP BY entity_id HAVING COUNT(DISTINCT book_id) >= 2)"
        ).fetchone()[0]
        try:
            from .entities import ALIAS_GROUPS

            alias_groups = len(ALIAS_GROUPS)
        except Exception:
            alias_groups = 0
        return {
            "entities": entities,
            "cross_book_entities": cross_book,
            "mentions": mentions,
            "relations": relations,
            "alias_groups": alias_groups,
        }

    def entity_chunk_ids(self, entity_ids: list[str]) -> set[str]:
        if not entity_ids:
            return set()
        placeholders = ",".join("?" for _ in entity_ids)
        rows = self.conn.execute(
            f"SELECT DISTINCT chunk_id FROM entity_mentions WHERE entity_id IN ({placeholders})",
            entity_ids,
        ).fetchall()
        return {row["chunk_id"] for row in rows}

    # ---- evolution state ------------------------------------------------
    def get_state(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value FROM evolution_state WHERE key = ?", (key,)).fetchone()
        return _loads(row["value"], default) if row else default

    def set_state(self, key: str, value: Any) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO evolution_state (key, value, updated_at) VALUES (?, ?, ?)",
            (key, _json(value), utc_now()),
        )
        self.conn.commit()

    def record_evolution_run(self, proposal_id: str, mode: str, metrics: dict[str, Any], snapshot: dict[str, Any]) -> str:
        run_id = stable_id("run", proposal_id, utc_now())
        self.conn.execute(
            "INSERT INTO evolution_runs (run_id, proposal_id, mode, metrics, snapshot, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, proposal_id, mode, _json(metrics), _json(snapshot), utc_now()),
        )
        self.conn.commit()
        return run_id

    # ---- claims ---------------------------------------------------------
    def replace_claims(self, book_id: str, claims: list[dict[str, Any]]) -> int:
        """Replace auto-extracted claims without destroying human review.

        Claims that were superseded/retracted, or that carry a resolution note
        from a reviewer, are kept across rebuilds.  Only unreviewed
        active/conflicted claims are replaced.  Relations and evidence attached
        to preserved claims therefore survive too.
        """
        now = utc_now()
        preserved_rows = self.conn.execute(
            "SELECT claim_id FROM claims WHERE book_id = ? AND "
            "(status NOT IN ('active', 'conflicted') OR TRIM(COALESCE(resolution, '')) <> '')",
            (book_id,),
        ).fetchall()
        preserved_ids = {row["claim_id"] for row in preserved_rows}
        self.conn.execute(
            "DELETE FROM claims WHERE book_id = ? AND status IN ('active', 'conflicted') "
            "AND TRIM(COALESCE(resolution, '')) = ''",
            (book_id,),
        )
        count = 0
        for claim in claims:
            if claim.get("claim_id") in preserved_ids:
                continue
            self.conn.execute(
                "INSERT OR REPLACE INTO claims (claim_id, claim_key, base_key, subject, subject_entity_id, "
                "predicate, object, polarity, conditions, book_id, chunk_id, page, quote, valid_from, valid_to, "
                "status, resolution, confidence, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim["claim_id"], claim["claim_key"], claim["base_key"], claim["subject"],
                    claim.get("subject_entity_id", ""), claim["predicate"], claim["object"],
                    int(claim.get("polarity", 1)), _json(claim.get("conditions", [])), book_id,
                    claim["chunk_id"], claim.get("page"), claim["quote"], claim.get("valid_from"),
                    claim.get("valid_to"), claim.get("status", "active"), claim.get("resolution", ""),
                    float(claim.get("confidence", 0.5)), now, now,
                ),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO claim_evidence (claim_id, chunk_id, book_id, quote, page) VALUES (?, ?, ?, ?, ?)",
                (claim["claim_id"], claim["chunk_id"], book_id, claim["quote"], claim.get("page")),
            )
            count += 1
        self.conn.commit()
        return count

    def add_claim_relation(self, src_claim_id: str, dst_claim_id: str, relation: str, confidence: float = 0.6, note: str = "") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO claim_relations (src_claim_id, dst_claim_id, relation, confidence, note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (src_claim_id, dst_claim_id, relation, float(confidence), note, utc_now()),
        )
        self.conn.commit()

    def set_claim_status(self, claim_id: str, status: str, resolution: str = "", valid_to: str | None = None) -> dict[str, Any] | None:
        self.conn.execute(
            "UPDATE claims SET status = ?, resolution = ?, valid_to = COALESCE(?, valid_to), updated_at = ? WHERE claim_id = ?",
            (status, resolution, valid_to, utc_now(), claim_id),
        )
        self.conn.commit()
        return self.get_claim(claim_id)

    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT c.*, b.title AS book_title FROM claims c JOIN books b ON b.book_id = c.book_id WHERE c.claim_id = ?",
            (claim_id,),
        ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["conditions"] = _loads(item.get("conditions"), [])
        item["evidence"] = [
            dict(evidence) for evidence in self.conn.execute(
                "SELECT e.*, b.title AS book_title FROM claim_evidence e JOIN books b ON b.book_id = e.book_id "
                "WHERE e.claim_id = ? ORDER BY e.page",
                (claim_id,),
            ).fetchall()
        ]
        relations = self.conn.execute(
            "SELECT r.*, s.subject AS src_subject, s.predicate AS src_predicate, d.subject AS dst_subject, d.predicate AS dst_predicate "
            "FROM claim_relations r JOIN claims s ON s.claim_id = r.src_claim_id JOIN claims d ON d.claim_id = r.dst_claim_id "
            "WHERE r.src_claim_id = ? OR r.dst_claim_id = ? ORDER BY r.relation",
            (claim_id, claim_id),
        ).fetchall()
        item["relations"] = [dict(relation) for relation in relations]
        return item

    def list_claims(self, query: str = "", book_id: str = "", status: str = "", limit: int = 200) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ["1=1"]
        if book_id:
            where.append("c.book_id = ?")
            params.append(book_id)
        if status:
            where.append("c.status = ?")
            params.append(status)
        if query.strip():
            where.append("(c.subject LIKE ? OR c.object LIKE ? OR c.quote LIKE ?)")
            needle = f"%{query.strip()}%"
            params.extend([needle, needle, needle])
        params.append(max(1, int(limit)))
        rows = self.conn.execute(
            "SELECT c.*, b.title AS book_title FROM claims c JOIN books b ON b.book_id = c.book_id "
            f"WHERE {' AND '.join(where)} ORDER BY c.status = 'conflicted' DESC, c.created_at DESC, c.page LIMIT ?",
            params,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["conditions"] = _loads(item.get("conditions"), [])
            result.append(item)
        return result

    def search_claims(
        self,
        query: str,
        book_ids: list[str] | None = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Lexically recall claims relevant to a question.

        This is deliberately simple and local: 640 claims do not justify a
        second vector index.  Terms come from the same Chinese bigram/trigram
        tokenizer used by retrieval, and superseded/retracted claims are
        excluded so the analysis packet never treats an old claim as current.
        """
        terms = query_terms(query)
        if not terms:
            return []
        params: list[Any] = []
        where = ["c.status NOT IN ('superseded', 'retracted')"]
        if book_ids:
            placeholders = ",".join("?" for _ in book_ids)
            where.append(f"c.book_id IN ({placeholders})")
            params.extend(book_ids)
        rows = self.conn.execute(
            "SELECT c.*, b.title AS book_title, ch.chapter_title AS chapter_title "
            "FROM claims c JOIN books b ON b.book_id = c.book_id "
            "JOIN chunks ch ON ch.chunk_id = c.chunk_id "
            f"WHERE {' AND '.join(where)}",
            params,
        ).fetchall()
        noise_markers = ("授课教师", "签字", "盖章", "ISBN", "版权所有", "定价", "习题", "思考题")
        scored: list[tuple[float, dict[str, Any]]] = []
        lowered_terms = [term.lower() for term in terms]
        for row in rows:
            item = dict(row)
            haystack = " ".join(
                str(item.get(key, "")) for key in ("subject", "predicate", "object", "quote")
            ).lower()
            score = 0.0
            for term in lowered_terms:
                count = haystack.count(term)
                if count:
                    score += min(count, 3)
            if score <= 0:
                continue
            if item.get("subject_entity_id"):
                score += 1.0
            if item.get("status") == "conflicted":
                score += 0.3
            if any(marker in str(item.get("quote", "")) for marker in noise_markers):
                score *= 0.25
                item["quality_warning"] = "boilerplate/table text"
            if score < 1.0:
                continue
            item["score"] = round(score, 4)
            item["conditions"] = _loads(item.get("conditions"), [])
            scored.append((score, item))
        scored.sort(
            key=lambda pair: (
                -pair[0],
                -float(pair[1].get("confidence", 0.0)),
                str(pair[1].get("book_id", "")),
                int(pair[1].get("page") or 0),
            )
        )
        return [item for _, item in scored[: max(1, int(limit))]]

    def get_claim_conflicts(
        self,
        book_ids: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return reviewed or auto-detected claim contradictions/supersessions."""
        params: list[Any] = []
        where = [
            "r.relation IN ('contradicts', 'supersedes')",
            # A superseded/retracted claim is historical.  It may still be
            # useful in a dedicated history view, but it must not surface as a
            # live conflict in a new analysis.
            "s.status NOT IN ('superseded', 'retracted')",
            "d.status NOT IN ('superseded', 'retracted')",
        ]
        if book_ids:
            placeholders = ",".join("?" for _ in book_ids)
            where.append(f"(s.book_id IN ({placeholders}) OR d.book_id IN ({placeholders}))")
            params.extend(book_ids)
            params.extend(book_ids)
        params.append(max(1, int(limit)))
        rows = self.conn.execute(
            "SELECT r.relation, r.confidence, r.note, "
            "s.claim_id AS src_claim_id, s.subject AS src_subject, s.predicate AS src_predicate, "
            "s.object AS src_object, s.polarity AS src_polarity, s.book_id AS src_book_id, "
            "s.quote AS src_quote, s.page AS src_page, sb.title AS src_book_title, "
            "d.claim_id AS dst_claim_id, d.subject AS dst_subject, d.predicate AS dst_predicate, "
            "d.object AS dst_object, d.polarity AS dst_polarity, d.book_id AS dst_book_id, "
            "d.quote AS dst_quote, d.page AS dst_page, dbk.title AS dst_book_title "
            "FROM claim_relations r "
            "JOIN claims s ON s.claim_id = r.src_claim_id "
            "JOIN claims d ON d.claim_id = r.dst_claim_id "
            "JOIN books sb ON sb.book_id = s.book_id "
            "JOIN books dbk ON dbk.book_id = d.book_id "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY r.confidence DESC, r.relation LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def claim_stats(self) -> dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        by_status = {
            row["status"]: row["count"]
            for row in self.conn.execute("SELECT status, COUNT(*) AS count FROM claims GROUP BY status").fetchall()
        }
        conflicts = self.conn.execute("SELECT COUNT(*) FROM claim_relations WHERE relation = 'contradicts'").fetchone()[0]
        books = self.conn.execute("SELECT COUNT(DISTINCT book_id) FROM claims").fetchone()[0]
        pending_merges = self.conn.execute(
            "SELECT COUNT(*) FROM entity_merge_candidates WHERE status = 'pending'"
        ).fetchone()[0]
        return {
            "claims": total,
            "books_with_claims": books,
            "by_status": by_status,
            "contradicts_relations": conflicts,
            "pending_entity_merges": pending_merges,
        }

    # ---- entity merge review queue -------------------------------------
    def upsert_entity_merge_candidates(self, candidates: list[dict[str, Any]]) -> int:
        now = utc_now()
        count = 0
        for candidate in candidates:
            left = candidate.get("left", {})
            right = candidate.get("right", {})
            left_id = str(left.get("entity_id", ""))
            right_id = str(right.get("entity_id", ""))
            if not left_id or not right_id:
                continue
            # Canonical ordering prevents A/B and B/A duplicates.
            if left_id > right_id:
                left, right = right, left
                left_id, right_id = right_id, left_id
            candidate_id = stable_id("merge", left_id, right_id)
            self.conn.execute(
                "INSERT INTO entity_merge_candidates (candidate_id, left_id, right_id, left_name, right_name, similarity, "
                "reason, shared_books, status, decision_note, snapshot, created_at, decided_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', '{}', ?, '') "
                "ON CONFLICT(candidate_id) DO UPDATE SET similarity = excluded.similarity, reason = excluded.reason, "
                "shared_books = excluded.shared_books, left_name = excluded.left_name, right_name = excluded.right_name",
                (
                    candidate_id, left_id, right_id, str(left.get("canonical_name", "")),
                    str(right.get("canonical_name", "")), float(candidate.get("similarity", 0.0)),
                    str(candidate.get("reason", "")), _json(candidate.get("shared_books", [])), now,
                ),
            )
            count += 1
        self.conn.commit()
        return count

    def list_entity_merge_candidates(self, status: str = "", limit: int = 200) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ""
        if status:
            where = "WHERE status = ?"
            params.append(status)
        params.append(max(1, int(limit)))
        rows = self.conn.execute(
            f"SELECT * FROM entity_merge_candidates {where} ORDER BY status = 'pending' DESC, similarity DESC LIMIT ?",
            params,
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["shared_books"] = _loads(item.get("shared_books"), [])
            item["snapshot"] = _loads(item.get("snapshot"), {})
            result.append(item)
        return result

    def get_entity_merge_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM entity_merge_candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["shared_books"] = _loads(item.get("shared_books"), [])
        item["snapshot"] = _loads(item.get("snapshot"), {})
        return item

    def set_entity_merge_candidate(self, candidate_id: str, status: str, note: str = "", snapshot: dict[str, Any] | None = None) -> dict[str, Any] | None:
        self.conn.execute(
            "UPDATE entity_merge_candidates SET status = ?, decision_note = ?, snapshot = COALESCE(?, snapshot), decided_at = ? "
            "WHERE candidate_id = ?",
            (status, note, _json(snapshot) if snapshot is not None else None, utc_now(), candidate_id),
        )
        self.conn.commit()
        return self.get_entity_merge_candidate(candidate_id)

    def coverage(self) -> dict[str, Any]:
        books = self.list_books()
        frameworks = self.list_frameworks()
        disciplines: dict[str, int] = {}
        lenses: dict[str, int] = {}
        for book in books:
            for discipline in book.get("disciplines", []):
                disciplines[discipline] = disciplines.get(discipline, 0) + 1
        for framework in frameworks:
            for lens in framework.get("lenses", []):
                lenses[lens] = lenses.get(lens, 0) + 1
        return {
            "books": len(books),
            "frameworks": len(frameworks),
            "disciplines": disciplines,
            "lenses": lenses,
            "compiled_books": sum(1 for book in books if book.get("status") == "compiled"),
            "analyses": len(self.list_analyses()),
            "feedback": len(self.list_feedback()),
            "reading_evaluations": len(self.list_reading_evaluations(limit=100000)),
            "evolution_proposals": len(self.list_evolution_proposals()),
        }