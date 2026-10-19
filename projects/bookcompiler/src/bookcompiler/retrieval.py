from __future__ import annotations

import logging
import math
import re
from typing import Any

from .embeddings import cosine, get_embedder
from .entities import AMBIGUOUS_ALIASES, detect_entities, related_entities
from .evolution import get_evolution_config
from .rerank import enabled as rerank_enabled, rerank_items
from .store import Store, query_terms

logger = logging.getLogger(__name__)

DEFAULT_RETRIEVAL_CONFIG: dict[str, Any] = {
    "bm25_weight": 0.55,
    "embedding_weight": 0.35,
    "entity_weight": 0.10,
    "lexical_expansion_weight": 0.35,
    "lazy_embed": True,
    "entity_expand": True,
    # None means "follow BOOKCOMPILER_RERANK"; True/False is an explicit override.
    "rerank": None,
    "rerank_candidates": 40,
    # Extra weight for glossary-bridged English chunks when the query is Chinese.
    "cross_lingual_weight": 0.25,
}


def load_retrieval_config(store: Store | None = None) -> dict[str, Any]:
    config = dict(DEFAULT_RETRIEVAL_CONFIG)
    if store is not None:
        saved = store.get_state("retrieval_config", {})
        if isinstance(saved, dict):
            for key in config:
                if key in saved:
                    config[key] = saved[key]
    return config


_ROWS_CACHE: dict[tuple[str, tuple[str, ...], tuple[int, int, int, int]], list[dict[str, Any]]] = {}
_QUERY_VECTOR_CACHE: dict[tuple[str, str, str], tuple[float, ...]] = {}
_MATRIX_CACHE: dict[tuple[str, str, tuple[int, int, int, int], tuple[str, ...]], Any] = {}
_VECTORS_CACHE: dict[tuple[str, str, tuple[int, int, int, int], tuple[str, ...]], dict[str, list[float]]] = {}
_QUALITY_CACHE: dict[tuple[str, tuple[int, int, int, int]], dict[str, float]] = {}


def _db_version(store: Store) -> tuple[int, int, int, int]:
    """Cheap content fingerprint used to invalidate read-through caches.

    ``total_changes`` catches writes made through this connection (embeddings,
    re-ingest); ``PRAGMA data_version`` catches commits from other processes
    such as the GUI or an MCP server.  Counting chunks and taking MAX(rowid)
    covers table swaps that keep the change counter stable across reconnects.
    """
    chunk_row = store.conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(MAX(rowid), 0) AS max_rowid FROM chunks"
    ).fetchone()
    data_version = int(store.conn.execute("PRAGMA data_version").fetchone()[0])
    return (
        int(store.conn.total_changes),
        data_version,
        int(chunk_row["n"]),
        int(chunk_row["max_rowid"]),
    )


def _cache_put(cache: dict[Any, Any], key: Any, value: Any, limit: int = 16) -> None:
    cache[key] = value
    if len(cache) > limit:
        cache.pop(next(iter(cache)))


def _query_vector(backend, query: str) -> tuple[float, ...]:
    key = (str(getattr(backend, "kind", "")), str(getattr(backend, "model", "")), str(query))
    cached = _QUERY_VECTOR_CACHE.get(key)
    if cached is None:
        cached = tuple(float(value) for value in backend.embed([query])[0])
        _cache_put(_QUERY_VECTOR_CACHE, key, cached, limit=256)
    return cached


def _cached_embeddings(
    store: Store,
    model: str,
    chunk_ids: list[str],
    version: tuple[int, int, int, int],
) -> dict[str, list[float]]:
    key = (str(store.db_path.resolve()), model, version, tuple(chunk_ids))
    cached = _VECTORS_CACHE.get(key)
    if cached is None:
        cached = store.get_embeddings(model, chunk_ids)
        _cache_put(_VECTORS_CACHE, key, cached, limit=8)
    return cached


