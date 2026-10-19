"""Lightweight, deterministic GraphRAG sidecar for BookCompiler.

This is deliberately *not* an LLM-extracted Microsoft-style graph.  It reuses
the entities, claims, mentions, relations, frameworks, and chunks that the
library already stores, materialises them into a separate SQLite sidecar, and
adds deterministic communities plus a weighted 2-hop traversal.  The main
library database is never modified by graph builds.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .entities import detect_entities
from .retrieval import hybrid_search
from .store import Store

GRAPH_RELATIONS_FOR_COMMUNITIES = {"related_to", "co_mentions", "same_as", "part_of", "causes"}
DEFAULT_RRF_K = 60
DEFAULT_GRAPH_WEIGHT = 0.9


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _clip(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def graph_path_for(store: Store) -> Path:
    return Path(store.db_path).resolve().with_suffix(".graph.db")


def source_fingerprint(store: Store) -> str:
    """Fingerprint only source facts that affect the graph."""

    def scalar(sql: str) -> Any:
        try:
            return store.conn.execute(sql).fetchone()[0]
        except Exception:
            return 0

    payload = {
        "books": scalar("SELECT COUNT(*) FROM books"),
        "book_max": scalar("SELECT COALESCE(MAX(rowid), 0) FROM books"),
        "chunks": scalar("SELECT COUNT(*) FROM chunks"),
        "chunk_max": scalar("SELECT COALESCE(MAX(rowid), 0) FROM chunks"),
        "frameworks": scalar("SELECT COUNT(*) FROM frameworks"),
        "claims": scalar("SELECT COUNT(*) FROM claims"),
        "entities": scalar("SELECT COUNT(*) FROM entities"),
        "mentions": scalar("SELECT COUNT(*) FROM entity_mentions"),
        "entity_relations": scalar("SELECT COUNT(*) FROM entity_relations"),
        "claim_relations": scalar("SELECT COUNT(*) FROM claim_relations"),
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


class GraphStore:
    def __init__(self, path: str | Path, source_db: str | Path) -> None:
        self.path = Path(path)
        self.source_db = Path(source_db).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                node_type TEXT NOT NULL,
                label TEXT NOT NULL,
                book_id TEXT NOT NULL DEFAULT '',
                ref_id TEXT NOT NULL DEFAULT '',
                data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
            CREATE INDEX IF NOT EXISTS idx_nodes_book ON nodes(book_id);
            CREATE TABLE IF NOT EXISTS edges (
                src_id TEXT NOT NULL,
                dst_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                book_id TEXT NOT NULL DEFAULT '',
                data TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY (src_id, dst_id, relation)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
            CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
            CREATE TABLE IF NOT EXISTS communities (
                community_id INTEGER PRIMARY KEY,
                label TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '{}',
                size INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS community_members (
                community_id INTEGER NOT NULL,
                node_id TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                PRIMARY KEY (community_id, node_id)
            );
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def clear(self) -> None:
        self.conn.executescript(
            "DELETE FROM community_members; DELETE FROM communities; DELETE FROM edges; DELETE FROM nodes; DELETE FROM meta;"
        )
        self.conn.commit()

    def meta(self) -> dict[str, Any]:
        return {row["key"]: _loads(row["value"], row["value"]) for row in self.conn.execute("SELECT * FROM meta")}

    def set_meta(self, key: str, value: Any) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, _json(value)))
        self.conn.commit()

    def build(self, store: Store) -> dict[str, Any]:
        started = _now()
        self.clear()
        nodes: dict[str, tuple[str, str, str, str, str, str, str]] = {}
        edges: dict[tuple[str, str, str], tuple[str, str, str, float, str, str, str]] = {}

        def add_node(node_id: str, node_type: str, label: str, book_id: str = "", ref_id: str = "", data: Any = None) -> None:
            nodes.setdefault(
                node_id,
                (node_id, node_type, _clip(label, 240), book_id or "", ref_id or "", _json(data or {}), started),
            )

        def add_edge(src: str, dst: str, relation: str, weight: float = 1.0, book_id: str = "", data: Any = None) -> None:
            if not src or not dst or src == dst:
                return
            key = (src, dst, relation)
            if key not in edges:
                edges[key] = (src, dst, relation, float(max(0.0, weight)), book_id or "", _json(data or {}), started)

        books = store.list_books()
        book_titles: dict[str, str] = {}
        for book in books:
            book_id = book["book_id"]
            book_titles[book_id] = book["title"]
            add_node(
                f"book:{book_id}", "book", book["title"], book_id, book_id,
                {"author": book.get("author", ""), "disciplines": book.get("disciplines", []), "status": book.get("status", "")},
            )

        frameworks = store.list_frameworks()
        framework_text: dict[str, str] = {}
        for framework in frameworks:
            framework_id = framework.get("framework_id", "")
            if not framework_id:
                continue
            node_id = f"framework:{framework_id}"
            book_id = framework.get("book_id", "")
            add_node(
                node_id, "framework", framework.get("name", ""), book_id, framework_id,
                {
                    "one_liner": framework.get("one_liner", ""),
                    "lenses": framework.get("lenses", []),
                    "applicable_when": framework.get("applicable_when", []),
                    "failure_modes": framework.get("failure_modes", []),
                },
            )
            if book_id:
                add_edge(f"book:{book_id}", node_id, "has_framework", 1.0, book_id)
            framework_text[node_id] = " ".join(
                str(value or "")
                for value in (
                    framework.get("name", ""),
                    framework.get("one_liner", ""),
                    " ".join(map(str, framework.get("steps", []) or [])),
                    " ".join(map(str, framework.get("applicable_when", []) or [])),
                )
            )

        claims = store.list_claims(limit=1000000)
        for claim in claims:
            claim_id = claim.get("claim_id", "")
            if not claim_id:
                continue
            node_id = f"claim:{claim_id}"
            book_id = claim.get("book_id", "")
            label = f"{claim.get('subject', '')} {claim.get('predicate', '')} {claim.get('object', '')}".strip()
            add_node(
                node_id, "claim", label, book_id, claim_id,
                {
                    "quote": claim.get("quote", ""),
                    "page": claim.get("page"),
                    "chunk_id": claim.get("chunk_id", ""),
                    "status": claim.get("status", ""),
                    "confidence": claim.get("confidence"),
                    "subject_entity_id": claim.get("subject_entity_id", ""),
                },
            )
            if claim.get("chunk_id"):
                add_edge(node_id, f"chunk:{claim['chunk_id']}", "supported_by", 1.0, book_id)

        entities = store.list_entities(limit=1000000)
        entity_name_map: dict[str, str] = {}
        entity_names: dict[str, str] = {}
        entity_types: dict[str, str] = {}
        for row in store.conn.execute("SELECT entity_id, canonical_name, aliases, entity_type FROM entities").fetchall():
            entity_id = row["entity_id"]
            aliases = _loads(row["aliases"], [])
            entity_names[entity_id] = row["canonical_name"]
            entity_types[entity_id] = row["entity_type"]
            for name in [row["canonical_name"], *aliases]:
                normalized = str(name or "").strip().lower()
                if normalized:
                    entity_name_map[normalized] = entity_id
            add_node(
                f"entity:{entity_id}", "entity", row["canonical_name"], "", entity_id,
                {"aliases": aliases, "entity_type": row["entity_type"]},
            )
        for entity in entities:
            entity_id = entity.get("entity_id", "")
            if entity_id and f"entity:{entity_id}" not in nodes:
                add_node(f"entity:{entity_id}", "entity", entity.get("canonical_name", ""), "", entity_id, entity)

        chunk_count = 0
        chunk_book: dict[str, str] = {}
        for row in store.conn.execute(
            "SELECT chunk_id, book_id, chapter_title, position, page_start, text FROM chunks"
        ).fetchall():
            node_id = f"chunk:{row['chunk_id']}"
            chunk_count += 1
            chunk_book[row["chunk_id"]] = row["book_id"]
            book_title = book_titles.get(row["book_id"], row["book_id"])
            add_node(
                node_id, "chunk", f"{book_title} / {row['chapter_title']} / p.{row['page_start'] or ''}",
                row["book_id"], row["chunk_id"],
                {
                    "chapter_title": row["chapter_title"],
                    "position": row["position"],
                    "page_start": row["page_start"],
                    "text": row["text"],
                },
            )
            add_edge(f"book:{row['book_id']}", node_id, "has_chunk", 0.5, row["book_id"])

        mentions_by_chunk: dict[str, list[str]] = defaultdict(list)
        for row in store.conn.execute("SELECT entity_id, chunk_id, book_id, surface, confidence FROM entity_mentions").fetchall():
            add_edge(
                f"chunk:{row['chunk_id']}", f"entity:{row['entity_id']}", "mentions",
                float(row["confidence"] or 0.8), row["book_id"], {"surface": row["surface"]},
            )
            if len(mentions_by_chunk[row["chunk_id"]]) < 8:
                mentions_by_chunk[row["chunk_id"]].append(row["entity_id"])

        # Co-mention edges are the only inferred edges used for communities.
        # They are deterministic and capped per chunk to avoid a quadratic blow-up.
        for chunk_id, entity_ids in mentions_by_chunk.items():
            unique_ids = sorted(set(entity_ids))
            for index, left in enumerate(unique_ids):
                for right in unique_ids[index + 1:]:
                    add_edge(
                        f"entity:{left}", f"entity:{right}", "co_mentions", 0.35,
                        chunk_book.get(chunk_id, ""), {"chunk_id": chunk_id},
                    )

        for claim in claims:
            claim_id = claim.get("claim_id", "")
            if not claim_id:
                continue
            claim_node = f"claim:{claim_id}"
            subject_id = claim.get("subject_entity_id", "")
            if subject_id:
                add_edge(claim_node, f"entity:{subject_id}", "about_subject", 1.0, claim.get("book_id", ""))
            object_text = str(claim.get("object", "") or "").strip().lower()
            object_id = entity_name_map.get(object_text, "")
            if not object_id and object_text:
                for name, candidate in entity_name_map.items():
                    if len(name) >= 2 and name in object_text:
                        object_id = candidate
                        break
            if object_id:
                add_edge(claim_node, f"entity:{object_id}", "about_object", 0.8, claim.get("book_id", ""))

        for row in store.conn.execute("SELECT src_claim_id, dst_claim_id, relation, confidence, note FROM claim_relations"):
            add_edge(
                f"claim:{row['src_claim_id']}", f"claim:{row['dst_claim_id']}", row["relation"],
                float(row["confidence"] or 0.5), "", {"note": row["note"]},
            )

        for row in store.conn.execute("SELECT src_entity_id, dst_entity_id, relation, weight, evidence FROM entity_relations"):
            add_edge(
                f"entity:{row['src_entity_id']}", f"entity:{row['dst_entity_id']}", row["relation"],
                float(row["weight"] or 0.5), "", {"evidence": _loads(row["evidence"], [])},
            )

        # Conservative framework -> entity links. Only exact substring matches
        # of existing canonical names/aliases are allowed; no fuzzy inference.
        candidates = [
            (name, entity_id)
            for name, entity_id in entity_name_map.items()
            if 2 <= len(name) <= 30
        ]
        for framework_node, text in framework_text.items():
            lowered = text.lower()
            matched: set[str] = set()
            for name, entity_id in candidates:
                if name in lowered:
                    matched.add(entity_id)
                    if len(matched) >= 12:
                        break
            for entity_id in sorted(matched):
                add_edge(framework_node, f"entity:{entity_id}", "about", 0.6, "", {"match": "substring"})

        self.conn.executemany(
            "INSERT OR REPLACE INTO nodes (node_id, node_type, label, book_id, ref_id, data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            list(nodes.values()),
        )
        self.conn.executemany(
            "INSERT OR REPLACE INTO edges (src_id, dst_id, relation, weight, book_id, data, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            list(edges.values()),
        )
        self.conn.commit()

        communities = self._build_communities()
        stats = {
            "path": str(self.path),
            "source_db": str(self.source_db),
            "built_at": started,
            "source_fingerprint": source_fingerprint(store),
            "nodes": len(nodes),
            "edges": len(edges),
            "communities": communities,
            "chunks": chunk_count,
            "books": len(books),
            "frameworks": len(frameworks),
            "claims": len(claims),
            "entities": len(entities),
            "mentions": sum(1 for edge in edges.values() if edge[2] == "mentions"),
        }
        self.set_meta("status", stats)
        return stats

    def _build_communities(self, max_rounds: int = 8) -> int:
        """Build deterministic, book-scoped entity communities.

        Label propagation over a dense co-mention graph tends to collapse into
        one giant component, which is useless for retrieval.  Instead we use
        two auditable groupings: entities co-mentioned in the same book, and a
        cross-book bridge community for entities that appear in two or more
        books.  Communities are context maps, not claims about causality.
        """
        mentions: dict[str, set[str]] = defaultdict(set)
        books_by_entity: dict[str, set[str]] = defaultdict(set)
        for row in self.conn.execute(
            "SELECT e.dst_id AS entity_node, e.book_id FROM edges e "
            "WHERE e.relation = 'mentions' AND e.book_id != ''"
        ).fetchall():
            mentions[row["book_id"]].add(row["entity_node"])
            books_by_entity[row["entity_node"]].add(row["book_id"])

        self.conn.execute("DELETE FROM community_members")
        self.conn.execute("DELETE FROM communities")
        community_count = 0

        def add_community(label: str, members: list[str], summary: dict[str, Any]) -> None:
            nonlocal community_count
            members = sorted(set(members))
            if len(members) < 2:
                return
            community_count += 1
            self.conn.execute(
                "INSERT INTO communities (community_id, label, summary, size, created_at) VALUES (?, ?, ?, ?, ?)",
                (community_count, label, _json(summary), len(members), _now()),
            )
            self.conn.executemany(
                "INSERT OR REPLACE INTO community_members (community_id, node_id, weight) VALUES (?, ?, ?)",
                [(community_count, member, 1.0) for member in members],
            )

        for book_id in sorted(mentions):
            entity_nodes = sorted(mentions[book_id])
            if len(entity_nodes) < 2:
                continue
            book_label = self._node_label(f"book:{book_id}")
            names = [self._node_label(node) for node in entity_nodes[:20]]
            claims = []
            for entity_node in entity_nodes[:12]:
                for row in self.conn.execute(
                    "SELECT src_id FROM edges WHERE dst_id = ? AND relation IN ('about_subject','about_object') LIMIT 2",
                    (entity_node,),
                ).fetchall():
                    label = self._node_label(row["src_id"])
                    if label not in claims:
                        claims.append(label)
            add_community(
                f"{book_label} / entities",
                entity_nodes,
                {
                    "kind": "book_scope",
                    "book_id": book_id,
                    "book": book_label,
                    "entities": names,
                    "books": [book_id],
                    "book_count": 1,
                    "representative_claims": claims[:5],
                },
            )

        bridge_nodes = sorted(node for node, books in books_by_entity.items() if len(books) >= 2)
        if len(bridge_nodes) >= 2:
            bridge_books = sorted({book for node in bridge_nodes for book in books_by_entity[node]})
            add_community(
                "Cross-book bridge entities",
                bridge_nodes,
                {
                    "kind": "cross_book_bridge",
                    "entities": [self._node_label(node) for node in bridge_nodes[:30]],
                    "books": bridge_books,
                    "book_count": len(bridge_books),
                    "representative_claims": [],
                },
            )
        self.conn.commit()
        return community_count

    def _node_label(self, node_id: str) -> str:
        row = self.conn.execute("SELECT label FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
        return row["label"] if row else node_id

    def _community_summary(self, members: list[str], book_ids: set[str], claim_rows: Iterable[Any]) -> dict[str, Any]:
        names = [self._node_label(member) for member in members]
        claims = []
        for member in members[:12]:
            for row in self.conn.execute(
                "SELECT src_id FROM edges WHERE dst_id = ? AND relation IN ('about_subject','about_object') LIMIT 2",
                (member,),
            ).fetchall():
                label = self._node_label(row["src_id"])
                if label and label not in claims:
                    claims.append(label)
        return {
            "label": " / ".join(names[:3]) or "entity community",
            "entities": names,
            "books": sorted(book_ids),
            "book_count": len(book_ids),
            "representative_claims": claims[:5],
        }


def _graph_store(store: Store) -> GraphStore:
    return GraphStore(graph_path_for(store), store.db_path)


def graph_available(store: Store) -> bool:
    path = graph_path_for(store)
    if not path.exists():
        return False
    try:
        conn = sqlite3.connect(str(path))
        try:
            count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        finally:
            conn.close()
        return int(count) > 0
    except Exception:
        return False


def build_graph(store: Store) -> dict[str, Any]:
    graph = _graph_store(store)
    try:
        return graph.build(store)
    finally:
        graph.close()


def graph_status(store: Store) -> dict[str, Any]:
    path = graph_path_for(store)
    if not path.exists():
        return {
            "available": False,
            "path": str(path),
            "stale": True,
            "reason": "graph sidecar has not been built",
            "source_fingerprint": source_fingerprint(store),
        }
    graph = _graph_store(store)
    try:
        status = graph.meta().get("status", {})
        current = source_fingerprint(store)
        return {
            "available": True,
            "path": str(path),
            "stale": status.get("source_fingerprint") != current,
            "source_fingerprint": current,
            "graph_fingerprint": status.get("source_fingerprint"),
            **{key: status.get(key) for key in ("nodes", "edges", "communities", "chunks", "books", "frameworks", "claims", "entities", "built_at")},
        }
    except Exception as exc:
        return {"available": False, "path": str(path), "stale": True, "error": str(exc)}
    finally:
        graph.close()


def ensure_graph(store: Store, rebuild_stale: bool = True) -> dict[str, Any]:
    status = graph_status(store)
    if not status.get("available") or (rebuild_stale and status.get("stale")):
        return build_graph(store)
    return status


def _load_nodes(graph: GraphStore) -> dict[str, dict[str, Any]]:
    return {
        row["node_id"]: {
            "node_id": row["node_id"],
            "node_type": row["node_type"],
            "label": row["label"],
            "book_id": row["book_id"],
            "ref_id": row["ref_id"],
            "data": _loads(row["data"], {}),
        }
        for row in graph.conn.execute("SELECT * FROM nodes")
    }


def _load_edges(graph: GraphStore) -> list[dict[str, Any]]:
    return [
        {
            "src": row["src_id"],
            "dst": row["dst_id"],
            "relation": row["relation"],
            "weight": float(row["weight"] or 0.0),
            "book_id": row["book_id"],
        }
        for row in graph.conn.execute("SELECT * FROM edges")
    ]


_CJK_STOP_BIGRAMS = {
    "什么", "怎么", "如何", "为何", "是否", "以及", "之间", "关系", "问题", "可以",
    "需要", "我们", "他们", "这个", "那个", "这些", "那些", "一个", "进行", "通过",
    "对于", "关于", "还是", "或者", "因为", "所以", "但是", "如果", "就是", "不是",
    "没有", "已经", "可能", "应该", "它的", "其中", "这种", "那样", "一下", "哪些",
}


def _cjk_ngrams(text: str, sizes: tuple[int, ...] = (2, 3)) -> set[str]:
    """Character n-grams for Chinese seed matching.

    Chinese has no spaces, so a clause like "中央集权与制度变迁" cannot be
    matched by splitting on punctuation alone.  Bigram/trigram overlap lets a
    query seed entities, frameworks, and claims that share meaningful terms
    without requiring a tokenizer dependency.
    """
    grams: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        for size in sizes:
            for index in range(max(0, len(run) - size + 1)):
                gram = run[index : index + size]
                if len(gram) == 2 and gram in _CJK_STOP_BIGRAMS:
                    continue
                grams.add(gram)
    return grams


def _seed_scores(
    store: Store,
    nodes: dict[str, dict[str, Any]],
    query: str,
    book_ids: list[str] | None,
    anchor_chunk_ids: set[str] | None = None,
) -> tuple[dict[str, float], list[str]]:
    seeds: dict[str, float] = defaultdict(float)
    seed_entities: list[str] = []
    try:
        detected = detect_entities(store, query)
    except Exception:
        detected = []
    for item in detected:
        entity_id = item.get("entity_id", "")
        if entity_id and f"entity:{entity_id}" in nodes:
            seeds[f"entity:{entity_id}"] = max(seeds[f"entity:{entity_id}"], 1.0)
            seed_entities.append(entity_id)
    lowered = query.lower()
    terms = [term for term in re.split(r"[\s,，。；;、/？！?]+", lowered) if len(term) >= 2]
    term_limit = set(terms[:24])
    query_grams = _cjk_ngrams(lowered)
    ranked: list[tuple[float, str]] = []
    anchors = {str(chunk_id) for chunk_id in (anchor_chunk_ids or set()) if chunk_id}
    if anchors:
        # Anchor the graph walk in the strongest hybrid hits.  This keeps the
        # graph channel precise: it discovers neighbouring claims/entities
        # instead of seeding from every common bigram in the question.
        for chunk_id in anchors:
            node_id = f"chunk:{chunk_id}"
            if node_id in nodes:
                seeds[node_id] = max(seeds[node_id], 1.0)
        if book_ids:
            allowed = set(book_ids)
            seeds = {
                node_id: score for node_id, score in seeds.items()
                if not nodes[node_id]["book_id"] or nodes[node_id]["book_id"] in allowed
            }
        return dict(seeds), sorted(set(seed_entities))
    for node_id, node in nodes.items():
        node_type = node["node_type"]
        if node_type == "entity":
            name = node["label"].lower()
            aliases = [str(alias).lower() for alias in node["data"].get("aliases", [])]
            exact = bool(name) and (name in lowered or any(alias and alias in lowered for alias in aliases))
            if exact:
                seeds[node_id] = max(seeds[node_id], 0.95)
                seed_entities.append(node["ref_id"])
                continue
            overlap = len(query_grams.intersection(_cjk_ngrams(" ".join([name, *aliases]))))
            if overlap >= 2 or (overlap >= 1 and len(name) <= 4):
                seeds[node_id] = max(seeds[node_id], min(0.9, 0.6 + 0.07 * overlap))
                seed_entities.append(node["ref_id"])
        elif node_type == "framework":
            text = f"{node['label']} {node['data'].get('one_liner', '')}".lower()
            exact = any(term in text for term in term_limit)
            overlap = len(query_grams.intersection(_cjk_ngrams(text)))
            if exact or overlap >= 2:
                ranked.append((min(0.68, 0.34 + 0.05 * overlap) if not exact else 0.68, node_id))
        elif node_type == "claim":
            text = f"{node['label']} {node['data'].get('quote', '')}".lower()
            exact = any(term in text for term in term_limit)
            overlap = len(query_grams.intersection(_cjk_ngrams(text)))
            if exact or overlap >= 2:
                ranked.append((min(0.86, 0.42 + 0.05 * overlap), node_id))
        elif node_type == "book":
            if node["label"].lower() in lowered:
                seeds[node_id] = max(seeds[node_id], 0.6)
    # Cap noisy claim/framework fan-out while keeping the strongest seeds.
    for score, node_id in sorted(ranked, key=lambda item: (-item[0], item[1]))[:80]:
        seeds[node_id] = max(seeds[node_id], score)
    if book_ids:
        allowed = set(book_ids)
        seeds = {
            node_id: score for node_id, score in seeds.items()
            if not nodes[node_id]["book_id"] or nodes[node_id]["book_id"] in allowed
        }
    return dict(seeds), sorted(set(seed_entities))


def query_graph(
    store: Store,
    query: str,
    book_ids: list[str] | None = None,
    limit: int = 12,
    max_hops: int = 2,
    anchor_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Weighted 2-hop graph retrieval returning chunk candidates.

    Graph failures are reported, never raised into the analysis path.  The
    function returns ``available=False`` when the sidecar is missing or broken.
    """
    path = graph_path_for(store)
    result: dict[str, Any] = {
        "query": query,
        "available": False,
        "path": str(path),
        "items": [],
        "communities": [],
        "seed_entities": [],
        "max_hops": max_hops,
    }
    if not path.exists():
        result["reason"] = "graph sidecar missing"
        return result
    graph = _graph_store(store)
    try:
        nodes = _load_nodes(graph)
        if not nodes:
            result["reason"] = "graph sidecar is empty"
            return result
        adjacency: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
        for edge in _load_edges(graph):
            adjacency[edge["src"]].append((edge["dst"], edge["weight"], edge["relation"]))
            adjacency[edge["dst"]].append((edge["src"], edge["weight"] * 0.9, edge["relation"]))
        seeds, seed_entities = _seed_scores(store, nodes, query, book_ids, set(anchor_chunk_ids or []))
        scores: dict[str, float] = defaultdict(float)
        queue: deque[tuple[str, float, int]] = deque()
        for node_id, score in sorted(seeds.items(), key=lambda item: (-item[1], item[0])):
            if node_id not in nodes:
                continue
            scores[node_id] = max(scores[node_id], score)
            queue.append((node_id, score, 0))
        while queue:
            node_id, score, hop = queue.popleft()
            if hop >= max_hops:
                continue
            for neighbor, weight, _relation in adjacency.get(node_id, []):
                if neighbor not in nodes:
                    continue
                propagated = score * (0.62 ** (hop + 1)) * max(0.05, min(1.0, weight))
                if propagated <= scores.get(neighbor, 0.0) + 1e-9:
                    continue
                scores[neighbor] = propagated
                queue.append((neighbor, propagated, hop + 1))

        allowed = set(book_ids or [])
        chunk_scores: dict[str, float] = defaultdict(float)
        chunk_reasons: dict[str, list[str]] = defaultdict(list)
        for node_id, score in scores.items():
            node = nodes[node_id]
            if node["node_type"] == "chunk":
                chunk_id = node["ref_id"]
                chunk_scores[chunk_id] = max(chunk_scores[chunk_id], score)
                chunk_reasons[chunk_id].append(node_id)
            elif node["node_type"] == "claim":
                chunk_id = node["data"].get("chunk_id", "")
                if chunk_id:
                    chunk_scores[chunk_id] += score * 0.9
                    chunk_reasons[chunk_id].append(node_id)
        items: list[dict[str, Any]] = []
        anchor_set = set(anchor_chunk_ids or [])
        query_grams = _cjk_ngrams(query)
        candidates: list[tuple[float, str, float, Any]] = []
        for chunk_id, score in chunk_scores.items():
            # Anchors are already the hybrid channel's own hits.  Returning
            # them again would make the graph channel a duplicate of hybrid;
            # the useful graph signal is the neighbouring chunks it discovers.
            if chunk_id in anchor_set:
                continue
            chunk = store.get_chunk(chunk_id)
            if chunk is None:
                continue
            if allowed and chunk.book_id not in allowed:
                continue
            lexical = len(query_grams.intersection(_cjk_ngrams(chunk.text)))
            final_score = float(score) + min(0.2, 0.015 * lexical)
            candidates.append((final_score, chunk_id, float(score), chunk))
        for final_score, chunk_id, graph_score, chunk in sorted(candidates, key=lambda item: (-item[0], item[1]))[: max(1, limit)]:
            items.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "book_id": chunk.book_id,
                    "chapter_title": chunk.chapter_title,
                    "page_start": chunk.page_start,
                    "text": chunk.text,
                    "score": round(final_score, 6),
                    "source": "graph",
                    "graph_reasons": sorted(set(chunk_reasons.get(chunk_id, [])))[:6],
                    "score_breakdown": {"graph": graph_score, "lexical_bonus": round(final_score - graph_score, 6)},
                }
            )
        communities = _communities_for_nodes(graph, set(seeds) | {node_id for node_id, score in scores.items() if score > 0.15})
        result.update(
            {
                "available": True,
                "items": items,
                "communities": communities,
                "seed_entities": seed_entities,
                "node_count": len(nodes),
                "visited_nodes": len(scores),
            }
        )
        return result
    except Exception as exc:
        result["reason"] = f"graph query failed: {exc}"
        return result
    finally:
        graph.close()


