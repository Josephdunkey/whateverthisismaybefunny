"""Claim-level knowledge graph with conservative conflict and supersession handling.

A claim is a sentence-level assertion extracted from a learned book, linked to
its exact chunk and page.  Conflicts are surfaced, never silently resolved.
Supersession only happens through an explicit, confirmed call: a newer source
does not automatically invalidate an older one.
"""
from __future__ import annotations

import difflib
import re
from datetime import date
from typing import Any, Iterable

from .entities import detect_entities
from .models import utc_now
from .store import Store
from .utils import normalize_text, split_sentences, stable_id

MARKERS: list[tuple[str, str]] = [
    ("is caused by", "causes"),
    ("are caused by", "causes"),
    ("caused by", "causes"),
    ("leads to", "causes"),
    ("lead to", "causes"),
    ("results in", "causes"),
    ("result in", "causes"),
    ("depends on", "depends_on"),
    ("requires", "requires"),
    ("increases", "increases"),
    ("raises", "increases"),
    ("reduces", "reduces"),
    ("decreases", "reduces"),
    ("lowers", "reduces"),
    ("constrains", "constrains"),
    ("limits", "constrains"),
    ("promotes", "promotes"),
    ("supports", "supports"),
    ("only if", "only_if"),
    ("不一定导致", "causes"),
    ("未必导致", "causes"),
    ("不会导致", "causes"),
    ("没有导致", "causes"),
    ("并不导致", "causes"),
    ("导致了", "causes"),
    ("导致", "causes"),
    ("使得", "causes"),
    ("引起", "causes"),
    ("造成", "causes"),
    ("取决于", "depends_on"),
    ("意味着", "implies"),
    ("必然", "necessarily"),
    ("推动", "promotes"),
    ("促进", "promotes"),
    ("抑制", "restrains"),
    ("限制", "constrains"),
    ("提高", "increases"),
    ("增加", "increases"),
    ("降低", "reduces"),
    ("减少", "reduces"),
    ("要求", "requires"),
    ("需要", "requires"),
    ("支持", "supports"),
    ("只有", "only_if"),
    ("如果", "if"),
    ("当", "when"),
]

NEGATIONS = ("不", "未", "没", "无", "非", "莫", "勿")

# Predicates are grouped into comparable families. "提高" and "降低" are the
# same family with opposite direction, so a cross-book pair can be surfaced as
# a conflict instead of being hidden by different surface verbs.
PREDICATE_FAMILY = {
    "causes": "causes",
    "necessarily": "causes",
    "increases": "increase",
    "reduces": "increase",
    "promotes": "increase",
    "restrains": "increase",
    "constrains": "increase",
    "requires": "requires",
    "only_if": "requires",
    "depends_on": "depends",
    "implies": "implies",
    "supports": "implies",
    "if": "condition",
    "when": "condition",
}
REVERSED = {"reduces", "restrains", "constrains"}