def _quality_scores(
    store: Store,
    rows: list[dict[str, Any]],
    version: tuple[int, int, int, int],
) -> list[float]:
    key = (str(store.db_path.resolve()), version)
    cached = _QUALITY_CACHE.get(key)
    if cached is None or len(cached) != len(rows):
        cached = {row["chunk_id"]: _quality_multiplier(row) for row in rows}
        _cache_put(_QUALITY_CACHE, key, cached, limit=8)
    return [cached.get(row["chunk_id"], 1.0) for row in rows]


def _embedding_values(
    store: Store,
    rows: list[dict[str, Any]],
    vectors: dict[str, list[float]],
    query_vector: Any,
    model: str,
    version: tuple[int, int, int, int] | None = None,
) -> list[float]:
    """Cosine scores for every row, with a cached numpy matrix.

    The matrix is immutable per (database revision, model, row set), so a warm
    process pays one matrix-vector multiply instead of thousands of Python
    loops.  If numpy is unavailable we fall back to the original cosine loop.
    """
    if not vectors or len(query_vector) == 0:
        return [0.0] * len(rows)
    version = version or _db_version(store)
    chunk_ids = tuple(row["chunk_id"] for row in rows)
    key = (str(store.db_path.resolve()), model, version, chunk_ids)
    matrix = _MATRIX_CACHE.get(key)
    if matrix is None:
        try:
            import numpy as np

            matrix = np.zeros((len(rows), len(query_vector)), dtype="float32")
            for index, row in enumerate(rows):
                vector = vectors.get(row["chunk_id"])
                if not vector or len(vector) != matrix.shape[1]:
                    # Never truncate/pad a mismatched vector: that would
                    # silently compare vectors from different model spaces.
                    continue
                matrix[index] = vector
            _cache_put(_MATRIX_CACHE, key, matrix, limit=6)
        except Exception:
            matrix = False
            _cache_put(_MATRIX_CACHE, key, matrix, limit=6)
    if matrix is not False:
        try:
            import numpy as np

            scores = matrix @ np.asarray(query_vector, dtype="float32")
            return [float(max(0.0, min(1.0, value))) for value in scores]
        except Exception:
            pass
    return [cosine(query_vector, vectors.get(row["chunk_id"], [])) for row in rows]


def bm25_scores(
    rows: list[dict[str, Any]],
    terms: list[str],
    k1: float = 1.5,
    b: float = 0.75,
    term_weights: dict[str, float] | None = None,
) -> list[float]:
    if not rows or not terms:
        return [0.0] * len(rows)
    terms = [str(term).lower() for term in terms]
    documents = []
    for row in rows:
        text = f"{row.get('chapter_title', '')} {row.get('text', '')}".lower()
        documents.append(text)
    lengths = [max(len(document), 1) for document in documents]
    avgdl = sum(lengths) / len(lengths)
    document_frequency: dict[str, int] = {}
    for term in terms:
        document_frequency[term] = sum(1 for document in documents if term in document)
    total = len(documents)
    idf = {
        term: math.log(1.0 + (total - df + 0.5) / (df + 0.5))
        for term, df in document_frequency.items()
    }
    term_weights = {str(key).lower(): value for key, value in (term_weights or {}).items()}
    scores: list[float] = []
    for document, length in zip(documents, lengths):
        score = 0.0
        for term in terms:
            frequency = document.count(term)
            if frequency <= 0:
                continue
            denominator = frequency + k1 * (1.0 - b + b * length / max(avgdl, 1e-9))
            weight = max(0.0, float(term_weights.get(term, 1.0)))
            score += weight * idf[term] * frequency * (k1 + 1.0) / max(denominator, 1e-9)
        scores.append(score)
    return scores


def _normalized(values: list[float]) -> list[float]:
    if not values:
        return []
    maximum = max(values)
    if maximum <= 1e-12:
        return [0.0] * len(values)
    return [max(0.0, value) / maximum for value in values]