def _communities_for_nodes(graph: GraphStore, node_ids: set[str], limit: int = 6) -> list[dict[str, Any]]:
    if not node_ids:
        return []
    communities: list[dict[str, Any]] = []
    for row in graph.conn.execute("SELECT * FROM communities ORDER BY size DESC").fetchall():
        members = [
            member["node_id"]
            for member in graph.conn.execute(
                "SELECT node_id FROM community_members WHERE community_id = ?", (row["community_id"],)
            ).fetchall()
        ]
        overlap = len(node_ids.intersection(members))
        if overlap <= 0:
            continue
        summary = _loads(row["summary"], {})
        communities.append(
            {
                "community_id": row["community_id"],
                "label": row["label"],
                "size": row["size"],
                "overlap": overlap,
                "summary": summary,
            }
        )
        if len(communities) >= limit:
            break
    return communities


def list_communities(store: Store, limit: int = 30) -> list[dict[str, Any]]:
    path = graph_path_for(store)
    if not path.exists():
        return []
    graph = _graph_store(store)
    try:
        rows = graph.conn.execute("SELECT * FROM communities ORDER BY size DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            members = [
                graph._node_label(member["node_id"])
                for member in graph.conn.execute(
                    "SELECT node_id FROM community_members WHERE community_id = ? LIMIT 20",
                    (row["community_id"],),
                ).fetchall()
            ]
            result.append(
                {
                    "community_id": row["community_id"],
                    "label": row["label"],
                    "size": row["size"],
                    "summary": _loads(row["summary"], {}),
                    "members": members,
                }
            )
        return result
    except Exception:
        return []
    finally:
        graph.close()


