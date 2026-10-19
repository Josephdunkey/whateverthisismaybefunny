from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from typing import Any, Iterable

from .models import utc_now
from .store import Store
from .utils import normalize_text, stable_id

# Conservative alias groups. These are seeds, not an ontology: the alignment
# pass can still create entities that are not listed here.
ALIAS_GROUPS: list[tuple[str, list[str], str]] = [
    ("中央银行", ["央行", "人民银行", "中国人民银行", "central bank", "pboc"], "institution"),
    ("地方政府融资平台", ["融资平台", "城投平台", "城投", "地方融资平台", "lgfv", "local government financing vehicle"], "institution"),
    ("土地财政", ["land finance"], "mechanism"),
    ("土地出让收入", ["土地出让金", "卖地收入", "land sale revenue"], "indicator"),
    ("土地出让", ["land sale", "land transfer"], "policy"),
    ("影子银行", ["shadow banking"], "mechanism"),
    ("表外业务", ["表外融资", "off-balance-sheet business", "off balance sheet business"], "mechanism"),
    ("存款准备金率", ["存准率", "降准", "法定存款准备金率", "rrr", "reserve requirement ratio"], "policy"),
    ("银行体系", ["银行部门", "banking system"], "institution"),
    ("商业银行", ["commercial banks"], "institution"),
    ("财政风险", ["fiscal risk"], "concept"),
    ("地方政府债务风险", ["地方债务风险", "local government debt risk"], "concept"),
    ("地方政府债务", ["地方债务", "地方政府性债务", "local government debt"], "concept"),
    ("货币政策", ["monetary policy"], "policy"),
    ("财政政策", ["fiscal policy"], "policy"),
    ("监管套利", ["regulatory arbitrage"], "mechanism"),
    ("预算软约束", ["soft budget constraint"], "mechanism"),
    ("道德风险", ["moral hazard"], "mechanism"),
    ("期限错配", ["maturity mismatch"], "mechanism"),
    ("信贷扩张", ["信用扩张", "credit expansion"], "mechanism"),
    ("房地产", ["房地产市场", "楼市", "real estate"], "sector"),
    ("资产负债表", ["balance sheet"], "concept"),
    ("公开市场操作", ["open market operations", "omo"], "policy"),
    ("利率走廊", ["interest rate corridor"], "mechanism"),
    ("金融稳定", ["financial stability"], "concept"),
    ("系统性风险", ["systemic risk"], "concept"),
    ("政府信用", ["国家信用", "sovereign credit"], "concept"),
    ("土地抵押", ["land collateral"], "mechanism"),
    ("城投债", ["platform bond", "urban investment bond"], "instrument"),
    ("专项债", ["地方政府专项债券", "special purpose bond"], "instrument"),
    ("转移支付", ["transfer payment"], "mechanism"),
    ("分税制", ["tax sharing system"], "policy"),
    ("财政分权", ["fiscal decentralization"], "concept"),
    ("信贷配给", ["credit rationing"], "mechanism"),
    ("流动性", ["liquidity"], "concept"),
    ("杠杆率", ["leverage ratio"], "indicator"),
    ("不良贷款", ["npl", "non-performing loan"], "indicator"),
    ("资本充足率", ["capital adequacy ratio", "car"], "indicator"),
    ("银行间市场", ["interbank market"], "market"),
    ("债券市场", ["bond market"], "market"),
    ("影子银行监管", ["shadow banking regulation"], "policy"),
    ("宏观审慎政策", ["宏观审慎", "macroprudential regulation", "macroprudential policy"], "policy"),
    # Cross-disciplinary seeds. These are deliberately high-confidence names
    # and are still merged only by exact alias or conservative containment.
    ("全国人民代表大会", ["全国人大", "人民代表大会", "national people's congress", "npc"], "institution"),
    ("国务院", ["state council"], "institution"),
    ("中国共产党", ["中共", "communist party of china", "cpc"], "institution"),
    ("国有企业", ["国企", "state-owned enterprise", "state owned enterprise", "soe"], "institution"),
    ("民营企业", ["民企", "private enterprise"], "institution"),
    ("产权", ["property rights"], "concept"),
    ("法治", ["rule of law"], "concept"),
    ("合法性", ["legitimacy"], "concept"),
    ("央地关系", ["中央与地方关系", "central-local relations", "central local relations"], "concept"),
    ("财政联邦制", ["fiscal federalism"], "concept"),
    ("司法解释", ["judicial interpretation"], "policy"),
    ("行政法规", ["administrative regulation", "administrative regulations"], "policy"),
    ("土地征收", ["征地", "land expropriation"], "policy"),
    ("户籍制度", ["hukou", "household registration"], "policy"),
    ("存款保险", ["deposit insurance"], "policy"),
    ("资本管制", ["capital controls", "capital control"], "policy"),
    ("汇率", ["exchange rate"], "indicator"),
    ("通货膨胀", ["通胀", "inflation"], "indicator"),
    ("通货紧缩", ["deflation"], "indicator"),
    ("经济增长", ["economic growth"], "indicator"),
    ("失业", ["unemployment"], "indicator"),
]