def _quality_multiplier(row: dict[str, Any]) -> float:
    """Down-rank OCR index pages and reference dumps without hiding them.

    A page full of page numbers and index cross-references can match many query terms while
    containing no usable argument. The multiplier is intentionally modest and
    is returned in ``score_breakdown`` so a low-quality hit remains auditable.
    """
    text = str(row.get("text", ""))
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return 0.25
    # str.count runs in C; the old per-character generator did ~5M Python
    # iterations per query and was the single largest retrieval cost.
    digits = sum(compact.count(character) for character in "0123456789")
    digit_ratio = digits / max(len(compact), 1)
    reference_markers = (
        compact.count("\u53e6\u53c2\u89c1")
        + compact.count("\u53c2\u89c1")
        + compact.count("\u7d22\u5f15")
        + compact.count("index")
    )
    # Front-matter tables of contents and "专栏/目录" listings are not
    # arguments. They can match many query terms while containing no usable
    # claim, so they get a separate structural penalty from index pages.
    toc_markers = compact.count("\u76ee\u5f55") + compact.count("\u4e13\u680f") + compact.lower().count("contents")
    chapter_markers = len(re.findall(r"\u7b2c[\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\u767e0-9]{1,4}[\u7ae0\u8282\u8bb2\u7bc7\u90e8]", compact))
    page_number_runs = len(re.findall(r"\d{1,3}", compact))
    penalty = 0.0
    if reference_markers >= 2:
        penalty += min(0.55, 0.16 * reference_markers)
    if reference_markers and digit_ratio > 0.16:
        penalty += min(0.30, (digit_ratio - 0.16) * 1.8)
    if toc_markers >= 3:
        penalty += min(0.50, 0.11 * toc_markers)
    if chapter_markers >= 4 and page_number_runs >= 4:
        penalty += min(0.30, 0.045 * chapter_markers)
    if digit_ratio > 0.22:
        penalty += min(0.20, (digit_ratio - 0.22) * 1.2)
    if len(compact) < 40:
        penalty += 0.08
    return round(max(0.25, 1.0 - penalty), 4)


def _chunk_rows(
    store: Store,
    book_ids: list[str] | None,
    version: tuple[int, int, int, int] | None = None,
) -> list[dict[str, Any]]:
    version = version or _db_version(store)
    key = (str(store.db_path.resolve()), tuple(book_ids or ()), version)
    cached = _ROWS_CACHE.get(key)
    if cached is not None:
        return cached
    params: list[Any] = []
    where = ""
    if book_ids:
        placeholders = ",".join("?" for _ in book_ids)
        where = f"WHERE book_id IN ({placeholders})"
        params.extend(book_ids)
    rows = store.conn.execute(
        f"SELECT chunk_id, book_id, chapter_index, chapter_title, position, text, page_start, page_end FROM chunks {where}"
        " ORDER BY book_id, chapter_index, position",
        params,
    ).fetchall()
    result = [dict(row) for row in rows]
    _cache_put(_ROWS_CACHE, key, result, limit=16)
    return result


# Cross-lingual bridge for mixed-language libraries.  A Chinese question about
# "逻辑谬误" should still reach an English logic textbook.  This is a small,
# auditable glossary rather than a translation call: deterministic and cheap.
_CROSS_LINGUAL = {
    "逻辑": ["logic", "logical"],
    "谬误": ["fallacy", "fallacies"],
    "论证": ["argument", "reasoning"],
    "推理": ["reasoning", "inference"],
    "命题": ["proposition"],
    "演绎": ["deduction", "deductive"],
    "归纳": ["induction", "inductive"],
    "证据": ["evidence"],
    "定义": ["definition"],
    "法律": ["law", "legal"],
    "权利": ["right", "rights"],
    "义务": ["obligation", "duty"],
    "正义": ["justice"],
    "自由": ["liberty", "freedom"],
    "法治": ["rule of law"],
    "宪法": ["constitution", "constitutional"],
    "监管": ["regulation", "regulatory"],
    "文明": ["civilization", "civilisation"],
    "文化": ["culture"],
    "政治": ["politics", "political"],
    "权力": ["power"],
    "国家": ["state", "nation"],
    "民主": ["democracy", "democratic"],
    "制度": ["institution", "institutional"],
    "秩序": ["order"],
    "冲突": ["conflict"],
    "市场": ["market"],
    "货币": ["money", "monetary"],
    "信贷": ["credit"],
    "银行": ["bank", "banking"],
    "利率": ["interest rate"],
    "通胀": ["inflation"],
    "通缩": ["deflation"],
    "债务": ["debt"],
    "财政": ["fiscal"],
    "税收": ["tax", "taxation"],
    "土地": ["land"],
    "房价": ["housing price"],
    "危机": ["crisis"],
    "周期": ["cycle", "cyclical"],
    "投资": ["investment"],
    "风险": ["risk"],
    "央行": ["central bank"],
    "准备金": ["reserve", "reserves"],
}