def _rrf_fuse(
    channels: list[tuple[str, float, list[dict[str, Any]]]],
    rrf_k: int,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for name, weight, items in channels:
        for rank, item in enumerate(items, start=1):
            chunk_id = str(item.get("chunk_id", ""))
            if not chunk_id:
                continue
            contribution = weight / (rrf_k + rank)
            if chunk_id not in merged:
                merged[chunk_id] = {
                    **item,
                    "rrf_score": 0.0,
                    "channels": {},
                }
            entry = merged[chunk_id]
            entry["rrf_score"] += contribution
            entry["channels"][name] = {
                "rank": rank,
                "score": item.get("score"),
                "contribution": contribution,
            }
            if name == "graph":
                entry["source"] = "graph+hybrid" if "hybrid" in entry["channels"] else "graph"
            elif name == "hybrid":
                entry["source"] = "graph+hybrid" if "graph" in entry["channels"] else "hybrid"
    return sorted(merged.values(), key=lambda item: (-item["rrf_score"], item.get("chunk_id", "")))


def fused_search_report(
    store: Store,
    query: str,
    book_ids: list[str] | None = None,
    limit: int = 8,
    rrf_k: int = DEFAULT_RRF_K,
    graph_weight: float = DEFAULT_GRAPH_WEIGHT,
) -> dict[str, Any]:
    """Hybrid + GraphRAG retrieval fused with Reciprocal Rank Fusion."""
    report: dict[str, Any] = {
        "query": query,
        "channels": {"hybrid": [], "graph": [], "fused": []},
        "communities": [],
        "graph": {"available": False, "path": str(graph_path_for(store))},
        "rrf_k": rrf_k,
        "graph_weight": graph_weight,
        "fallback": "",
    }
    try:
        hybrid = hybrid_search(store, query, book_ids=book_ids, limit=max(limit * 3, 12), mode="hybrid")
    except Exception as exc:
        hybrid = []
        report["fallback"] = f"hybrid failed: {exc}"
    graph_result: dict[str, Any] = {"available": False, "items": [], "communities": []}
    try:
        graph_result = query_graph(
            store,
            query,
            book_ids=book_ids,
            limit=max(limit * 3, 12),
            anchor_chunk_ids=[str(item.get("chunk_id", "")) for item in hybrid[: max(limit * 2, 12)] if item.get("chunk_id")],
        )
    except Exception as exc:
        report["fallback"] = (report["fallback"] + "; " if report["fallback"] else "") + f"graph failed: {exc}"
    graph_items = graph_result.get("items", []) if graph_result.get("available") else []
    fused = _rrf_fuse(
        [
            ("hybrid", 1.0, hybrid),
            ("graph", graph_weight, graph_items),
        ],
        max(1, rrf_k),
    )
    report["channels"] = {
        "hybrid": [_compact_item(item) for item in hybrid[: max(limit * 2, 16)]],
        "graph": [_compact_item(item) for item in graph_items[: max(limit * 2, 16)]],
        "fused": [_compact_item(item) for item in fused[: max(limit * 2, 16)]],
    }
    report["items"] = fused[:limit]
    report["communities"] = graph_result.get("communities", [])
    report["graph"] = {
        "available": bool(graph_result.get("available")),
        "path": graph_result.get("path"),
        "seed_entities": graph_result.get("seed_entities", []),
        "reason": graph_result.get("reason", ""),
        "visited_nodes": graph_result.get("visited_nodes", 0),
    }
    if not graph_items:
        report["fallback"] = report["fallback"] or "graph returned no chunks; hybrid channel remains active"
    return report


def _compact_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": item.get("chunk_id"),
        "book_id": item.get("book_id"),
        "score": item.get("score"),
        "rrf_score": item.get("rrf_score"),
        "source": item.get("source"),
        "chapter_title": item.get("chapter_title"),
        "channels": item.get("channels", {}),
    }


def fused_search(
    store: Store,
    query: str,
    book_ids: list[str] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    return fused_search_report(store, query, book_ids=book_ids, limit=limit).get("items", [])