AMBIGUOUS_ALIASES = {
    "银行", "政府", "政策", "风险", "债务", "投资", "信贷", "货币", "市场", "金融",
    "监管", "财政", "经济", "法律", "权力", "利率", "价格", "资本", "资产", "负债",
}

_TYPE_SUFFIXES = [
    ("银行", "institution"), ("政府", "institution"), ("部门", "institution"), ("机构", "institution"),
    ("委员会", "institution"), ("央行", "institution"), ("平台", "institution"),
    ("政策", "policy"), ("制度", "policy"), ("法律", "policy"), ("条例", "policy"), ("规定", "policy"),
    ("率", "indicator"), ("量", "indicator"), ("指数", "indicator"), ("价格", "indicator"),
    ("市场", "market"), ("债", "instrument"), ("基金", "instrument"), ("贷款", "instrument"),
]

_ASCII = re.compile(r"^[a-z0-9 _\-]+$")


def _norm(value: str) -> str:
    value = normalize_text(value or "").strip().lower()
    value = re.sub(r"[\s\u3000]+", " ", value)
    value = re.sub(r"^[《“”\"'（(]+|[》”\"'）)]+$", "", value)
    value = re.sub(r"\s*(?:等|等等)$", "", value)
    return value.strip(" :：,，.。;；、")


def _entity_type(name: str) -> str:
    for suffix, kind in _TYPE_SUFFIXES:
        if name.endswith(suffix):
            return kind
    return "concept"


def _stable_entity_id(canonical: str) -> str:
    return stable_id("ent", _norm(canonical))


def _candidate_phrases(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return
        # Framework names often look like "主题：决策框架". Split on explicit
        # separators and keep the meaningful head.
        parts = re.split(r"[：:|/]", text)
        for part in parts:
            part = part.strip()
            if 2 <= len(part) <= 18:
                yield part
    elif isinstance(value, list):
        for item in value:
            yield from _candidate_phrases(item)


def _merge_candidate(groups: dict[str, dict[str, Any]], candidate: str, book_id: str) -> None:
    name = _norm(candidate)
    if not name or name in AMBIGUOUS_ALIASES:
        return
    if _ASCII.match(name):
        if len(name) < 3:
            return
    elif len(name) < 2:
        return
    # Reject sentence-like fragments.
    if len(name) > 18 or name.count("，") or name.count("。"):
        return

    matched_key = ""
    for key, group in groups.items():
        aliases = {_norm(alias) for alias in group["aliases"]}
        if name in aliases:
            matched_key = key
            break
        # Exact containment only when the shorter name is a meaningful phrase.
        for alias in aliases:
            if len(alias) >= 4 and (name in alias or alias in name):
                shorter, longer = sorted((len(name), len(alias)))
                if shorter / max(longer, 1) >= 0.72:
                    matched_key = key
                    break
        if matched_key:
            break

    if matched_key:
        group = groups[matched_key]
        if name not in {_norm(alias) for alias in group["aliases"]}:
            group["aliases"].append(candidate.strip())
        group["books"].add(book_id)
    else:
        groups[name] = {
            "canonical_name": candidate.strip(),
            "aliases": [candidate.strip()],
            "entity_type": _entity_type(name),
            "books": {book_id},
            "seeds": [],
        }


def _seed_groups(groups: dict[str, dict[str, Any]]) -> None:
    for canonical, aliases, entity_type in ALIAS_GROUPS:
        key = _norm(canonical)
        group = groups.setdefault(
            key,
            {
                "canonical_name": canonical,
                "aliases": [canonical],
                "entity_type": entity_type,
                "books": set(),
                "seeds": [],
            },
        )
        group["entity_type"] = entity_type
        for alias in aliases:
            if _norm(alias) not in {_norm(item) for item in group["aliases"]}:
                group["aliases"].append(alias)


def _match_aliases(text: str, aliases: list[str]) -> list[tuple[str, float]]:
    lowered = text.lower()
    matches: list[tuple[str, float]] = []
    for alias in aliases:
        alias_l = _norm(alias)
        if not alias_l or alias_l in AMBIGUOUS_ALIASES:
            continue
        if _ASCII.match(alias_l):
            if len(alias_l) < 3:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(alias_l)}(?![a-z0-9])", lowered):
                matches.append((alias, 0.9))
        else:
            if len(alias_l) < 2:
                continue
            if alias_l in lowered:
                matches.append((alias, 1.0))
    return matches


