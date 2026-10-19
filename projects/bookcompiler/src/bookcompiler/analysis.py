from __future__ import annotations

from typing import Any

from .evolution import recall_memory
from .graph_rag import ensure_graph, fused_search_report
from .models import AnalysisPacket, SelectionProposal, ValidationIssue, utc_now
from .obsidian_sync import reader_notes_for_analysis
from .orchestration import orchestrate_analysis
from .modes import resolve_proposal, select_frameworks
from .store import Store
from .utils import stable_id
from .validation import validate_analysis_packet


class AnalysisValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        message = "; ".join(issue.message for issue in issues if issue.severity == "error")
        super().__init__(message or "Analysis patch failed validation")
        self.message = message


def _hydrate_frameworks(store: Store, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frameworks: list[dict[str, Any]] = []
    for row in rows:
        framework_id = row.get("framework_id", "")
        if not framework_id:
            continue
        framework = store.get_framework(framework_id)
        if framework:
            frameworks.append(framework)
    return frameworks


def _fallback_frameworks(store: Store, question: str, lenses: list[str], book_ids: list[str]) -> list[dict[str, Any]]:
    rows = select_frameworks(store, question, lenses, book_ids=book_ids)
    return _hydrate_frameworks(store, rows)


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result = []
    for item in items:
        key = (item.get("chunk_id", ""), item.get("quote", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _hypotheses(frameworks: list[dict[str, Any]], lenses: list[str]) -> list[dict[str, Any]]:
    hypotheses = []
    for lens in lenses:
        candidates = [fw for fw in frameworks if lens in fw.get("lenses", [])]
        for framework in candidates[:1]:
            hypotheses.append(
                {
                    "lens": lens,
                    "framework_id": framework.get("framework_id"),
                    "framework": framework.get("name"),
                    "claim": f"{framework.get('one_liner', '')} Apply this to the event and state the expected transmission path.",
                    "supporting_evidence": framework.get("citations", [])[:2],
                    "status": "draft",
                    "confidence": "low",
                }
            )
    return hypotheses


def _conflicts(frameworks: list[dict[str, Any]], lenses: list[str]) -> list[dict[str, Any]]:
    if len(lenses) < 2:
        return []
    return [
        {
            "lenses": lenses[:2],
            "description": "Check whether the economic, political, and legal lenses point in different directions. Do not average them away.",
            "status": "draft",
        }
    ]


def _claim_conflicts(store: Store, book_ids: list[str]) -> list[dict[str, Any]]:
    """Turn claim-graph relations into auditable conflict items."""
    conflicts: list[dict[str, Any]] = []
    for relation in store.get_claim_conflicts(book_ids=book_ids, limit=12):
        conflicts.append(
            {
                "lenses": [],
                "description": (
                    f"{relation.get('src_subject', '')} "
                    f"[{relation.get('src_predicate', '')}] "
                    f"{str(relation.get('src_object', ''))[:120]} "
                    f"vs {relation.get('dst_subject', '')} "
                    f"[{relation.get('dst_predicate', '')}] "
                    f"{str(relation.get('dst_object', ''))[:120]}"
                ),
                "status": "draft",
                "source": "claim_graph",
                "relation": relation.get("relation"),
                "confidence": relation.get("confidence"),
                "claims": [relation],
            }
        )
    return conflicts


def _claim_evidence(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "book_id": claim.get("book_id", ""),
        "quote": claim.get("quote", ""),
        "chunk_id": claim.get("chunk_id", ""),
        "chapter": claim.get("chapter_title", ""),
        "page": claim.get("page"),
        "source": "claim",
        "claim_id": claim.get("claim_id", ""),
        "subject": claim.get("subject", ""),
        "predicate": claim.get("predicate", ""),
        "object": claim.get("object", ""),
        "confidence": claim.get("confidence"),
    }


def _chunks_by_book(store: Store, packet: dict[str, Any]) -> dict[str, list[Any]]:
    book_ids = {
        citation.get("book_id", "")
        for citation in packet.get("citations", [])
        if isinstance(citation, dict) and citation.get("book_id")
    }
    selection = packet.get("selection", {})
    if isinstance(selection, dict):
        for book in selection.get("books", []):
            if isinstance(book, dict) and book.get("book_id"):
                book_ids.add(book["book_id"])
    return {book_id: store.get_chunks(book_id) for book_id in sorted(book_ids)}


def create_analysis(
    store: Store,
    question: str,
    lenses: list[str],
    proposal: SelectionProposal,
    choice: str,
) -> AnalysisPacket:
    if proposal.mode == "auto":
        resolved = {
            "books": proposal.recommended_books,
            "frameworks": proposal.recommended_frameworks,
            "choice": "auto",
        }
    else:
        resolved = resolve_proposal(proposal, choice)
    if not resolved["books"] and not resolved["frameworks"]:
        raise ValueError(
            "resolved selection is empty; choose another consent option or add books/frameworks"
        )
    book_ids = [book["book_id"] for book in resolved["books"]]
    learned_ids = store.learned_book_ids()
    unlearned = sorted(set(book_ids) - learned_ids)
    if unlearned:
        raise ValueError(
            "These books are ingested but not learned yet (no compiled framework): "
            + ", ".join(unlearned)
            + ". Export, compile, and validate them before using them as evidence."
        )
    frameworks = _hydrate_frameworks(store, resolved["frameworks"])
    if not frameworks:
        frameworks = _fallback_frameworks(store, question, lenses, book_ids)
    framework_book_ids = sorted({fw.get("book_id", "") for fw in frameworks if fw.get("book_id")})
    search_book_ids = book_ids or framework_book_ids
    evidence: list[dict[str, Any]] = []
    for framework in frameworks:
        evidence.extend(framework.get("citations", []))
    claims: list[dict[str, Any]] = []
    retrieval: dict[str, Any] = {
        "channels": {"hybrid": [], "graph": [], "fused": []},
        "graph": {"available": False, "path": ""},
        "communities": [],
        "fallback": "no book scope; retrieval skipped",
    }
    if search_book_ids:
        claims = store.search_claims(question, book_ids=search_book_ids, limit=8)
        for claim in claims:
            evidence.append(_claim_evidence(claim))
        try:
            ensure_graph(store, rebuild_stale=True)
        except Exception:
            # The graph is an enhancement. A failed build must never prevent
            # hybrid retrieval or the rest of the analysis.
            pass
        retrieval = fused_search_report(store, question, book_ids=search_book_ids, limit=8)
        for chunk in retrieval.get("items", []):
            quote = str(chunk.get("text", "")).strip()
            if len(quote) < 12:
                continue
            evidence.append(
                {
                    "book_id": chunk.get("book_id", ""),
                    "quote": quote[:500],
                    "chunk_id": chunk.get("chunk_id", ""),
                    "chapter": chunk.get("chapter_title", ""),
                    "page": chunk.get("page_start"),
                    "source": chunk.get("source", "retrieval"),
                }
            )
        retrieval = {
            "channels": retrieval.get("channels", {}),
            "graph": retrieval.get("graph", {}),
            "communities": retrieval.get("communities", []),
            "rrf_k": retrieval.get("rrf_k"),
            "graph_weight": retrieval.get("graph_weight"),
            "fallback": retrieval.get("fallback", ""),
        }
    reader_notes: list[dict[str, Any]] = []
    try:
        reader_notes = reader_notes_for_analysis(store, question, lenses, search_book_ids, limit=5)
    except Exception:
        reader_notes = []
    evidence = _dedupe_evidence(evidence)
    claim_conflicts = _claim_conflicts(store, search_book_ids) if search_book_ids else []
    cross_lens_conflicts = claim_conflicts or _conflicts(frameworks, lenses)
    if len(lenses) >= 2 and not any(item.get("lenses") for item in cross_lens_conflicts):
        cross_lens_conflicts.extend(_conflicts(frameworks, lenses))
    next_checks = ["Find the strongest counterexample.", "Check whether the legal authority is clear.", "Check who can block implementation."]
    if claims:
        next_checks.append("Check claim-level contradictions and whether conditions differ across books.")
    for source in proposal.source_recommendations[:5]:
        check = str(source.get("next_check", "")).strip()
        if check and check not in next_checks:
            next_checks.append(check)
    memory_context = recall_memory(store, question, lenses)
    packet = AnalysisPacket(
        analysis_id=stable_id(question, "|".join(lenses), "|".join(book_ids), utc_now()),
        question=question,
        mode=proposal.mode,
        lenses=lenses,
        selection={
            "mode": proposal.mode,
            "choice": resolved["choice"],
            "books": resolved["books"],
            "frameworks": resolved["frameworks"],
            "coverage_gaps": proposal.coverage_gaps,
            "source_recommendations": proposal.source_recommendations,
            "rationale": proposal.rationale,
        },
        frameworks=frameworks,
        evidence=evidence,
        hypotheses=_hypotheses(frameworks, lenses),
        counterevidence=[],
        cross_lens_conflicts=cross_lens_conflicts,
        conclusion="",
        uncertainty="Draft: the agent must state what would change the conclusion.",
        next_checks=next_checks,
        citations=evidence,
        jurisdiction="",
        not_legal_advice="law" in lenses,
        status="draft",
        created_at=utc_now(),
        memory_context=memory_context,
        claims=claims,
        reader_notes=reader_notes,
        retrieval=retrieval,
    )
    packet.orchestration = orchestrate_analysis(store, packet.to_dict(), retrieval=retrieval, reader_notes=reader_notes)
    store.save_analysis(packet)
    return packet


def apply_analysis_patch(store: Store, analysis_id: str, patch: dict[str, Any]) -> AnalysisPacket:
    data = store.get_analysis(analysis_id)
    if not data:
        raise ValueError(f"Unknown analysis_id: {analysis_id}")
    for field in [
        "hypotheses",
        "counterevidence",
        "cross_lens_conflicts",
        "conclusion",
        "uncertainty",
        "next_checks",
        "citations",
        "jurisdiction",
        "not_legal_advice",
        "claims",
    ]:
        if field in patch:
            data[field] = patch[field]
    status = str(patch.get("status", "complete"))
    if status not in {"draft", "complete"}:
        raise ValueError("analysis status must be 'draft' or 'complete'")
    data["status"] = status
    data.setdefault("memory_context", [])
    data.setdefault("reader_notes", [])
    data.setdefault("retrieval", {})
    packet = AnalysisPacket(**data)
    issues = validate_analysis_packet(packet.to_dict(), _chunks_by_book(store, packet.to_dict()))
    if any(issue.severity == "error" for issue in issues):
        raise AnalysisValidationError(issues)
    packet.orchestration = orchestrate_analysis(
        store,
        packet.to_dict(),
        retrieval=packet.retrieval,
        reader_notes=packet.reader_notes,
    )
    store.save_analysis(packet)
    return packet