def _norm(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", normalize_text(value).lower())


def _entity_surfaces(store: Store) -> list[tuple[str, dict[str, Any]]]:
    surfaces: list[tuple[str, dict[str, Any]]] = []
    for entity in store.list_entities(limit=1000):
        names = [entity.get("canonical_name", ""), *entity.get("aliases", [])]
        for name in names:
            name = str(name or "").strip()
            if len(name) >= 2:
                surfaces.append((name, entity))
    surfaces.sort(key=lambda pair: (-len(pair[0]), pair[0]))
    return surfaces


def _match_subject(sentence: str, surfaces: list[tuple[str, dict[str, Any]]]) -> tuple[str, str]:
    lowered = sentence.lower()
    for surface, entity in surfaces:
        if surface.lower() in lowered:
            return entity["canonical_name"], entity["entity_id"]
    return "", ""


def _find_marker(sentence: str) -> tuple[str, str, int, int] | None:
    best: tuple[str, str, int, int] | None = None
    lowered = sentence.lower()
    for marker, predicate in MARKERS:
        index = lowered.find(marker.lower())
        if index < 0:
            continue
        polarity = 1
        prefix = sentence[max(0, index - 8):index]
        if any(character in prefix[-2:] for character in NEGATIONS):
            polarity = -1
        if any(word in prefix.lower() for word in ("not ", "n't ", "no ")):
            polarity = -1
        if marker in {phrase for phrase, _ in MARKERS[:5]}:
            polarity = -1
        if best is None or index < best[2] or (index == best[2] and len(marker) > len(best[0])):
            best = (marker, predicate, index, polarity)
    return best


BOILERPLATE_MARKERS = (
    "目录", "索引", "参见", "版权页", "ISBN", "版权所有", "定价", "责任编辑",
    "封面设计", "出版社", "http://", "https://", "www.", "习题", "思考题",
    "参考文献", "签字", "盖章", "学号", "班级", "授课教师", "教学大纲",
    "开本", "印张", "版次", "印次", "上机", "实验报告",
)

SUBJECT_STOPWORDS = (
    "为了", "本书", "本教材", "授课", "教学", "主编", "著", "表", "图",
    "本章", "本编", "全书", "教材",
)


def _plausible(sentence: str) -> bool:
    """Reject table rows, front matter, and OCR boilerplate.

    Rule-based extraction is intentionally conservative.  A false negative
    costs one candidate; a false positive pollutes the knowledge graph and is
    much harder to remove later.
    """
    compact = re.sub(r"\s+", "", sentence)
    if len(compact) < 16 or len(compact) > 260:
        return False
    digits = sum(compact.count(character) for character in "0123456789")
    if digits / max(len(compact), 1) > 0.22:
        return False
    if any(marker in compact for marker in BOILERPLATE_MARKERS):
        return False
    # A table-of-contents row or a form field has an unusual punctuation
    # density.  Ordinary prose stays well below this threshold.
    punctuation = sum(compact.count(character) for character in "，。；：、")
    if punctuation / max(len(compact), 1) > 0.12:
        return False
    if compact.count("…") >= 3 or compact.count("...") >= 2:
        return False
    if compact.endswith(("：", ":", "；")):
        return False
    if compact.count("|") >= 2:
        return False
    return True


def extract_claims(store: Store, book_id: str, limit: int = 120, surfaces: list[tuple[str, dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    surfaces = surfaces if surfaces is not None else _entity_surfaces(store)
    claims: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in store.get_chunks(book_id):
        for sentence in split_sentences(chunk.text):
            if not _plausible(sentence):
                continue
            found = _find_marker(sentence)
            if found is None:
                continue
            marker, predicate, index, polarity = found
            subject, entity_id = _match_subject(sentence, surfaces)
            if not subject:
                prefix = normalize_text(sentence[:index]).strip("，。；：、 ")
                if re.search(r"[A-Za-z]", prefix):
                    if len(prefix) > 60 or "," in prefix or ";" in prefix:
                        continue
                    if prefix.lower().startswith((
                        "if ", "when ", "whether ", "while ", "although ", "because ",
                        "since ", "during ", "after ", "before ", "under ", "without ",
                        "in ", "for ", "with ", "as ",
                    )):
                        continue
                elif len(prefix) > 24:
                    continue
                if len(prefix) < 2:
                    continue
                if any(character in prefix for character in "，。；：、|"):
                    continue
                if prefix.startswith(SUBJECT_STOPWORDS):
                    continue
                subject = re.sub(r"^(the|a|an)\s+", "", prefix, flags=re.IGNORECASE)
            remainder = normalize_text(sentence[index + len(marker):]).strip("，。；：、 ")
            if len(remainder) < 4:
                remainder = normalize_text(sentence)
            subject_norm = _norm(subject)
            object_norm = _norm(remainder)[:100]
            family = PREDICATE_FAMILY.get(predicate, predicate)
            direction = -1 if predicate in REVERSED else 1
            polarity *= direction
            base_key = f"{subject_norm}|{family}"
            claim_key = f"{base_key}|{object_norm}|{polarity}"
            if claim_key in seen:
                continue
            seen.add(claim_key)
            claim_id = stable_id("claim", book_id, chunk.chunk_id, sentence[:80])
            claims.append(
                {
                    "claim_id": claim_id,
                    "claim_key": claim_key,
                    "base_key": base_key,
                    "subject": subject,
                    "subject_entity_id": entity_id,
                    "predicate": family,
                    "object": remainder[:400],
                    "polarity": polarity,
                    "conditions": [],
                    "book_id": book_id,
                    "chunk_id": chunk.chunk_id,
                    "page": chunk.page_start,
                    "quote": sentence,
                    "valid_from": None,
                    "valid_to": None,
                    "status": "active",
                    "resolution": "",
                    "confidence": round(min(0.92, 0.58 + (0.12 if entity_id else 0.0) + (0.06 if len(remainder) > 12 else 0.0)), 3),
                }
            )
            if len(claims) >= limit:
                return claims
    return claims


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return difflib.SequenceMatcher(None, left, right).ratio()


def detect_conflicts(store: Store, limit: int = 400) -> dict[str, Any]:
    """Mark cross-book, opposite-polarity claims as conflicts for review."""
    store.conn.execute("DELETE FROM claim_relations WHERE relation = 'contradicts' AND note LIKE 'auto:%'")
    store.conn.execute(
        "UPDATE claims SET status = 'active' WHERE status = 'conflicted' "
        "AND TRIM(COALESCE(resolution, '')) = ''"
    )
    store.conn.commit()
    rows = [
        dict(row) for row in store.conn.execute(
            "SELECT claim_id, base_key, subject, predicate, object, polarity, book_id, quote, resolution FROM claims "
            "WHERE status NOT IN ('superseded', 'retracted') ORDER BY base_key, book_id"
        ).fetchall()
    ]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["base_key"], []).append(row)
    created = 0
    pairs: set[tuple[str, str]] = set()
    for base_key, items in grouped.items():
        for index, left in enumerate(items):
            for right in items[index + 1:]:
                if left["book_id"] == right["book_id"]:
                    continue
                # A human/agent decision to keep two views must survive a
                # rebuild; otherwise dismissed conflicts reappear forever.
                if left.get("resolution") or right.get("resolution"):
                    continue
                if int(left["polarity"]) == int(right["polarity"]):
                    continue
                if _similarity(_norm(left["object"]), _norm(right["object"])) < 0.45:
                    continue
                pair = tuple(sorted((left["claim_id"], right["claim_id"])))
                if pair in pairs:
                    continue
                pairs.add(pair)
                store.add_claim_relation(
                    pair[0], pair[1], "contradicts", 0.6,
                    "auto:same subject/predicate, opposite polarity, similar object; needs review",
                )
                store.conn.execute(
                    "UPDATE claims SET status = 'conflicted', updated_at = ? WHERE claim_id IN (?, ?) "
                    "AND status = 'active' AND TRIM(COALESCE(resolution, '')) = ''",
                    (utc_now(), pair[0], pair[1]),
                )
                created += 1
                if created >= limit:
                    store.conn.commit()
                    return {"conflicts": created, "capped": True}
    store.conn.commit()
    return {"conflicts": created, "capped": False}


def build_claims(
    store: Store,
    book_ids: Iterable[str] | None = None,
    limit_per_book: int = 120,
    replace: bool = True,
) -> dict[str, Any]:
    learned = set(store.learned_book_ids())
    requested = list(book_ids or learned)
    allowed = [book_id for book_id in requested if book_id in learned]
    surfaces = _entity_surfaces(store)
    per_book: dict[str, int] = {}
    for book_id in allowed:
        claims = extract_claims(store, book_id, limit=limit_per_book, surfaces=surfaces)
        if replace:
            count = store.replace_claims(book_id, claims)
        else:
            now = utc_now()
            count = 0
            for claim in claims:
                store.conn.execute(
                    "INSERT OR IGNORE INTO claims (claim_id, claim_key, base_key, subject, subject_entity_id, predicate, "
                    "object, polarity, conditions, book_id, chunk_id, page, quote, status, confidence, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, ?, ?, 'active', ?, ?, ?)",
                    (
                        claim["claim_id"], claim["claim_key"], claim["base_key"], claim["subject"],
                        claim["subject_entity_id"], claim["predicate"], claim["object"], claim["polarity"],
                        book_id, claim["chunk_id"], claim["page"], claim["quote"], claim["confidence"], now, now,
                    ),
                )
                count += 1
            store.conn.commit()
        per_book[book_id] = count
    conflicts = detect_conflicts(store)
    return {
        "books": per_book,
        "claims": sum(per_book.values()),
        "conflicts": conflicts,
        "stats": store.claim_stats(),
    }


def list_claims(store: Store, query: str = "", book_id: str = "", status: str = "", limit: int = 100) -> dict[str, Any]:
    return {
        "claims": store.list_claims(query=query, book_id=book_id, status=status, limit=limit),
        "stats": store.claim_stats(),
    }


def supersede_claim(store: Store, old_claim_id: str, new_claim_id: str, note: str = "", confirm: bool = False, force: bool = False) -> dict[str, Any]:
    if not confirm:
        raise ValueError("supersession is a write operation; pass confirm=true after reviewing both claims")
    old = store.get_claim(old_claim_id)
    new = store.get_claim(new_claim_id)
    if not old or not new:
        raise ValueError("both old_claim_id and new_claim_id must exist")
    if old_claim_id == new_claim_id:
        raise ValueError("a claim cannot supersede itself")
    if not force and (old["base_key"] != new["base_key"]):
        raise ValueError("claims have different subject/predicate; pass force=true only after explicit review")
    today = date.today().isoformat()
    store.add_claim_relation(new_claim_id, old_claim_id, "supersedes", 0.9, note or "explicit user/agent confirmation")
    store.set_claim_status(old_claim_id, "superseded", note or "superseded by explicit decision", valid_to=today)
    store.set_claim_status(new_claim_id, "active", note or "current claim after explicit supersession")
    return {
        "old": store.get_claim(old_claim_id),
        "new": store.get_claim(new_claim_id),
        "note": note,
    }


def dismiss_conflict(store: Store, left_claim_id: str, right_claim_id: str, note: str = "") -> dict[str, Any]:
    pair = tuple(sorted((left_claim_id, right_claim_id)))
    store.conn.execute(
        "DELETE FROM claim_relations WHERE relation = 'contradicts' AND "
        "((src_claim_id = ? AND dst_claim_id = ?) OR (src_claim_id = ? AND dst_claim_id = ?))",
        (pair[0], pair[1], pair[1], pair[0]),
    )
    for claim_id in pair:
        store.conn.execute(
            "UPDATE claims SET status = 'active', resolution = ?, updated_at = ? WHERE claim_id = ? AND status = 'conflicted'",
            (note or "reviewed: both claims kept as different views", utc_now(), claim_id),
        )
    store.conn.commit()
    return {"dismissed": pair, "note": note, "claims": [store.get_claim(pair[0]), store.get_claim(pair[1])]}