def align_entities(store: Store, max_relation_pairs: int = 300) -> dict[str, Any]:
    """Align concepts across books into one canonical entity graph.

    The pass is deterministic and conservative:
    1. collect concepts from agent-authored cards and framework metadata,
    2. merge exact aliases and curated groups,
    3. scan every chunk for mentions,
    4. write cross-book co-occurrence relations and provenance edges.

    It does not claim to be a full knowledge graph or an LLM ontology.
    """
    groups: dict[str, dict[str, Any]] = {}
    # Seed the alias groups first so a later candidate such as "融资平台"
    # merges into "地方政府融资平台" instead of producing a duplicate entity.
    _seed_groups(groups)
    for book in store.list_books():
        book_id = book["book_id"]
        card = store.get_book_card(book_id) or {}
        for concept in card.get("key_concepts", []) or []:
            for phrase in _candidate_phrases(concept):
                _merge_candidate(groups, phrase, book_id)
        for framework in store.list_frameworks(book_ids=[book_id]):
            for field in ("name", "inputs", "outputs"):
                for phrase in _candidate_phrases(framework.get(field)):
                    _merge_candidate(groups, phrase, book_id)
    # Drop empty seed-only entities that are never mentioned later; they are
    # still useful for alias detection, so keep them for the scan.
    entities: list[dict[str, Any]] = []
    alias_to_entity: dict[str, str] = {}
    for key, group in sorted(groups.items()):
        canonical = group["canonical_name"]
        entity_id = _stable_entity_id(canonical)
        aliases = []
        for alias in [canonical, *group["aliases"]]:
            cleaned = alias.strip()
            if cleaned and _norm(cleaned) not in {_norm(item) for item in aliases}:
                aliases.append(cleaned)
        entities.append(
            {
                "entity_id": entity_id,
                "canonical_name": canonical,
                "entity_type": group["entity_type"],
                "aliases": aliases,
            }
        )
        for alias in aliases:
            alias_to_entity[_norm(alias)] = entity_id

    chunks = store.conn.execute(
        "SELECT chunk_id, book_id, chapter_title, text FROM chunks ORDER BY book_id, chapter_index, position"
    ).fetchall()
    mentions: list[dict[str, Any]] = []
    chunk_entities: dict[str, set[str]] = defaultdict(set)
    entity_books: dict[str, set[str]] = defaultdict(set)
    for entity in entities:
        entity_id = entity["entity_id"]
        for chunk in chunks:
            text = chunk["text"] or ""
            matches = _match_aliases(text, entity["aliases"])
            if not matches:
                continue
            # One mention per entity/chunk is enough for retrieval; keep the
            # most specific surface form.
            surface = max((item[0] for item in matches), key=len)
            confidence = max(item[1] for item in matches)
            mentions.append(
                {
                    "entity_id": entity_id,
                    "chunk_id": chunk["chunk_id"],
                    "book_id": chunk["book_id"],
                    "surface": surface,
                    "confidence": confidence,
                }
            )
            chunk_entities[chunk["chunk_id"]].add(entity_id)
            entity_books[entity_id].add(chunk["book_id"])

    # Remove seed-only entities that never occur in the corpus.
    entity_by_id = {entity["entity_id"]: entity for entity in entities}
    kept_ids = set(entity_books)
    entities = [entity for entity in entities if entity["entity_id"] in kept_ids]
    mentions = [mention for mention in mentions if mention["entity_id"] in kept_ids]

    relations: list[dict[str, Any]] = []
    pair_counts: Counter[tuple[str, str]] = Counter()
    pair_evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
    for chunk_id, ids in chunk_entities.items():
        ordered = sorted(ids)
        if len(ordered) < 2:
            continue
        # Cap pathological chunks so relation generation stays linear-ish.
        ordered = ordered[:20]
        for i, left in enumerate(ordered):
            for right in ordered[i + 1:]:
                pair = (left, right)
                pair_counts[pair] += 1
                if len(pair_evidence[pair]) < 3:
                    pair_evidence[pair].append(chunk_id)
    for (left, right), weight in pair_counts.most_common(max_relation_pairs):
        if weight < 2:
            continue
        relations.append(
            {
                "src_entity_id": left,
                "dst_entity_id": right,
                "relation": "co_occurs",
                "weight": float(weight),
                "evidence": pair_evidence[(left, right)],
            }
        )

    store.replace_entity_graph(entities, mentions, relations)
    store.conn.execute("DELETE FROM edges WHERE src_type = 'entity' OR dst_type = 'entity'")
    store.conn.commit()

    book_titles = {book["book_id"]: book["title"] for book in store.list_books()}
    for entity in entities:
        books = sorted(entity_books[entity["entity_id"]])
        titles = [book_titles.get(book_id, book_id) for book_id in books]
        entity["summary"] = f"出现在 {len(books)} 本书中：" + "、".join(titles[:4]) + ("等" if len(titles) > 4 else "")
        store.conn.execute("UPDATE entities SET summary = ? WHERE entity_id = ?", (entity["summary"], entity["entity_id"]))
        for book_id in books:
            store.add_edge("book", book_id, "entity", entity["entity_id"], "discusses")
    for relation in relations:
        store.add_edge("entity", relation["src_entity_id"], "entity", relation["dst_entity_id"], relation["relation"], relation.get("evidence", []))
    store.conn.commit()

    cross_book = sum(1 for entity in entities if len(entity_books[entity["entity_id"]]) >= 2)
    return {
        "entities": len(entities),
        "cross_book_entities": cross_book,
        "mentions": len(mentions),
        "relations": len(relations),
        "books": len(store.list_books()),
        "alias_groups": len(ALIAS_GROUPS),
    }


