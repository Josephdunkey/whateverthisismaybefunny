from __future__ import annotations

import re

from .models import BookCard, CompileResult, Evidence, FrameworkCard, ValidationIssue, utc_now
from .store import Store
from .utils import dedupe_keep_order, normalize_text, split_sentences, stable_id
from .validation import find_quote, validate_book_card, validate_framework_card

LENS_KEYWORDS = {
    "economics": ["price", "incentive", "cost", "market", "capital", "credit", "investment", "supply", "demand", "经济", "价格", "成本", "激励", "投资"],
    "politics": ["coalition", "veto", "government", "political", "implementation", "power", "legitimacy", "政治", "联盟", "政府", "权力"],
    "law": ["law", "legal", "court", "statutory", "jurisdiction", "regulator", "authority", "liability", "rights", "法律", "法院", "监管", "权限", "责任"],
}

TRIGGER_WORDS = {
    "when", "if", "unless", "must", "should", "avoid", "risk", "framework", "principle",
    "checklist", "condition", "however", "but", "therefore", "asks", "separate",
    "当", "如果", "除非", "必须", "应该", "避免", "风险", "框架", "原则", "条件", "但是", "因此",
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "when", "then", "than", "that", "this", "these", "those",
    "is", "are", "was", "were", "be", "been", "being", "to", "of", "in", "on", "for", "with", "as", "by",
    "it", "its", "not", "no", "can", "may", "must", "should", "will", "would", "could", "from", "at",
    "we", "you", "they", "he", "she", "they", "their", "our", "your", "what", "which", "who", "how",
}


def infer_lenses(text: str) -> list[str]:
    lowered = text.lower()
    result = []
    for lens, words in LENS_KEYWORDS.items():
        if any(word in lowered for word in words):
            result.append(lens)
    return result or ["general"]