def _cross_lingual_terms(query: str, limit: int = 12) -> list[str]:
    """Add English equivalents for Chinese academic terms present in the query."""
    text = str(query or "")
    result: list[str] = []
    for chinese, english in _CROSS_LINGUAL.items():
        if chinese and chinese in text:
            for term in english:
                if term not in result:
                    result.append(term)
    return result[:limit]


def _expansion_terms(detected: list[dict[str, Any]], limit: int = 12) -> list[str]:
    """Return specific entity surfaces, longest first, without generic aliases."""
    candidates: list[str] = []
    for entity in detected:
        for value in [entity.get("canonical_name", ""), *entity.get("aliases", [])]:
            value = str(value or "").strip()
            normalized = value.lower()
            if len(value) < 2 or normalized in AMBIGUOUS_ALIASES:
                continue
            candidates.append(value)
    candidates = sorted(set(candidates), key=lambda value: (-len(value), value.lower()))
    chosen: list[str] = []
    for value in candidates:
        lowered = value.lower()
        if any(lowered in item.lower() or item.lower() in lowered for item in chosen):
            continue
        chosen.append(value)
        if len(chosen) >= limit:
            break
    return chosen


def hybrid_search(
    store: Store,
    query: str,
    book_ids: list[str] | None = None,
    limit: int = 12,
    mode: str = "hybrid",
    config: dict[str, Any] | None = None,
    embedder=None,
    rerank: bool | None = None,
) -> list[dict[str, Any]]:
    """Hybrid lexical + embedding + entity-expanded retrieval.

    `mode="lexical"` is kept for diagnostics and replay comparisons. The default
    hybrid mode uses BM25, a local/remote embedding vector, and a small bonus for
    chunks that mention entities detected in the question. Entity surfaces are
    also added to BM25 with a lower weight so a query such as "降准" can recall
    passages that use "存款准备金率" explicitly. All components are returned in
    `score_breakdown` so a result is auditable rather than a black box.
    """
    terms = query_terms(query)
    if not terms and not query.strip():
        return []
    if config is None:
        config = get_evolution_config(store).get("retrieval", {})
    config = {**DEFAULT_RETRIEVAL_CONFIG, **(config or {})}
    version = _db_version(store)
    rows = _chunk_rows(store, book_ids, version)
    if not rows:
        return []

    detected: list[dict[str, Any]] = []
    related: list[dict[str, Any]] = []
    expanded_terms: list[str] = []
    entity_chunk_map: dict[str, set[str]] = {}
    related_chunks: set[str] = set()
    if mode == "hybrid" and config.get("entity_expand", True):
        detected = detect_entities(store, query)
        if detected:
            ids = [item["entity_id"] for item in detected]
            entity_chunk_map = {
                item["entity_id"]: store.entity_chunk_ids([item["entity_id"]])
                for item in detected
            }
            related = related_entities(store, ids)
            related_chunks = store.entity_chunk_ids([item["entity_id"] for item in related])
            expanded_terms = _expansion_terms(detected)
    if mode == "hybrid":
        for term in _cross_lingual_terms(query):
            if term not in expanded_terms:
                expanded_terms.append(term)

    expansion_weight = max(0.0, min(1.0, float(config.get("lexical_expansion_weight", 0.35))))
    cross_weight = max(0.0, min(1.0, float(config.get("cross_lingual_weight", 0.25))))
    bridge_norm = [0.0] * len(rows)
    latin_expansion = [term for term in expanded_terms if re.search(r"[A-Za-z]", term)]
    if mode == "hybrid" and latin_expansion and re.search(r"[\u4e00-\u9fff]", query):
        bridge_raw = bm25_scores(rows, latin_expansion, term_weights={term: 1.0 for term in latin_expansion})
        bridge_norm = _normalized(bridge_raw)
        for index, row in enumerate(rows):
            text_value = str(row.get("text") or "")
            letters = len(re.findall(r"[A-Za-z]", text_value))
            cjk = len(re.findall(r"[\u4e00-\u9fff]", text_value))
            # Keep the bridge for genuinely English passages; do not let a few
            # acronyms in a Chinese passage trigger it.
            if letters < 20 or letters <= cjk * 2:
                bridge_norm[index] = 0.0
    term_weights = {term.lower(): 1.0 for term in terms}
    for term in expanded_terms:
        lowered = term.lower()
        if lowered in term_weights:
            continue
        term_weights[lowered] = expansion_weight
    lexical = bm25_scores(rows, list(term_weights), term_weights=term_weights)
    lexical_norm = _normalized(lexical)

    embedding_values = [0.0] * len(rows)
    embedding_available = False
    embedding_error = ""
    embedding_model = ""
    embedding_covered = 0
    embedding_fallback = False
    embedding_warning = ""
    if mode == "hybrid":
        backend = embedder or get_embedder()
        chunk_ids = [row["chunk_id"] for row in rows]
        vectors: dict[str, list[float]] = {}
        query_vector: Any = ()
        try:
            vectors = _cached_embeddings(store, backend.model, chunk_ids, version)
            if config.get("lazy_embed", True) and len(vectors) < len(chunk_ids):
                filled = store.embed_pending(backend, chunk_ids=chunk_ids)
                if filled.get("fallback"):
                    embedding_fallback = True
                    embedding_warning = (
                        f"embedding backend fell back to {filled.get('model', 'local')}: "
                        f"{filled.get('fallback_error', '')}"
                    )
                    logger.warning(embedding_warning)
                    backend = get_embedder(allow_remote=False)
                # embed_pending() writes to this same connection.  The version
                # captured before the write is now stale, so using it would hit
                # the cached pre-backfill vector dictionary and silently keep
                # only the chunks that were already embedded.
                version = _db_version(store)
                vectors = _cached_embeddings(store, backend.model, chunk_ids, version)
            query_vector = _query_vector(backend, query)
            embedding_model = backend.model
        except Exception as exc:
            embedding_error = f"{type(exc).__name__}: {exc}"
            # A local fallback is safe only when both the query and the stored
            # vectors come from the same local model space.
            if backend.kind != "local":
                local = get_embedder(allow_remote=False)
                try:
                    store.embed_pending(local, chunk_ids=chunk_ids)
                    version = _db_version(store)
                    vectors = _cached_embeddings(store, local.model, chunk_ids, version)
                    query_vector = _query_vector(local, query)
                    backend = local
                    embedding_model = local.model
                    embedding_fallback = True
                    embedding_warning = f"{embedding_error}; using local fallback {local.model}"
                    logger.warning(embedding_warning)
                except Exception as local_exc:
                    embedding_error += f"; local fallback failed: {type(local_exc).__name__}: {local_exc}"
                    vectors = {}
                    query_vector = ()
            else:
                vectors = {}
                query_vector = ()
        embedding_covered = len(vectors)
        if vectors and len(query_vector):
            embedding_available = True
            embedding_values = _embedding_values(store, rows, vectors, query_vector, embedding_model, version)
    embedding_norm = _normalized(embedding_values)

    bm25_weight = float(config.get("bm25_weight", 0.55))
    embedding_weight = float(config.get("embedding_weight", 0.35)) if embedding_available else 0.0
    entity_weight = float(config.get("entity_weight", 0.10))
    total_weight = bm25_weight + embedding_weight + entity_weight
    if total_weight <= 0:
        total_weight = 1.0

    quality_values = _quality_scores(store, rows, version)
    scored: list[tuple[float, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        # Reward chunks that contain several distinct entities from the
        # question, not just any one of them. A passage connecting local
        # government debt, banks, and reserve requirements is stronger evidence
        # than a passage that only mentions one of the three.
        matched_entities = [
            entity for entity in detected
            if row["chunk_id"] in entity_chunk_map.get(entity["entity_id"], set())
        ]
        entity_bonus = 0.0
        if matched_entities:
            entity_bonus = 0.35 + 0.65 * len(matched_entities) / max(1, len(detected))
        elif row["chunk_id"] in related_chunks:
            entity_bonus = 0.3
        base_score = (
            bm25_weight * lexical_norm[index]
            + embedding_weight * embedding_norm[index]
            + entity_weight * entity_bonus
        ) / total_weight
        if cross_weight and bridge_norm[index]:
            base_score = min(1.0, base_score + cross_weight * bridge_norm[index])
        quality = quality_values[index]
        score = base_score * quality
        if score <= 1e-9:
            continue
        item = dict(row)
        item["score"] = round(score, 6)
        item["score_breakdown"] = {
            "bm25_raw": round(lexical[index], 4),
            "bm25": round(lexical_norm[index], 4),
            "embedding": round(embedding_norm[index], 4),
            "entity": round(entity_bonus, 4),
            "quality": quality,
            "base_score": round(base_score, 6),
            "weights": {
                "bm25": bm25_weight,
                "embedding": embedding_weight,
                "entity": entity_weight,
            },
            "cross_lingual": round(bridge_norm[index], 4),
        }
        item["matched_entities"] = [entity["canonical_name"] for entity in matched_entities]
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["book_id"], pair[1]["chapter_index"], pair[1]["position"]))
    candidate_count = len(scored)
    rerank_requested = bool(config.get("rerank")) if rerank is None else bool(rerank)
    if rerank is None and config.get("rerank") is None:
        rerank_requested = rerank_enabled()
    pool_size = max(limit, int(config.get("rerank_candidates", 40))) if rerank_requested else limit
    candidates = [item for _, item in scored[:pool_size]]
    rerank_meta: dict[str, Any] = {"requested": rerank_requested, "reranked": False}
    if rerank_requested and candidates:
        candidates, rerank_meta = rerank_items(query, candidates, top_k=limit)
    results = candidates[:limit]
    for item in results:
        item["retrieval"] = {
            "mode": mode,
            "embedding_available": embedding_available,
            "embedding_model": embedding_model,
            "embedding_covered": embedding_covered,
            "embedding_error": embedding_error,
            "embedding_fallback": embedding_fallback,
            "embedding_warning": embedding_warning,
            "detected_entities": [entity["canonical_name"] for entity in detected],
            "related_entities": [entity["canonical_name"] for entity in related],
            "expanded_terms": expanded_terms,
            "lexical_expansion_weight": expansion_weight,
            "candidate_count": candidate_count,
            "rerank": rerank_meta,
        }
    return results

def retrieval_diagnostics(store: Store, query: str, book_ids: list[str] | None = None, limit: int = 8) -> dict[str, Any]:
    lexical = hybrid_search(store, query, book_ids=book_ids, limit=limit, mode="lexical")
    hybrid = hybrid_search(store, query, book_ids=book_ids, limit=limit, mode="hybrid")
    detected = detect_entities(store, query)
    return {
        "query": query,
        "embedding": store.embedding_stats(get_embedder().model),
        "entities": {
            "detected": detected,
            "stats": store.entity_stats(),
        },
        "lexical": [
            {"chunk_id": item["chunk_id"], "book_id": item["book_id"], "score": item["score"], "chapter": item["chapter_title"]}
            for item in lexical
        ],
        "hybrid": [
            {
                "chunk_id": item["chunk_id"],
                "book_id": item["book_id"],
                "score": item["score"],
                "breakdown": item["score_breakdown"],
                "chapter": item["chapter_title"],
                "matched_entities": item.get("matched_entities", []),
            }
            for item in hybrid
        ],
    }