def _entity_books(store: Store, entity_id: str) -> list[str]:
    rows = store.conn.execute(
        "SELECT DISTINCT b.title FROM entity_mentions m "
        "JOIN books b ON b.book_id = m.book_id WHERE m.entity_id = ? ORDER BY b.title",
        (entity_id,),
    ).fetchall()
    return [row["title"] for row in rows]


def alignment_audit(store: Store, threshold: float = 0.62, limit: int = 50) -> dict[str, Any]:
    """Surface near-duplicate entities for human/agent review.

    Alignment must stay conservative: a wrong merge silently destroys the
    provenance of two different concepts. This audit therefore only proposes
    candidates; it never mutates the graph. The candidate list makes unresolved
    aliases visible instead of pretending the entity graph is complete.
    """
    entities = store.list_entities(limit=1000)
    candidates: list[dict[str, Any]] = []
    for index, left in enumerate(entities):
        left_name = _norm(left["canonical_name"])
        left_surfaces = {_norm(value) for value in [left["canonical_name"], *left.get("aliases", [])]}
        for right in entities[index + 1:]:
            right_name = _norm(right["canonical_name"])
            if not left_name or not right_name or left_name == right_name:
                continue
            right_surfaces = {_norm(value) for value in [right["canonical_name"], *right.get("aliases", [])]}
            if left_surfaces & right_surfaces:
                continue
            containment = 0.0
            if left_name in right_name or right_name in left_name:
                containment = min(len(left_name), len(right_name)) / max(len(left_name), len(right_name))
            sequence = difflib.SequenceMatcher(None, left_name, right_name).ratio()
            similarity = max(containment, sequence)
            if similarity < threshold:
                continue
            left_books = _entity_books(store, left["entity_id"])
            right_books = _entity_books(store, right["entity_id"])
            shared_books = sorted(set(left_books) & set(right_books))
            # Identical or nearly identical names are the only candidates that
            # should ever be considered for automatic merge. Everything else is
            # explicitly review-only.
            relation = "containment" if containment else "near_duplicate"
            candidates.append(
                {
                    "left": {
                        "entity_id": left["entity_id"],
                        "canonical_name": left["canonical_name"],
                        "aliases": left.get("aliases", []),
                        "book_count": left.get("book_count", 0),
                    },
                    "right": {
                        "entity_id": right["entity_id"],
                        "canonical_name": right["canonical_name"],
                        "aliases": right.get("aliases", []),
                        "book_count": right.get("book_count", 0),
                    },
                    "similarity": round(similarity, 3),
                    "relation": relation,
                    "shared_books": shared_books,
                    "shared_book_count": len(shared_books),
                    "action": "review_only",
                    "reason": (
                        "One name contains the other; check whether they are the same concept "
                        "or a broader/narrower pair before merging."
                    ) if relation == "containment" else (
                        "Names are lexically close; check definitions and book passages before merging."
                    ),
                }
            )
    candidates.sort(key=lambda item: (-item["similarity"], -item["shared_book_count"], item["left"]["canonical_name"]))
    candidates = candidates[:limit]
    return {
        "audit_version": "1",
        "threshold": threshold,
        "candidate_count": len(candidates),
        "candidates": candidates,
        "note": "Audit output is advisory. No entity was merged automatically.",
    }


