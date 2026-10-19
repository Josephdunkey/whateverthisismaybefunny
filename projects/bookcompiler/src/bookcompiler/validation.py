from __future__ import annotations

from typing import Any, Iterable

from .models import Chunk, ValidationIssue
from .utils import normalize_for_quote


MIN_QUOTE_CHARS = 12


def find_quote(quote: str, chunks: Iterable[Chunk]) -> Chunk | None:
    normalized = normalize_for_quote(quote)
    if len(normalized) < MIN_QUOTE_CHARS:
        return None
    for chunk in list(chunks):
        if normalized in normalize_for_quote(chunk.text):
            return chunk
    return None


def validate_quote(quote: str, chunks: Iterable[Chunk]) -> bool:
    return find_quote(quote, chunks) is not None


def _citation_dict(citation: Any) -> dict[str, Any]:
    if isinstance(citation, dict):
        return citation
    if hasattr(citation, "to_dict"):
        return citation.to_dict()
    return {}


def _validate_citation(
    citation: Any,
    chunks: list[Chunk],
    location: str,
    strict_provenance: bool = False,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    item = _citation_dict(citation)
    quote = str(item.get("quote", ""))
    if not quote:
        return [ValidationIssue("error", "missing_quote", "Citation has no quote", location)]
    # Prefer the chunk the citation actually names.  OCR books often repeat a
    # paragraph (running headers, duplicated pages), and a global first-match
    # lookup would otherwise report a false provenance mismatch.
    cited_chunk_id = str(item.get("chunk_id") or "")
    found = None
    if cited_chunk_id:
        normalized = normalize_for_quote(quote)
        for chunk in chunks:
            if chunk.chunk_id == cited_chunk_id:
                if len(normalized) >= MIN_QUOTE_CHARS and normalized in normalize_for_quote(chunk.text):
                    found = chunk
                break
    if found is None:
        found = find_quote(quote, chunks)
    if not found:
        issues.append(ValidationIssue("error", "unsupported_quote", f"Quote not found in source: {quote[:80]}", location))
        return issues
    provenance_severity = "error" if strict_provenance else "warning"
    if item.get("chunk_id") and item.get("chunk_id") != found.chunk_id:
        issues.append(
            ValidationIssue(
                provenance_severity,
                "citation_chunk_mismatch",
                f"Citation chunk_id does not match the chunk containing the quote: {quote[:60]}",
                location,
            )
        )
    if item.get("chapter") and item.get("chapter") != found.chapter_title:
        issues.append(
            ValidationIssue(
                provenance_severity,
                "citation_chapter_mismatch",
                f"Citation chapter does not match source metadata: {quote[:60]}",
                location,
            )
        )
    if item.get("page") is not None and found.page_start is not None:
        page_end = found.page_end if found.page_end is not None else found.page_start
        try:
            page_number = int(item["page"])
        except (TypeError, ValueError):
            issues.append(
                ValidationIssue(
                    provenance_severity,
                    "invalid_citation_page",
                    f"Citation page is not an integer: {quote[:60]}",
                    location,
                )
            )
        else:
            if not (found.page_start <= page_number <= page_end):
                issues.append(
                    ValidationIssue(
                        provenance_severity,
                        "citation_page_mismatch",
                        f"Citation page does not match source metadata: {quote[:60]}",
                        location,
                    )
                )
    return issues


def validate_book_card(card: dict[str, Any], chunks: Iterable[Chunk]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    chunk_list = list(chunks)
    required = [
        "book_id",
        "title",
        "author",
        "one_line_thesis",
        "core_questions",
        "key_concepts",
        "assumptions",
        "limitations",
        "best_for",
        "not_for",
        "chapter_coverage",
        "lenses",
        "confidence",
        "status",
    ]
    for field in required:
        if field not in card or card.get(field) is None:
            issues.append(ValidationIssue("error", "missing_field", f"Book card is missing {field}", card.get("title", "")))
    if not str(card.get("one_line_thesis", "")).strip():
        issues.append(ValidationIssue("error", "missing_thesis", "Book card needs a one-line thesis", card.get("title", "")))
    if not card.get("lenses"):
        issues.append(ValidationIssue("error", "missing_lenses", "Book card needs at least one lens", card.get("title", "")))
    coverage = card.get("chapter_coverage") or []
    if not coverage:
        issues.append(ValidationIssue("error", "missing_chapter_coverage", "Book card needs chapter coverage with citations", card.get("title", "")))
    for entry in coverage:
        if not isinstance(entry, dict):
            issues.append(ValidationIssue("error", "invalid_chapter_coverage", "Chapter coverage entry must be an object", card.get("title", "")))
            continue
        if not entry.get("chapter") or not entry.get("summary"):
            issues.append(ValidationIssue("error", "incomplete_chapter_coverage", "Chapter coverage needs chapter and summary", card.get("title", "")))
        citation = entry.get("citation")
        if not citation:
            issues.append(ValidationIssue("error", "missing_chapter_citation", f"Chapter has no citation: {entry.get('chapter', '')}", card.get("title", "")))
        else:
            issues.extend(_validate_citation(citation, chunk_list, f"book card: {entry.get('chapter', '')}"))
    return issues


def validate_framework_card(framework: dict[str, Any], chunks: Iterable[Chunk]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    chunk_list = list(chunks)
    required_present = [
        "framework_id",
        "book_id",
        "name",
        "one_liner",
        "lenses",
        "applicable_when",
        "inputs",
        "steps",
        "outputs",
        "failure_modes",
        "counterexamples",
        "citations",
        "related_frameworks",
        "confidence",
        "status",
    ]
    for field in required_present:
        if field not in framework or framework.get(field) is None:
            issues.append(ValidationIssue("error", "missing_field", f"Framework is missing {field}", framework.get("name", "")))
    required_nonempty = ["framework_id", "book_id", "name", "one_liner", "lenses", "applicable_when", "inputs", "steps", "outputs", "failure_modes", "citations"]
    for field in required_nonempty:
        if not framework.get(field):
            issues.append(ValidationIssue("error", "empty_field", f"Framework field must not be empty: {field}", framework.get("name", "")))
    for field in ("confidence", "status"):
        if framework.get(field) and framework.get(field) not in {"low", "medium", "high", "draft", "heuristic", "verified", "complete"}:
            issues.append(ValidationIssue("warning", "unknown_value", f"Unexpected {field}: {framework.get(field)}", framework.get("name", "")))
    if len(str(framework.get("one_liner", "")).strip()) < 20:
        issues.append(ValidationIssue("warning", "short_one_liner", "Framework one-liner is very short", framework.get("name", "")))
    citations = framework.get("citations") or []
    if not citations:
        issues.append(ValidationIssue("error", "missing_citations", "Framework needs at least one exact source citation", framework.get("name", "")))
    for citation in citations:
        issues.extend(_validate_citation(citation, chunk_list, framework.get("name", "")))
    if not framework.get("failure_modes"):
        issues.append(ValidationIssue("error", "missing_failure_modes", "Framework must state when it fails or does not apply", framework.get("name", "")))
    return issues


def _collect_citations(packet: dict[str, Any]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for citation in packet.get("citations", []) or []:
        if isinstance(citation, dict):
            citations.append(citation)
    for citation in packet.get("evidence", []) or []:
        if isinstance(citation, dict):
            citations.append(citation)
    for hypothesis in packet.get("hypotheses", []) or []:
        for citation in hypothesis.get("supporting_evidence", []) or []:
            if isinstance(citation, dict):
                citations.append(citation)
    for item in packet.get("counterevidence", []) or []:
        citation = item.get("citation") if isinstance(item, dict) else None
        if isinstance(citation, dict):
            citations.append(citation)
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for citation in citations:
        key = (str(citation.get("book_id", "")), str(citation.get("quote", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def validate_analysis_packet(packet: dict[str, Any], chunks_by_book: dict[str, list[Chunk]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    lenses = packet.get("lenses", [])
    if len(lenses) < 2:
        issues.append(ValidationIssue("warning", "single_lens", "Analysis uses fewer than two lenses"))
    citations = _collect_citations(packet)
    if not citations:
        issues.append(ValidationIssue("error", "no_citations", "Analysis has no citations"))
    for citation in citations:
        book_id = str(citation.get("book_id", ""))
        quote = str(citation.get("quote", ""))
        if not book_id:
            issues.append(ValidationIssue("error", "citation_missing_book", "Citation has no book_id"))
            continue
        if not citation.get("chapter"):
            issues.append(ValidationIssue("warning", "citation_missing_chapter", f"Citation has no chapter: {quote[:60]}", book_id))
        issues.extend(
            _validate_citation(
                citation,
                chunks_by_book.get(book_id, []),
                book_id,
                strict_provenance=True,
            )
        )
    if packet.get("status") == "complete":
        if not str(packet.get("conclusion", "")).strip():
            issues.append(ValidationIssue("error", "missing_conclusion", "Complete analysis needs a conclusion"))
        if len(lenses) >= 2 and not packet.get("cross_lens_conflicts"):
            issues.append(ValidationIssue("warning", "missing_conflict_handling", "Cross-lens analysis should record a conflict or state that none was found"))
        if not str(packet.get("uncertainty", "")).strip():
            issues.append(ValidationIssue("warning", "missing_uncertainty", "Complete analysis should state what would change the conclusion"))
        if "law" in lenses and not packet.get("not_legal_advice"):
            issues.append(ValidationIssue("error", "legal_disclaimer_missing", "Legal-lens analysis must be marked as not legal advice"))
    return issues