from __future__ import annotations

from typing import Any

from .evolution import get_evolution_config
from .models import SelectionProposal
from .source_gaps import recommend_sources
from .store import Store, query_terms


def _term_score(text: str, terms: list[str]) -> float:
    lowered = (text or "").lower()
    score = 0.0
    for term in terms:
        if term:
            score += min(lowered.count(term), 5)
    return score


def _group_top_hits(hits: list[dict[str, Any]], per_book: int = 3) -> dict[str, list[dict[str, Any]]]:
    """Group a batch retrieval result into at most ``per_book`` hits per book."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        book_id = str(hit.get("book_id", ""))
        if not book_id:
            continue
        bucket = grouped.setdefault(book_id, [])
        if len(bucket) < per_book:
            bucket.append(hit)
    return grouped


def _batch_hits(
    store: Store,
    query: str,
    book_ids: list[str],
    per_book: int = 3,
) -> dict[str, list[dict[str, Any]]]:
    """Retrieve one ranked pool and keep the top hits for every book.

    The previous implementation ran a full hybrid search once per book.  That
    is fine for four books and becomes unusable at a hundred.  One batched
    search keeps the same evidence shape while making selection scale with the
    library size instead of the square of it.  We over-fetch a little because
    a single verbose book can otherwise occupy the whole global top-N.
    """
    if not query.strip() or not book_ids:
        return {}
    pool_size = max(12, min(600, len(book_ids) * per_book * 4))
    hits = store.search_chunks(query, book_ids=list(book_ids), limit=pool_size)
    return _group_top_hits(hits, per_book=per_book)


def _direction_scores(store: Store, book_ids: list[str], direction: str) -> dict[str, float]:
    grouped = _batch_hits(store, direction, book_ids, per_book=3)
    return {
        book_id: sum(float(hit.get("score", 0.0)) for hit in hits)
        for book_id, hits in grouped.items()
    }


def _book_row(book: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "book_id": book["book_id"],
        "title": book["title"],
        "author": book["author"],
        "disciplines": book.get("disciplines", []),
        "status": book.get("status", "ingested"),
        "reason": reason,
    }


def _framework_row(framework: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "framework_id": framework["framework_id"],
        "book_id": framework.get("book_id", ""),
        "name": framework.get("name", "Untitled framework"),
        "one_liner": framework.get("one_liner", ""),
        "lenses": framework.get("lenses", []),
        "confidence": framework.get("confidence", "medium"),
        "status": framework.get("status", "draft"),
        "reason": reason,
    }


def select_books(
    store: Store,
    query: str,
    lenses: list[str],
    direction: str = "",
    limit: int = 8,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any], str]] = []
    preference = store.preference_weights().get("books", {})
    config = get_evolution_config(store)
    selection = config.get("selection", {})
    overrides = config.get("preference_overrides", {}).get("books", {})
    learned_ids = store.learned_book_ids()
    learned_books = [book for book in store.list_books() if book["book_id"] in learned_ids]
    candidate_ids = sorted(book["book_id"] for book in learned_books)
    hits_by_book = _batch_hits(store, query, candidate_ids, per_book=3)
    direction_by_book = _direction_scores(store, candidate_ids, direction)
    for book in learned_books:
        book_id = book["book_id"]
        # A compiled book with at least one framework is the only thing the
        # agent may present as "read". Ingested-only books stay visible in the
        # library UI but are not eligible for automatic analysis selection.
        lens_match = set(lenses).intersection(set(book.get("disciplines", [])))
        query_hits = hits_by_book.get(book_id, [])
        query_score = sum(float(hit.get("score", 0)) for hit in query_hits)
        direction_score = direction_by_book.get(book_id, 0.0)
        preference_score = min(float(preference.get(book_id, 0.0)) + float(overrides.get(book_id, 0.0)), 4.0)
        score = (
            float(selection.get("lens_weight", 3.0)) * len(lens_match)
            + query_score
            + float(selection.get("direction_weight", 2.0)) * direction_score
            + float(selection.get("preference_weight", 1.5)) * preference_score
        )
        if score <= 0 and not lens_match and not query_hits:
            continue
        reasons = []
        if lens_match:
            reasons.append("covers lenses: " + ", ".join(sorted(lens_match)))
        if query_hits:
            reasons.append(f"query match in {query_hits[0]['chapter_title']}")
        if direction_score:
            reasons.append("matches the requested direction")
        if preference_score:
            reasons.append("preferred in past feedback")
        scored.append((score, book, "; ".join(reasons) or "coverage fallback"))
    scored.sort(key=lambda item: (-item[0], item[1]["title"]))
    return [_book_row(book, reason) for _, book, reason in scored[:limit]]


def select_frameworks(
    store: Store,
    query: str,
    lenses: list[str],
    book_ids: list[str] | None = None,
    direction: str = "",
    limit: int = 8,
) -> list[dict[str, Any]]:
    query_term_list = query_terms(query)
    direction_term_list = query_terms(direction)
    preference = store.preference_weights().get("frameworks", {})
    config = get_evolution_config(store)
    selection = config.get("selection", {})
    overrides = config.get("preference_overrides", {}).get("frameworks", {})
    scored: list[tuple[float, dict[str, Any], str]] = []
    for framework in store.list_frameworks(book_ids=book_ids):
        framework_lenses = set(framework.get("lenses", []))
        lens_match = set(lenses).intersection(framework_lenses)
        text = " ".join(
            str(part)
            for part in [
                framework.get("name", ""),
                framework.get("one_liner", ""),
                " ".join(framework.get("applicable_when", [])),
                " ".join(framework.get("steps", [])),
                " ".join(framework.get("failure_modes", [])),
            ]
        )
        query_score = _term_score(text, query_term_list)
        direction_score = _term_score(text, direction_term_list)
        framework_id = framework.get("framework_id", "")
        preference_score = min(float(preference.get(framework_id, 0.0)) + float(overrides.get(framework_id, 0.0)), 4.0)
        score = (
            4.0 * len(lens_match)
            + query_score
            + float(selection.get("direction_weight", 2.0)) * direction_score
            + float(selection.get("preference_weight", 1.5)) * preference_score
        )
        if score <= 0 and not lens_match:
            continue
        reasons = []
        if lens_match:
            reasons.append("covers lenses: " + ", ".join(sorted(lens_match)))
        if query_score:
            reasons.append("matches the event language")
        if direction_score:
            reasons.append("matches the requested direction")
        if preference_score:
            reasons.append("preferred in past feedback")
        scored.append((score, framework, "; ".join(reasons) or "lens fallback"))
    scored.sort(key=lambda item: (-item[0], item[1].get("name", "")))
    return [_framework_row(framework, reason) for _, framework, reason in scored[:limit]]


def _coverage(books: list[dict[str, Any]], frameworks: list[dict[str, Any]], lenses: list[str]) -> tuple[set[str], list[str]]:
    covered: set[str] = set()
    for book in books:
        covered.update(book.get("disciplines", []))
    for framework in frameworks:
        covered.update(framework.get("lenses", []))
    return covered, [lens for lens in lenses if lens not in covered]


def _dedupe_frameworks(frameworks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({framework["framework_id"]: framework for framework in frameworks if framework.get("framework_id")}.values())


def build_proposal(
    store: Store,
    mode: str,
    query: str,
    lenses: list[str],
    book_ids: list[str] | None = None,
    framework_ids: list[str] | None = None,
    direction: str = "",
) -> SelectionProposal:
    mode = mode.lower().strip()
    if mode not in {"auto", "direction", "books"}:
        raise ValueError("mode must be one of: auto, direction, books")
    if mode == "direction" and not direction.strip():
        raise ValueError("direction mode requires a non-empty direction")
    if mode == "books" and not (book_ids or framework_ids):
        raise ValueError("books mode requires at least one book_id or framework_id")

    explicit_frameworks: list[dict[str, Any]] = []
    for framework_id in framework_ids or []:
        framework = store.get_framework(framework_id)
        if not framework:
            raise ValueError(f"Unknown framework_id: {framework_id}")
        explicit_frameworks.append(_framework_row(framework, "explicitly selected by the user"))

    if mode == "books":
        specified_books = []
        for book_id in book_ids or []:
            book = store.get_book(book_id)
            if not book:
                raise ValueError(f"Unknown book_id: {book_id}")
            specified_books.append(_book_row(book, "explicitly selected by the user"))
        specified_ids = {book["book_id"] for book in specified_books}
        for framework in explicit_frameworks:
            framework_book_id = framework.get("book_id", "")
            if framework_book_id and framework_book_id not in specified_ids:
                book = store.get_book(framework_book_id)
                if book:
                    specified_books.append(_book_row(book, "required by an explicitly selected framework"))
                    specified_ids.add(framework_book_id)
        recommended_books = [
            book for book in select_books(store, query, lenses, direction)
            if book["book_id"] not in specified_ids
        ]
        all_book_ids = sorted(specified_ids) + [book["book_id"] for book in recommended_books]
        recommended_frameworks = [
            framework for framework in select_frameworks(store, query, lenses, all_book_ids, direction)
            if framework["framework_id"] not in {item["framework_id"] for item in explicit_frameworks}
        ]
        specified_frameworks = explicit_frameworks
        requires_confirmation = True
        rationale = "You specified books or frameworks. The agent checked coverage and proposes additions for gaps."
    elif mode == "direction":
        candidates = select_books(store, query, lenses, direction)
        specified_books = [
            book for book in candidates
            if "matches the requested direction" in str(book.get("reason", ""))
        ]
        if not specified_books:
            specified_books = [book for book in candidates if set(lenses).intersection(set(book.get("disciplines", [])))]
        if not specified_books and candidates:
            specified_books = candidates[:1]
        specified_ids = {book["book_id"] for book in specified_books}
        recommended_books = [book for book in candidates if book["book_id"] not in specified_ids]
        specified_frameworks = select_frameworks(store, query, lenses, sorted(specified_ids), direction)
        if explicit_frameworks:
            specified_frameworks = _dedupe_frameworks(explicit_frameworks + specified_frameworks)
        specified_framework_ids = {framework["framework_id"] for framework in specified_frameworks}
        all_book_ids = sorted(specified_ids) + [book["book_id"] for book in recommended_books]
        recommended_frameworks = [
            framework for framework in select_frameworks(store, query, lenses, all_book_ids, direction)
            if framework["framework_id"] not in specified_framework_ids
        ]
        requires_confirmation = True
        rationale = "You specified a direction. The agent proposes direction-matched capabilities and cross-disciplinary additions."
    else:
        specified_books = []
        specified_frameworks = []
        recommended_books = select_books(store, query, lenses, direction)
        recommended_frameworks = select_frameworks(
            store,
            query,
            lenses,
            book_ids=[book["book_id"] for book in recommended_books] or None,
            direction=direction,
        )
        requires_confirmation = False
        rationale = "Automatic selection from the library."

    all_books = specified_books + recommended_books
    all_frameworks = specified_frameworks + recommended_frameworks
    _, gaps = _coverage(all_books, all_frameworks, lenses)
    source_recommendations = recommend_sources(store, query, lenses, direction)
    return SelectionProposal(
        mode=mode,
        query=query,
        lenses=lenses,
        direction=direction,
        specified_books=specified_books,
        specified_frameworks=specified_frameworks,
        recommended_books=recommended_books,
        recommended_frameworks=recommended_frameworks,
        coverage_gaps=gaps,
        requires_confirmation=requires_confirmation,
        options=["specified", "specified+recommended", "recommended"],
        rationale=rationale,
        source_recommendations=source_recommendations,
    )


def resolve_proposal(proposal: SelectionProposal, choice: str) -> dict[str, Any]:
    if choice not in proposal.options:
        raise ValueError(f"choice must be one of: {', '.join(proposal.options)}")
    if choice == "specified":
        books = proposal.specified_books
        frameworks = proposal.specified_frameworks
    elif choice == "recommended":
        books = proposal.recommended_books
        frameworks = proposal.recommended_frameworks
    else:
        books = proposal.specified_books + proposal.recommended_books
        frameworks = proposal.specified_frameworks + proposal.recommended_frameworks
    deduped_books = list({book["book_id"]: book for book in books}.values())
    deduped_frameworks = list({fw["framework_id"]: fw for fw in frameworks if fw.get("framework_id")}.values())
    return {"books": deduped_books, "frameworks": deduped_frameworks, "choice": choice}