def detect_entities(store: Store, text: str, limit: int = 12) -> list[dict[str, Any]]:
    if not text.strip():
        return []
    rows = store.list_entities(limit=500)
    scored: list[tuple[float, dict[str, Any]]] = []
    lowered = text.lower()
    for entity in rows:
        aliases = [entity["canonical_name"], *entity.get("aliases", [])]
        matches = _match_aliases(lowered, aliases)
        if not matches:
            continue
        unique_matches: dict[str, float] = {}
        for alias, confidence in matches:
            unique_matches[alias] = max(unique_matches.get(alias, 0.0), confidence)
        score = sum(confidence * (1.0 + 0.05 * min(len(alias), 12)) for alias, confidence in unique_matches.items())
        item = dict(entity)
        item["matched_surfaces"] = sorted(unique_matches, key=len, reverse=True)
        item["match_score"] = round(score, 3)
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], -pair[1].get("book_count", 0), pair[1]["canonical_name"]))
    return [item for _, item in scored[:limit]]


def related_entities(store: Store, entity_ids: list[str], limit: int = 12) -> list[dict[str, Any]]:
    if not entity_ids:
        return []
    placeholders = ",".join("?" for _ in entity_ids)
    rows = store.conn.execute(
        f"SELECT * FROM entity_relations WHERE src_entity_id IN ({placeholders}) OR dst_entity_id IN ({placeholders}) "
        "ORDER BY weight DESC LIMIT ?",
        [*entity_ids, *entity_ids, limit],
    ).fetchall()
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        item = dict(row)
        other = item["dst_entity_id"] if item["src_entity_id"] in entity_ids else item["src_entity_id"]
        if other in seen or other in entity_ids:
            continue
        seen.add(other)
        name = store.conn.execute("SELECT canonical_name FROM entities WHERE entity_id = ?", (other,)).fetchone()
        item["entity_id"] = other
        item["canonical_name"] = name["canonical_name"] if name else other
        result.append(item)
    return result


# ---- entity merge review queue -----------------------------------------
def sync_merge_candidates(store: Store, threshold: float = 0.62, limit: int = 50) -> dict[str, Any]:
    """Persist the advisory audit output as an explicit review queue.

    ``align_entities`` itself never merges near-duplicates. This function only
    records candidates so a user or agent can accept/reject them later.
    """
    audit = alignment_audit(store, threshold=threshold, limit=limit)
    count = store.upsert_entity_merge_candidates(audit["candidates"])
    return {
        **audit,
        "persisted": count,
        "queue": store.list_entity_merge_candidates(limit=limit),
    }