def _has_trigger(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(word in lowered for word in TRIGGER_WORDS)


def _pick(sentences: list[str], patterns: list[str], limit: int = 3) -> list[str]:
    picked = [s for s in sentences if any(p in s.lower() for p in patterns)]
    return dedupe_keep_order(picked)[:limit]


def _key_concepts(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
    counts: dict[str, int] = {}
    for word in words:
        if word in STOPWORDS:
            continue
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [word for word, _ in ranked[:limit]]


def _evidence(book_id: str, chunk, sentence: str) -> Evidence:
    return Evidence(
        book_id=book_id,
        quote=sentence,
        chunk_id=chunk.chunk_id,
        chapter=chunk.chapter_title,
        page=chunk.page_start,
    )


def _heuristic_book_card(store: Store, book: dict, chunks: list) -> BookCard:
    all_text = "\n".join(chunk.text for chunk in chunks)
    sentences = [s for chunk in chunks for s in split_sentences(chunk.text)]
    first_sentence = sentences[0] if sentences else ""
    chapter_coverage = []
    for chunk in chunks:
        chapter_sentences = split_sentences(chunk.text)
        if not chapter_sentences:
            continue
        summary = chapter_sentences[0]
        chapter_coverage.append(
            {
                "chapter": chunk.chapter_title,
                "summary": summary,
                "citation": _evidence(book["book_id"], chunk, summary).to_dict(),
            }
        )
    return BookCard(
        book_id=book["book_id"],
        title=book["title"],
        author=book["author"],
        one_line_thesis=first_sentence or f"{book['title']} develops a framework for policy analysis.",
        core_questions=_pick(sentences, ["asks", "question", "问题", "?"], 4),
        key_concepts=_key_concepts(all_text),
        assumptions=_pick(sentences, ["when", "if", "assume", "前提", "假设"], 4),
        limitations=_pick(sentences, ["but", "however", "unless", "risk", "limitation", "但是", "风险", "局限"], 4),
        best_for=[chunk.chapter_title for chunk in chunks][:6],
        not_for=["Questions that require facts outside the library"],
        chapter_coverage=chapter_coverage,
        lenses=infer_lenses(all_text),
        confidence="low",
        status="heuristic",
    )


def _heuristic_frameworks(store: Store, book: dict, chunks: list) -> list[FrameworkCard]:
    frameworks: list[FrameworkCard] = []
    for chunk in chunks:
        sentences = split_sentences(chunk.text)
        if not sentences:
            continue
        trigger_sentences = [s for s in sentences if _has_trigger(s) and len(s) >= 30]
        if not trigger_sentences:
            continue
        name = f"{chunk.chapter_title}: decision framework"
        applicable = _pick(sentences, ["when", "if", "unless", "当", "如果", "除非"], 4)
        steps = _pick(sentences, ["must", "should", "asks", "separate", "build", "reduce", "必须", "应该", "需要"], 4)
        failure = _pick(sentences, ["unless", "but", "however", "risk", "cannot", "stall", "除非", "但是", "风险", "不能"], 4)
        if not applicable:
            applicable = [trigger_sentences[0]]
        if not steps:
            steps = [trigger_sentences[0]]
        if not failure:
            failure = ["The framework does not apply when its stated conditions are absent."]
        citation_sentences = dedupe_keep_order(trigger_sentences[:2] + applicable[:1] + failure[:1])
        citations = []
        for sentence in citation_sentences:
            found = find_quote(sentence, [chunk])
            if found:
                citations.append(_evidence(book["book_id"], found, sentence))
        if not citations:
            continue
        framework = FrameworkCard(
            framework_id=stable_id(book["book_id"], chunk.chunk_id, name),
            book_id=book["book_id"],
            name=name,
            one_liner=trigger_sentences[0],
            lenses=infer_lenses(chunk.text),
            applicable_when=applicable,
            inputs=["A concrete event or decision", "The conditions named in the source"],
            steps=steps,
            outputs=["A conditional judgment with supporting evidence and failure modes"],
            failure_modes=failure,
            counterexamples=[],
            citations=citations,
            related_frameworks=[],
            confidence="low",
            status="heuristic",
        )
        frameworks.append(framework)
    return frameworks


def compile_book(store: Store, book_id: str, patch: dict | None = None) -> CompileResult:
    book = store.get_book(book_id)
    if not book:
        raise ValueError(f"Unknown book_id: {book_id}")
    chunks = store.get_chunks(book_id)
    if not chunks:
        raise ValueError(f"Book has no chunks: {book_id}")
    if patch:
        book_card = dict(patch.get("book_card") or {})
        frameworks_data = [dict(item) for item in (patch.get("frameworks") or [])]
        book_card.setdefault("book_id", book_id)
        book_card.setdefault("title", book["title"])
        book_card.setdefault("author", book["author"])
        for framework in frameworks_data:
            framework.setdefault("framework_id", stable_id(book_id, framework.get("name", ""), framework.get("one_liner", "")))
            framework.setdefault("book_id", book_id)
            framework.setdefault("status", "draft")
            framework.setdefault("confidence", "medium")
            framework.setdefault("related_frameworks", [])
        issues: list[ValidationIssue] = []
        if not book_card:
            issues.append(ValidationIssue("error", "missing_book_card", "Patch has no book_card"))
        else:
            issues.extend(validate_book_card(book_card, chunks))
        if not frameworks_data:
            issues.append(ValidationIssue("error", "missing_frameworks", "Patch has no framework cards"))
        for framework in frameworks_data:
            issues.extend(validate_framework_card(framework, chunks))
        if any(issue.severity == "error" for issue in issues):
            placeholder = BookCard(
                book_id=book_id,
                title=book["title"],
                author=book["author"],
                one_line_thesis="",
                core_questions=[],
                key_concepts=[],
                assumptions=[],
                limitations=[],
                best_for=[],
                not_for=[],
                chapter_coverage=[],
                lenses=[],
                confidence="low",
                status="draft",
            )
            return CompileResult(book_id, placeholder, [], issues)
        book_card_obj = BookCard(**book_card)
        framework_objs = []
        for framework in frameworks_data:
            citations = [Evidence(**citation) if isinstance(citation, dict) else citation for citation in framework.get("citations", [])]
            framework["citations"] = citations
            framework_objs.append(FrameworkCard(**framework))
    else:
        book_card_obj = _heuristic_book_card(store, book, chunks)
        framework_objs = _heuristic_frameworks(store, book, chunks)
        issues = validate_book_card(book_card_obj.to_dict(), chunks)
        for framework in framework_objs:
            issues.extend(validate_framework_card(framework.to_dict(), chunks))
    store.save_book_card(book_id, book_card_obj.to_dict())
    store.replace_frameworks(book_id, [framework.to_dict() for framework in framework_objs])
    for framework in framework_objs:
        store.add_edge("book", book_id, "framework", framework.framework_id, "contains")
        for citation in framework.citations:
            store.add_edge("framework", framework.framework_id, "chunk", citation.chunk_id, "cites", [citation.to_dict()])
        for concept in book_card_obj.key_concepts[:5]:
            store.add_edge("framework", framework.framework_id, "concept", concept, "about")
    try:
        from .entities import align_entities
        align_entities(store)
    except Exception as exc:  # entity alignment must not invalidate a valid compile
        issues.append(ValidationIssue("warning", "entity_alignment_failed", str(exc), book_id))
    return CompileResult(book_id, book_card_obj, framework_objs, issues)