def merge_entity_candidate(store: Store, candidate_id: str, note: str = "", confirm: bool = False) -> dict[str, Any]:
    if not confirm:
        raise ValueError("merging entities is irreversible without a snapshot; pass confirm=true after reviewing both entities")
    candidate = store.get_entity_merge_candidate(candidate_id)
    if not candidate:
        raise ValueError(f"unknown candidate_id: {candidate_id}")
    if candidate["status"] != "pending":
        raise ValueError(f"candidate is already {candidate['status']}")
    left = store.get_entity(candidate["left_id"])
    right = store.get_entity(candidate["right_id"])
    if not left or not right:
        raise ValueError("one of the entities no longer exists; rerun the audit")
    # Prefer the entity with more evidence; tie-break on the longer canonical name.
    keep, drop = (left, right) if (len(left["mentions"]), len(left["canonical_name"])) >= (len(right["mentions"]), len(right["canonical_name"])) else (right, left)
    keep_id, drop_id = keep["entity_id"], drop["entity_id"]
    keep_aliases_before = list(keep.get("aliases", []))
    drop_names = [drop["canonical_name"], *drop.get("aliases", [])]
    merged_aliases = sorted(set(keep_aliases_before) | {name for name in drop_names if name and name != keep["canonical_name"]})
    keep_relations_before = [
        {
            "src_entity_id": row["src_entity_id"],
            "dst_entity_id": row["dst_entity_id"],
            "relation": row["relation"],
            "weight": row["weight"],
            "evidence": row["evidence"],
        }
        for row in store.conn.execute(
            "SELECT * FROM entity_relations WHERE src_entity_id = ? OR dst_entity_id = ?",
            (keep_id, keep_id),
        ).fetchall()
    ]
    drop_relations = [
        {
            "src_entity_id": row["src_entity_id"],
            "dst_entity_id": row["dst_entity_id"],
            "relation": row["relation"],
            "weight": row["weight"],
            "evidence": _loads_json(row["evidence"]),
        }
        for row in store.conn.execute(
            "SELECT * FROM entity_relations WHERE src_entity_id = ? OR dst_entity_id = ?",
            (drop_id, drop_id),
        ).fetchall()
    ]
    moved_claims = [
        row["claim_id"] for row in store.conn.execute(
            "SELECT claim_id FROM claims WHERE subject_entity_id = ?", (drop_id,)
        ).fetchall()
    ]
    snapshot = {
        "keep_id": keep_id,
        "drop_entity": dict(drop),
        "drop_mentions": [
            {"chunk_id": item["chunk_id"], "book_id": item["book_id"], "surface": item["surface"], "confidence": item["confidence"]}
            for item in drop["mentions"]
        ],
        "keep_aliases_before": keep_aliases_before,
        "keep_relations_before": keep_relations_before,
        "drop_relations": drop_relations,
        "moved_claim_ids": moved_claims,
    }
    try:
        store.conn.execute(
            "UPDATE entities SET aliases = ?, summary = ? WHERE entity_id = ?",
            (_json_dump(merged_aliases), f"merged from {drop['canonical_name']} by explicit review", keep_id),
        )
        for mention in drop["mentions"]:
            store.conn.execute(
                "INSERT OR IGNORE INTO entity_mentions (entity_id, chunk_id, book_id, surface, confidence) VALUES (?, ?, ?, ?, ?)",
                (keep_id, mention["chunk_id"], mention["book_id"], mention["surface"], mention["confidence"]),
            )
        store.conn.execute("DELETE FROM entity_mentions WHERE entity_id = ?", (drop_id,))
        store.conn.execute("DELETE FROM entity_relations WHERE src_entity_id = ? OR dst_entity_id = ?", (drop_id, drop_id))
        for relation in drop_relations:
            other = relation["dst_entity_id"] if relation["src_entity_id"] == drop_id else relation["src_entity_id"]
            if other == keep_id:
                continue
            src, dst = (keep_id, other) if relation["src_entity_id"] == drop_id else (other, keep_id)
            store.conn.execute(
                "INSERT OR IGNORE INTO entity_relations (src_entity_id, dst_entity_id, relation, weight, evidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (src, dst, relation["relation"], relation["weight"], _json_dump(relation["evidence"]), utc_now()),
            )
        store.conn.execute("UPDATE claims SET subject_entity_id = ?, updated_at = ? WHERE subject_entity_id = ?", (keep_id, utc_now(), drop_id))
        store.conn.execute("DELETE FROM entities WHERE entity_id = ?", (drop_id,))
        store.conn.commit()
    except Exception:
        store.conn.rollback()
        raise
    updated = store.set_entity_merge_candidate(candidate_id, "accepted", note or f"merged {drop['canonical_name']} into {keep['canonical_name']}", snapshot)
    return {"candidate": updated, "kept": keep_id, "dropped": drop_id, "merged_aliases": merged_aliases}


def undo_entity_merge(store: Store, candidate_id: str, note: str = "") -> dict[str, Any]:
    candidate = store.get_entity_merge_candidate(candidate_id)
    if not candidate:
        raise ValueError(f"unknown candidate_id: {candidate_id}")
    if candidate["status"] != "accepted":
        raise ValueError("only an accepted merge can be undone")
    snapshot = candidate.get("snapshot") or {}
    keep_id = snapshot.get("keep_id", "")
    drop_entity = snapshot.get("drop_entity") or {}
    drop_id = drop_entity.get("entity_id", "")
    if not keep_id or not drop_id:
        raise ValueError("candidate snapshot is incomplete")
    try:
        store.conn.execute(
            "INSERT OR REPLACE INTO entities (entity_id, canonical_name, entity_type, aliases, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                drop_id, drop_entity.get("canonical_name", ""), drop_entity.get("entity_type", "concept"),
                _json_dump(drop_entity.get("aliases", [])), drop_entity.get("summary", ""), drop_entity.get("created_at", utc_now()),
            ),
        )
        for mention in snapshot.get("drop_mentions", []):
            store.conn.execute(
                "DELETE FROM entity_mentions WHERE entity_id = ? AND chunk_id = ? AND surface = ?",
                (keep_id, mention["chunk_id"], mention["surface"]),
            )
            store.conn.execute(
                "INSERT OR IGNORE INTO entity_mentions (entity_id, chunk_id, book_id, surface, confidence) VALUES (?, ?, ?, ?, ?)",
                (drop_id, mention["chunk_id"], mention["book_id"], mention["surface"], mention["confidence"]),
            )
        store.conn.execute("UPDATE entities SET aliases = ? WHERE entity_id = ?", (_json_dump(snapshot.get("keep_aliases_before", [])), keep_id))
        store.conn.execute("DELETE FROM entity_relations WHERE src_entity_id = ? OR dst_entity_id = ?", (keep_id, keep_id))
        for relation in snapshot.get("keep_relations_before", []):
            store.conn.execute(
                "INSERT OR IGNORE INTO entity_relations (src_entity_id, dst_entity_id, relation, weight, evidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (relation["src_entity_id"], relation["dst_entity_id"], relation["relation"], relation["weight"], _json_dump(relation["evidence"]), utc_now()),
            )
        for relation in snapshot.get("drop_relations", []):
            store.conn.execute(
                "INSERT OR IGNORE INTO entity_relations (src_entity_id, dst_entity_id, relation, weight, evidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (relation["src_entity_id"], relation["dst_entity_id"], relation["relation"], relation["weight"], _json_dump(relation["evidence"]), utc_now()),
            )
        for claim_id in snapshot.get("moved_claim_ids", []):
            store.conn.execute("UPDATE claims SET subject_entity_id = ?, updated_at = ? WHERE claim_id = ?", (drop_id, utc_now(), claim_id))
        store.conn.commit()
    except Exception:
        store.conn.rollback()
        raise
    updated = store.set_entity_merge_candidate(candidate_id, "reverted", note or "merged entity restored from snapshot")
    return {"candidate": updated, "restored": drop_id, "kept": keep_id}


def _json_dump(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _loads_json(value: Any) -> Any:
    import json

    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return []
