from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

from .analysis import create_analysis
from .capabilities import (
    build_capability,
    capability_impact,
    capability_status,
    evaluate_capability,
    list_capabilities,
    list_presets,
    route_capability,
    update_capability,
)
from .claims import build_claims, dismiss_conflict, list_claims, supersede_claim
from .compiler import compile_book
from .llm_compile import compile_with_llm
from .embeddings import get_embedder
from .entities import (
    align_entities,
    alignment_audit,
    detect_entities,
    merge_entity_candidate,
    sync_merge_candidates,
    undo_entity_merge,
)
from .evolution import (
    decide_evolution,
    get_evolution_config,
    propose_evolutions,
    recall_memory,
    replay_cases,
)
from .graph_rag import build_graph, fused_search_report, graph_status, list_communities, query_graph
from .obsidian_sync import grade_review, list_due_reviews, list_reader_notes, obsidian_status, sync_obsidian
from . import hindsight
from .modes import build_proposal
from .parsing import parse_book
from .reading_eval import evaluate_reading, reading_report
from .render import render_memo
from .retrieval import hybrid_search, retrieval_diagnostics
from .store import Store
from .validation import validate_analysis_packet, validate_book_card, validate_framework_card

SERVER_NAME = "bookcompiler"
SERVER_VERSION = "0.5.0"
PROTOCOL_VERSION = "2024-11-05"


def _text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOLS = [
    _tool(
        "book_library",
        "List every book the agent has ingested, including whether it was deeply compiled, its disciplines, frameworks, embedding coverage, and cross-book entity stats. Use this before answering 'what have you read'.",
        {},
    ),
    _tool(
        "book_plan",
        "Choose which learned books/frameworks to use for a question. Supports three modes: auto (agent selects), direction (user gives a field/direction but not exact books), books (user names exact books). Modes direction/books return requires_confirmation=true and consent options. Returns source_recommendations for authoritative sources (for example statutes) that match the question but are absent from the library; surface those as download-and-ingest suggestions. Always call this before book_analyze when the user asks for an analysis based on books.",
        {
            "question": {"type": "string"},
            "lenses": {"type": "array", "items": {"type": "string"}, "description": "e.g. economics, politics, law, finance, history"},
            "mode": {"type": "string", "enum": ["auto", "direction", "books"], "default": "auto"},
            "direction": {"type": "string"},
            "book_ids": {"type": "array", "items": {"type": "string"}},
            "framework_ids": {"type": "array", "items": {"type": "string"}},
        },
        ["question"],
    ),
    _tool(
        "book_recall",
        "Hybrid retrieval across learned books (BM25 + embedding + cross-book entity expansion). Returns exact quotes with book_id, chunk_id, chapter, page and a score breakdown. Use it to ground claims in specific books.",
        {
            "query": {"type": "string"},
            "book_ids": {"type": "array", "items": {"type": "string"}},
            "lenses": {"type": "array", "items": {"type": "string"}},
            "top_k": {"type": "integer", "default": 12},
            "mode": {"type": "string", "enum": ["hybrid", "lexical"], "default": "hybrid"},
        },
        ["query"],
    ),
    _tool(
        "book_analyze",
        "Create a cited multi-lens AnalysisPacket from learned books. For direction/books modes you must first call book_plan and pass the user's consent as choice=specified|specified+recommended|recommended. The returned memo is evidence scaffolding; the calling agent should write the final prose while preserving exact citations. If source_recommendations is non-empty, explicitly tell the user which authoritative sources to download and ingest, and never pretend those sources were used.",
        {
            "question": {"type": "string"},
            "lenses": {"type": "array", "items": {"type": "string"}},
            "mode": {"type": "string", "enum": ["auto", "direction", "books"], "default": "auto"},
            "direction": {"type": "string"},
            "book_ids": {"type": "array", "items": {"type": "string"}},
            "framework_ids": {"type": "array", "items": {"type": "string"}},
            "choice": {"type": "string", "enum": ["specified", "specified+recommended", "recommended", "auto"]},
        },
        ["question"],
    ),
    _tool(
        "book_ingest",
        "Ingest a local .txt/.md/.pdf/.epub file into the library. Never downloads books. Returns book_id and chunk count; deep compilation is a separate step.",
        {
            "path": {"type": "string"},
            "title": {"type": "string"},
            "author": {"type": "string"},
            "disciplines": {"type": "array", "items": {"type": "string"}},
        },
        ["path"],
    ),
    _tool(
        "book_export_text",
        "Export one learned book's chapter text and structure.md so the calling agent can read it and author a compilation patch.",
        {
            "book_id": {"type": "string"},
            "out_dir": {"type": "string"},
        },
        ["book_id"],
    ),
    _tool(
        "book_learn",
        "Read one ingested book with the configured cloud reader and make it a learned, callable capability. The reader sees an evidence sample, proposes frameworks, and BookCompiler verifies every quote/chunk/page against the local source before writing. Use this instead of asking the user to hand-author a compilation patch.",
        {
            "book_id": {"type": "string"},
            "max_chunks": {"type": "integer", "default": 28},
            "force": {"type": "boolean", "default": False},
        },
        ["book_id"],
    ),
    _tool(
        "book_compile",
        "Apply an agent-authored compilation patch (BookCard + FrameworkCards) to a book. Every citation must quote source text exactly; validation errors are returned instead of being hidden.",
        {
            "book_id": {"type": "string"},
            "patch": {"type": "object"},
        },
        ["book_id", "patch"],
    ),
    _tool(
        "book_validate",
        "Validate a compiled book or an analysis. Returns exact citation/provenance issues.",
        {
            "book_id": {"type": "string"},
            "analysis_id": {"type": "string"},
        },
    ),
    _tool(
        "book_feedback",
        "Record structured feedback (rating, error labels, preferred books/frameworks, missing evidence, outcome) so the controlled self-evolution loop can propose bounded changes.",
        {
            "analysis_id": {"type": "string"},
            "rating": {"type": "integer", "minimum": 1, "maximum": 5},
            "note": {"type": "string"},
            "error_labels": {"type": "array", "items": {"type": "string"}},
            "preferred_book_ids": {"type": "array", "items": {"type": "string"}},
            "preferred_framework_ids": {"type": "array", "items": {"type": "string"}},
            "missing_evidence": {"type": "string"},
            "outcome": {"type": "string"},
        },
        ["analysis_id", "rating"],
    ),
    _tool(
        "book_memory",
        "Hindsight-style recall of lessons, corrections, preferences and outcomes from past analyses. Memory stores lessons, not book text; source claims still come from book_recall.",
        {
            "query": {"type": "string"},
            "lenses": {"type": "array", "items": {"type": "string"}},
            "limit": {"type": "integer", "default": 8},
        },
        ["query"],
    ),
    _tool(
        "book_hindsight",
        "Inspect or use the optional Hindsight long-term memory bank. action=status reports connectivity; recall merges durable lessons; reflect asks Hindsight for a synthesized answer; retain stores one explicit durable lesson. Hindsight failure never blocks book recall.",
        {
            "action": {"type": "string", "enum": ["status", "recall", "reflect", "retain"], "default": "status"},
            "query": {"type": "string"},
            "content": {"type": "string"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "budget": {"type": "string", "enum": ["low", "mid", "high"], "default": "low"},
            "limit": {"type": "integer", "default": 8},
            "async": {"type": "boolean", "default": True},
        },
    ),
    _tool(
        "book_entities",
        "Inspect cross-book aligned entities (canonical name, aliases, books, mentions, co-occurrence relations). action=audit lists near-duplicates; sync-audit persists them; merge/undo-merge are confirmed writes with snapshots.",
        {
            "action": {"type": "string", "enum": ["list", "show", "detect", "align", "audit", "sync-audit", "candidates", "merge", "undo-merge"], "default": "list"},
            "entity_id": {"type": "string"},
            "candidate_id": {"type": "string"},
            "query": {"type": "string"},
            "cross_book_only": {"type": "boolean", "default": False},
            "status": {"type": "string"},
            "confirm": {"type": "boolean", "default": False},
            "note": {"type": "string"},
            "limit": {"type": "integer", "default": 50},
        },
    ),
    _tool(
        "book_claims",
        "Claim-level knowledge graph. action=build extracts sentence claims with exact quote/chunk/page, action=list/stats shows claims and conflicts, action=show returns evidence, action=supersede requires confirm=true, action=dismiss records that two conflicting claims are different views.",
        {
            "action": {"type": "string", "enum": ["build", "list", "stats", "show", "supersede", "dismiss"], "default": "list"},
            "claim_id": {"type": "string"},
            "new_claim_id": {"type": "string"},
            "book_id": {"type": "string"},
            "book_ids": {"type": "array", "items": {"type": "string"}},
            "query": {"type": "string"},
            "status": {"type": "string"},
            "note": {"type": "string"},
            "confirm": {"type": "boolean", "default": False},
            "force": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "default": 100},
            "limit_per_book": {"type": "integer", "default": 120},
        },
    ),
    _tool(
        "book_reading_eval",
        "Score how effectively an analysis used the learned books. Nine weighted dimensions: source fidelity, retrieval coverage, framework fit, cross-book synthesis, cross-lens integration, conflict handling, calibration, actionability, failure-mode awareness. action=score stores explicit human/LLM scores; action=judge runs an independent blind LLM judge (auto_proxy is NEVER relabelled as judge); action=judge_status shows the configured judge; action=calibration compares judge and proxy; action=list/report aggregates; action=propose creates proposals ONLY from independent scores.",
        {
            "action": {"type": "string", "enum": ["score", "list", "report", "propose", "judge", "judge_status", "calibration"], "default": "report"},
            "analysis_id": {"type": "string"},
            "scores": {"type": "object", "description": "dimension -> 0..10; omitted dimensions keep deterministic proxies"},
            "evaluator": {"type": "string", "enum": ["auto", "human", "llm_judge", "mixed"], "default": "auto"},
            "note": {"type": "string"},
            "error_labels": {"type": "array", "items": {"type": "string"}},
            "provider": {"type": "string", "enum": ["ollama", "openai", "openai-compatible"], "default": "ollama"},
            "model": {"type": "string", "default": "qwen2.5:7b-instruct-q4_K_M"},
            "base_url": {"type": "string", "default": "http://127.0.0.1:11434"},
            "dry_run": {"type": "boolean", "default": False},
            "allow_draft": {"type": "boolean", "default": False},
            "min_support": {"type": "integer", "default": 1},
            "limit": {"type": "integer", "default": 100},
        },
    ),
    _tool(
        "book_graphrag",
        "GraphRAG sidecar over entities, claim relations, book membership, and communities. action=status/build/query/communities. It is a deterministic sidecar and never modifies library.db. Failures fall back to hybrid retrieval.",
        {
            "action": {"type": "string", "enum": ["status", "build", "query", "communities"], "default": "status"},
            "query": {"type": "string"},
            "book_ids": {"type": "array", "items": {"type": "string"}},
            "mode": {"type": "string", "enum": ["hybrid", "graph"], "default": "hybrid"},
            "limit": {"type": "integer", "default": 12},
        },
    ),
    _tool(
        "book_obsidian",
        "Controlled Obsidian sync and reader notes. Generated notes are exported one-way; only the separate inbox is imported. Reader notes are memory context, never citations. action=status/sync/notes/reviews/grade.",
        {
            "action": {"type": "string", "enum": ["status", "sync", "notes", "reviews", "grade"], "default": "status"},
            "vault": {"type": "string"},
            "subdir": {"type": "string", "default": "BookCompiler"},
            "inbox": {"type": "string", "default": "BookCompiler Inbox"},
            "direction": {"type": "string", "enum": ["export", "import", "both"], "default": "both"},
            "query": {"type": "string"},
            "target_type": {"type": "string"},
            "target_id": {"type": "string"},
            "item_id": {"type": "string"},
            "grade": {"type": "integer"},
            "limit": {"type": "integer", "default": 50},
        },
    ),
    _tool(
        "book_evolution",
        "Controlled self-evolution. action=list/propose/decide/replay/shadow. Promotion requires a clean structural replay plus a retrieval shadow gate and a post-change canary; rollback restores the pre-promotion snapshot.",
        {
            "action": {"type": "string", "enum": ["list", "propose", "decide", "replay", "shadow", "config"], "default": "list"},
            "proposal_id": {"type": "string"},
            "status": {"type": "string", "enum": ["accepted", "rejected", "shadow", "promoted", "rolled_back"]},
            "note": {"type": "string"},
            "min_support": {"type": "integer", "default": 1},
            "cases": {"type": "array", "items": {"type": "object"}},
            "replay_report": {"type": "object"},
            "quality_report": {"type": "object"},
            "k": {"type": "integer", "default": 5},
        },
    ),
    _tool(
        "book_capability",
        "Domain capability packs: one host-facing skill, several versioned domain packs. action=presets/list/status/route/build/impact/update/eval. Call route first for an event question; if requires_confirmation is true, show candidates and ask the user before loading a pack. A pack contains learned books, frameworks, evidence claims, conflicts and boundary conditions. update only proposes a diff unless apply=true. LOCAL.md is never overwritten.",
        {
            "action": {"type": "string", "enum": ["presets", "list", "status", "route", "build", "impact", "update", "eval"], "default": "list"},
            "domain": {"type": "string"},
            "query": {"type": "string"},
            "lenses": {"type": "array", "items": {"type": "string"}},
            "book_ids": {"type": "array", "items": {"type": "string"}},
            "book_id": {"type": "string"},
            "direction": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "apply": {"type": "boolean", "default": False},
            "force": {"type": "boolean", "default": False},
            "cases": {"type": "string"},
            "limit": {"type": "integer", "default": 3},
            "limit_cases": {"type": "integer", "default": 0},
            "max_books": {"type": "integer", "default": 8},
            "root": {"type": "string"},
        },
    ),
    _tool(
        "book_status",
        "Show library coverage, embedding backend/coverage, entity graph stats, retrieval diagnostics, and the active evolution config.",
        {
            "query": {"type": "string"},
        },
    ),
]


class BookCompilerMCP:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)

    def _store(self) -> Store:
        return Store(self.db_path)

    def _book_payload(self, store: Store, book: dict[str, Any]) -> dict[str, Any]:
        book_id = book["book_id"]
        frameworks = store.list_frameworks(book_ids=[book_id])
        card = store.get_book_card(book_id) or {}
        chunks = store.conn.execute("SELECT COUNT(*) FROM chunks WHERE book_id = ?", (book_id,)).fetchone()[0]
        return {
            **book,
            "framework_count": len(frameworks),
            "chunk_count": chunks,
            "card_status": card.get("status"),
            "card_confidence": card.get("confidence"),
            "one_line_thesis": card.get("one_line_thesis", ""),
            "learned": (
                book.get("status") == "compiled"
                and str(card.get("status", "")).lower() in {"verified", "complete"}
                and bool(frameworks)
            ),
        }

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        arguments = arguments or {}
        store = self._store()
        try:
            if name == "book_library":
                books = [self._book_payload(store, book) for book in store.list_books()]
                compiled = [book for book in books if book["learned"]]
                ingested_only = [book for book in books if not book["learned"]]
                return {
                    "books": books,
                    "total_books": len(books),
                    "learned_books": len(compiled),
                    "ingested_books": len(ingested_only),
                    "embedding": store.embedding_stats(get_embedder().model),
                    "entities": store.entity_stats(),
                    "note": (
                        "learned_books = verified/complete card with at least one framework; "
                        "ingested_books = imported or heuristically compiled but not reviewed. "
                        "Never describe the latter as read."
                    ),
                }

            if name == "book_plan":
                proposal = build_proposal(
                    store,
                    mode=str(arguments.get("mode", "auto")),
                    query=str(arguments.get("question", "")),
                    lenses=list(arguments.get("lenses") or ["economics", "politics", "law"]),
                    book_ids=list(arguments.get("book_ids") or []),
                    framework_ids=list(arguments.get("framework_ids") or []),
                    direction=str(arguments.get("direction", "")),
                )
                return proposal.to_dict()

            if name == "book_recall":
                query = str(arguments.get("query", ""))
                requested = list(arguments.get("book_ids") or [])
                learned = store.learned_book_ids()
                ignored = sorted(set(requested) - learned) if requested else []
                allowed = sorted(learned.intersection(requested)) if requested else sorted(learned)
                if not allowed:
                    return {
                        "query": query,
                        "evidence": [],
                        "learned_book_ids": sorted(learned),
                        "ignored_unlearned_book_ids": ignored,
                        "warning": (
                            "No learned books match this request. Ingested-only books "
                            "must be compiled and validated before recall."
                        ),
                    }
                hits = hybrid_search(
                    store,
                    query,
                    book_ids=allowed,
                    limit=int(arguments.get("top_k", 12)),
                    mode=str(arguments.get("mode", "hybrid")),
                )
                titles = {book["book_id"]: book["title"] for book in store.list_books()}
                return {
                    "query": query,
                    "detected_entities": detect_entities(store, query),
                    "learned_book_ids": allowed,
                    "ignored_unlearned_book_ids": ignored,
                    "evidence": [
                        {
                            "book_id": hit["book_id"],
                            "book_title": titles.get(hit["book_id"], ""),
                            "chunk_id": hit["chunk_id"],
                            "chapter": hit["chapter_title"],
                            "page": hit.get("page_start"),
                            "quote": hit["text"][:1600],
                            "score": hit["score"],
                            "score_breakdown": hit["score_breakdown"],
                            "matched_entities": hit.get("matched_entities", []),
                        }
                        for hit in hits
                    ],
                }

            if name == "book_analyze":
                question = str(arguments.get("question", ""))
                mode = str(arguments.get("mode", "auto"))
                lenses = list(arguments.get("lenses") or ["economics", "politics", "law"])
                proposal = build_proposal(
                    store,
                    mode=mode,
                    query=question,
                    lenses=lenses,
                    book_ids=list(arguments.get("book_ids") or []),
                    framework_ids=list(arguments.get("framework_ids") or []),
                    direction=str(arguments.get("direction", "")),
                )
                choice = str(arguments.get("choice", ""))
                if mode == "auto":
                    choice = "auto"
                elif not choice:
                    return {
                        "requires_confirmation": True,
                        "proposal": proposal.to_dict(),
                        "source_recommendations": proposal.source_recommendations,
                        "message": "Ask the user to choose one of: specified, specified+recommended, recommended. Also surface any source_recommendations as download-and-ingest suggestions.",
                    }
                elif choice not in proposal.options:
                    raise ValueError(f"choice must be one of: {', '.join(proposal.options)}")
                packet = create_analysis(store, question, lenses, proposal, choice)
                data = packet.to_dict()
                source_recommendations = data.get("selection", {}).get("source_recommendations", [])
                return {
                    "analysis_id": packet.analysis_id,
                    "analysis": data,
                    "source_recommendations": source_recommendations,
                    "memo_markdown": render_memo(data),
                    "instruction": (
                        "Preserve exact quotes and provenance. Write the final answer yourself; do not invent evidence. "
                        "If source_recommendations is non-empty, explicitly tell the user which authoritative sources to download and ingest; "
                        "do not imply they were part of the evidence."
                    ),
                }

            if name == "book_ingest":
                path = Path(str(arguments.get("path", ""))).expanduser()
                if not path.exists():
                    raise ValueError(f"path does not exist: {path}")
                parsed = parse_book(
                    path,
                    title=str(arguments.get("title") or "") or None,
                    author=str(arguments.get("author") or "Unknown"),
                    disciplines=list(arguments.get("disciplines") or []),
                )
                store.add_book(parsed)
                align_entities(store)
                return {
                    "book_id": parsed.book_id,
                    "title": parsed.title,
                    "author": parsed.author,
                    "chapters": len(parsed.chapters),
                    "chunks": len(parsed.chunks),
                    "status": "ingested",
                    "next_step": "Deep compilation is separate. Call book_learn to read it, or export text and author a patch with book_compile.",
                }

            if name == "book_export_text":
                book_id = str(arguments.get("book_id", ""))
                book = store.get_book(book_id)
                if not book:
                    raise ValueError(f"unknown book_id: {book_id}")
                chunks = store.get_chunks(book_id)
                out = Path(str(arguments.get("out_dir") or (Path.home() / ".bookcompiler" / "exports" / book_id))).expanduser()
                out.mkdir(parents=True, exist_ok=True)
                by_chapter: dict[tuple[int, str], list[Any]] = {}
                for chunk in chunks:
                    by_chapter.setdefault((chunk.chapter_index, chunk.chapter_title), []).append(chunk)
                structure = [f"# {book['title']}", "", f"Author: {book['author']}", "", "## Chapters", ""]
                files = []
                for (index, title), items in sorted(by_chapter.items()):
                    filename = f"chapter_{index:03d}.md"
                    body = "\n\n".join(item.text for item in items)
                    (out / filename).write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
                    structure.append(f"- {index}. {title} -> {filename} ({len(items)} chunks)")
                    files.append(str(out / filename))
                (out / "structure.md").write_text("\n".join(structure) + "\n", encoding="utf-8")
                return {"book_id": book_id, "out_dir": str(out), "chapters": len(by_chapter), "files": files}

            if name == "book_learn":
                book_id = str(arguments.get("book_id", ""))
                book = store.get_book(book_id)
                if not book:
                    raise ValueError(f"unknown book_id: {book_id}")
                if book.get("status") == "compiled" and not bool(arguments.get("force", False)):
                    return {
                        "book_id": book_id,
                        "ok": True,
                        "skipped": True,
                        "message": "already compiled; pass force=true to re-read",
                    }
                return compile_with_llm(
                    store,
                    book_id,
                    max_chunks=int(arguments.get("max_chunks", 28) or 28),
                )

            if name == "book_compile":
                book_id = str(arguments.get("book_id", ""))
                patch = arguments.get("patch")
                if not isinstance(patch, dict):
                    raise ValueError("patch must be an object")
                result = compile_book(store, book_id, patch=patch)
                return {
                    "book_id": result.book_id,
                    "frameworks": len(result.frameworks),
                    "issues": [issue.to_dict() for issue in result.issues],
                    "card_status": result.book_card.status,
                    "entity_stats": store.entity_stats(),
                }

            if name == "book_validate":
                book_id = str(arguments.get("book_id", ""))
                analysis_id = str(arguments.get("analysis_id", ""))
                issues = []
                if analysis_id:
                    analysis_payload = store.get_analysis(analysis_id)
                    if not analysis_payload:
                        raise ValueError(f"unknown analysis_id: {analysis_id}")
                    book_ids = {
                        citation.get("book_id", "")
                        for citation in analysis_payload.get("citations", [])
                        if isinstance(citation, dict) and citation.get("book_id")
                    }
                    for item in (analysis_payload.get("selection") or {}).get("books", []):
                        if isinstance(item, dict) and item.get("book_id"):
                            book_ids.add(item["book_id"])
                    issues = validate_analysis_packet(
                        analysis_payload,
                        {bid: store.get_chunks(bid) for bid in sorted(book_ids)},
                    )
                elif book_id:
                    card = store.get_book_card(book_id)
                    chunks = store.get_chunks(book_id)
                    if not card:
                        raise ValueError("book has no compiled card")
                    issues.extend(validate_book_card(card, chunks))
                    for framework in store.list_frameworks(book_ids=[book_id]):
                        issues.extend(validate_framework_card(framework, chunks))
                else:
                    raise ValueError("provide book_id or analysis_id")
                return {"issues": [issue.to_dict() for issue in issues], "ok": not any(issue.severity == "error" for issue in issues)}

            if name == "book_feedback":
                feedback_id = store.add_feedback(
                    str(arguments.get("analysis_id", "")),
                    int(arguments.get("rating", 3)),
                    str(arguments.get("note", "")),
                    error_labels=list(arguments.get("error_labels") or []),
                    preferred_book_ids=list(arguments.get("preferred_book_ids") or []),
                    preferred_framework_ids=list(arguments.get("preferred_framework_ids") or []),
                    missing_evidence=str(arguments.get("missing_evidence", "")),
                    outcome=str(arguments.get("outcome", "")),
                )
                rating = int(arguments.get("rating", 3))
                note = str(arguments.get("note", "")).strip()
                outcome = str(arguments.get("outcome", "")).strip()
                error_labels = list(arguments.get("error_labels") or [])
                if note or outcome or error_labels:
                    lesson = (
                        f"BookCompiler feedback (rating={rating}/5). "
                        f"Errors: {', '.join(error_labels) or 'none'}. "
                        f"Note: {note or 'none'}. Outcome: {outcome or 'none'}."
                    )
                    hindsight.retain(
                        lesson,
                        context="BookCompiler feedback",
                        document_id=f"feedback-{feedback_id}",
                        tags=["feedback"] + [str(x) for x in error_labels],
                        metadata={"source": "bookcompiler", "kind": "feedback", "rating": str(rating)},
                    )
                return {"feedback_id": feedback_id}

            if name == "book_memory":
                return {
                    "lessons": recall_memory(
                        store,
                        str(arguments.get("query", "")),
                        list(arguments.get("lenses") or ["economics", "politics", "law"]),
                        int(arguments.get("limit", 8)),
                    ),
                    "hindsight": hindsight.status(),
                }

            if name == "book_hindsight":
                action = str(arguments.get("action", "status"))
                if action == "status":
                    return hindsight.status()
                if action == "retain":
                    return hindsight.retain(
                        str(arguments.get("content", "")),
                        context="BookCompiler explicit memory",
                        tags=list(arguments.get("tags") or []),
                        metadata={"source": "bookcompiler", "kind": "explicit"},
                        asynchronous=bool(arguments.get("async", True)),
                    )
                if action == "reflect":
                    return hindsight.reflect(str(arguments.get("query", "")), budget=str(arguments.get("budget", "low")))
                return hindsight.recall(
                    str(arguments.get("query", "")),
                    limit=int(arguments.get("limit", 8)),
                    budget=str(arguments.get("budget", "low")),
                )

            if name == "book_entities":
                action = str(arguments.get("action", "list"))
                if action == "align":
                    return align_entities(store)
                if action == "audit":
                    return alignment_audit(store, limit=int(arguments.get("limit", 50)))
                if action == "sync-audit":
                    return sync_merge_candidates(store, limit=int(arguments.get("limit", 50)))
                if action == "candidates":
                    return {"candidates": store.list_entity_merge_candidates(status=str(arguments.get("status", "")), limit=int(arguments.get("limit", 50)))}
                if action == "merge":
                    return merge_entity_candidate(store, str(arguments.get("candidate_id", "")), note=str(arguments.get("note", "")), confirm=bool(arguments.get("confirm", False)))
                if action == "undo-merge":
                    return undo_entity_merge(store, str(arguments.get("candidate_id", "")), note=str(arguments.get("note", "")))
                if action == "show":
                    return store.get_entity(str(arguments.get("entity_id", ""))) or {}
                if action == "detect":
                    return {"entities": detect_entities(store, str(arguments.get("query", "")))}
                return {
                    "entities": store.list_entities(
                        query=str(arguments.get("query", "")),
                        cross_book_only=bool(arguments.get("cross_book_only", False)),
                        limit=int(arguments.get("limit", 50)),
                    )
                }

            if name == "book_claims":
                action = str(arguments.get("action", "list"))
                if action == "build":
                    return build_claims(
                        store,
                        book_ids=list(arguments.get("book_ids") or []) or None,
                        limit_per_book=int(arguments.get("limit_per_book", 120)),
                    )
                if action == "stats":
                    return store.claim_stats()
                if action == "show":
                    return store.get_claim(str(arguments.get("claim_id", ""))) or {}
                if action == "supersede":
                    return supersede_claim(
                        store,
                        str(arguments.get("claim_id", "")),
                        str(arguments.get("new_claim_id", "")),
                        note=str(arguments.get("note", "")),
                        confirm=bool(arguments.get("confirm", False)),
                        force=bool(arguments.get("force", False)),
                    )
                if action == "dismiss":
                    return dismiss_conflict(
                        store,
                        str(arguments.get("claim_id", "")),
                        str(arguments.get("new_claim_id", "")),
                        note=str(arguments.get("note", "")),
                    )
                return list_claims(
                    store,
                    query=str(arguments.get("query", "")),
                    book_id=str(arguments.get("book_id", "")),
                    status=str(arguments.get("status", "")),
                    limit=int(arguments.get("limit", 100)),
                )

            if name == "book_reading_eval":
                action = str(arguments.get("action", "report"))
                if action == "score":
                    return evaluate_reading(
                        store,
                        str(arguments.get("analysis_id", "")),
                        scores=arguments.get("scores") or {},
                        evaluator=str(arguments.get("evaluator", "auto")),
                        note=str(arguments.get("note", "")),
                        error_labels=list(arguments.get("error_labels") or []),
                    )
                if action == "propose":
                    return {
                        "proposals": [
                            item
                            for item in propose_evolutions(store, int(arguments.get("min_support", 1)))
                            if item.get("source") == "reading_eval"
                        ]
                    }
                if action == "judge":
                    from .judge import JudgeConfig, judge_analysis

                    return judge_analysis(
                        store,
                        str(arguments.get("analysis_id", "")),
                        config=JudgeConfig(
                            provider=str(arguments.get("provider", "ollama")),
                            model=str(arguments.get("model", "qwen2.5:7b-instruct-q4_K_M")),
                            base_url=str(arguments.get("base_url", "http://127.0.0.1:11434")),
                        ),
                        dry_run=bool(arguments.get("dry_run", False)),
                        allow_draft=bool(arguments.get("allow_draft", False)),
                        note=str(arguments.get("note", "")),
                    )
                if action == "judge_status":
                    from .judge import judge_status

                    return judge_status()
                if action == "calibration":
                    report = reading_report(store, limit=int(arguments.get("limit", 500)))
                    return {
                        "proxy_calibration": report.get("proxy_calibration", {}),
                        "independent_count": report.get("independent_count", 0),
                        "basis": report.get("basis"),
                    }
                if action == "report":
                    return reading_report(store, limit=int(arguments.get("limit", 500)))
                return {
                    "evaluations": store.list_reading_evaluations(
                        analysis_id=str(arguments.get("analysis_id", "")),
                        limit=int(arguments.get("limit", 100)),
                    )
                }

            if name == "book_graphrag":
                action = str(arguments.get("action", "status"))
                if action == "build":
                    return build_graph(store)
                if action == "communities":
                    return {"communities": list_communities(store, limit=int(arguments.get("limit", 30)))}
                if action == "query":
                    query = str(arguments.get("query", ""))
                    if not query:
                        raise ValueError("query is required")
                    graph_book_ids = list(arguments.get("book_ids") or []) or None
                    if str(arguments.get("mode", "hybrid")) == "graph":
                        return query_graph(store, query, book_ids=graph_book_ids, limit=int(arguments.get("limit", 12)))
                    return fused_search_report(store, query, book_ids=graph_book_ids, limit=int(arguments.get("limit", 12)))
                return graph_status(store)

            if name == "book_obsidian":
                action = str(arguments.get("action", "status"))
                vault = str(arguments.get("vault", ""))
                if action == "sync":
                    if not vault:
                        raise ValueError("vault is required for sync")
                    return sync_obsidian(
                        store,
                        vault,
                        subdir=str(arguments.get("subdir", "BookCompiler")),
                        inbox=str(arguments.get("inbox", "BookCompiler Inbox")),
                        direction=str(arguments.get("direction", "both")),
                    )
                if action == "notes":
                    return {
                        "notes": list_reader_notes(
                            store,
                            query=str(arguments.get("query", "")),
                            target_type=str(arguments.get("target_type", "")),
                            target_id=str(arguments.get("target_id", "")),
                            limit=int(arguments.get("limit", 50)),
                        )
                    }
                if action == "reviews":
                    return {"due": list_due_reviews(store, limit=int(arguments.get("limit", 50)))}
                if action == "grade":
                    return grade_review(
                        store,
                        str(arguments.get("item_id", "")),
                        int(arguments.get("grade", 0)),
                        note=str(arguments.get("note", "")),
                    )
                return obsidian_status(store, vault=vault)

            if name == "book_evolution":
                action = str(arguments.get("action", "list"))
                if action == "propose":
                    return {"proposals": propose_evolutions(store, int(arguments.get("min_support", 1)))}
                if action == "decide":
                    return decide_evolution(
                        store,
                        str(arguments.get("proposal_id", "")),
                        str(arguments.get("status", "")),
                        str(arguments.get("note", "")),
                        arguments.get("replay_report"),
                        arguments.get("quality_report"),
                    )
                if action == "shadow":
                    from .evolution import shadow_evaluate

                    proposal_payload = store.get_evolution_proposal(str(arguments.get("proposal_id", "")))
                    if not proposal_payload:
                        raise ValueError("unknown proposal_id")
                    return shadow_evaluate(store, proposal_payload, k=int(arguments.get("k", 5)))
                if action == "replay":
                    return replay_cases(store, list(arguments.get("cases") or []))
                if action == "config":
                    return get_evolution_config(store)
                return {"proposals": store.list_evolution_proposals()}

            if name == "book_capability":
                action = str(arguments.get("action") or "list").lower()
                root = str(arguments.get("root") or "") or None
                domain = str(arguments.get("domain") or "")
                if action == "presets":
                    return list_presets()
                if action == "list":
                    return list_capabilities(root=root)
                if action == "status":
                    return capability_status(domain, root=root)
                if action == "route":
                    return route_capability(
                        store,
                        str(arguments.get("query") or ""),
                        lenses=[str(item) for item in (arguments.get("lenses") or [])],
                        limit=int(arguments.get("limit", 3)),
                        root=root,
                    )
                if action == "impact":
                    return capability_impact(store, str(arguments.get("book_id") or ""), root=root)
                if action == "update":
                    return update_capability(
                        store,
                        domain,
                        book_ids=[str(item) for item in (arguments.get("book_ids") or [])],
                        apply=bool(arguments.get("apply", False)),
                        root=root,
                    )
                if action == "eval":
                    return evaluate_capability(
                        store,
                        domain,
                        cases_path=str(arguments.get("cases") or "") or None,
                        limit=int(arguments.get("limit_cases", 0) or 0),
                        root=root,
                    )
                if action == "build":
                    return build_capability(
                        store,
                        domain,
                        title=str(arguments.get("title") or ""),
                        description=str(arguments.get("description") or ""),
                        lenses=[str(item) for item in (arguments.get("lenses") or [])] or None,
                        book_ids=[str(item) for item in (arguments.get("book_ids") or [])] or None,
                        direction=str(arguments.get("direction") or ""),
                        max_books=int(arguments.get("max_books", 8)),
                        root=root,
                        force=bool(arguments.get("force", False)),
                    )
                raise ValueError(f"unknown capability action: {action}")

            if name == "book_status":
                query = str(arguments.get("query", ""))
                payload = {
                    "coverage": store.coverage(),
                    "embedding": store.embedding_stats(get_embedder().model),
                    "entities": store.entity_stats(),
                    "evolution": get_evolution_config(store),
                    "mcp": {"server": SERVER_NAME, "version": SERVER_VERSION},
                }
                if query:
                    payload["diagnostics"] = retrieval_diagnostics(store, query)
                return payload

            raise ValueError(f"unknown tool: {name}")
        finally:
            store.close()

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method", "")
        request_id = message.get("id")
        if "id" not in message:
            return None  # notification
        try:
            if method == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": message.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    },
                }
            if method == "ping":
                return {"jsonrpc": "2.0", "id": request_id, "result": {}}
            if method == "tools/list":
                return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
            if method == "tools/call":
                params = message.get("params", {})
                result = self.call_tool(str(params.get("name", "")), dict(params.get("arguments") or {}))
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {"content": [{"type": "text", "text": _text(result)}], "isError": False},
                }
            if method == "resources/list":
                return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": []}}
            if method == "prompts/list":
                return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": []}}
            raise ValueError(f"method not found: {method}")
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": str(exc), "data": traceback.format_exc(limit=4)},
            }


def _read_message(stream) -> dict[str, Any] | None:
    line = stream.readline()
    if not line:
        return None
    if line.lower().startswith(b"content-length:"):
        length = int(line.split(b":", 1)[1].strip())
        while True:
            header = stream.readline()
            if header in (b"\r\n", b"\n", b""):
                break
        body = stream.read(length)
        return json.loads(body.decode("utf-8"))
    text = line.decode("utf-8").strip()
    if not text:
        return None
    return json.loads(text)


def run_stdio(db_path: str | Path) -> None:
    server = BookCompilerMCP(db_path)
    stream = sys.stdin.buffer
    output = sys.stdout
    while True:
        try:
            message = _read_message(stream)
        except Exception as exc:
            print(f"bookcompiler-mcp: invalid input: {exc}", file=sys.stderr)
            break
        if message is None:
            break
        response = server.handle(message)
        if response is not None:
            output.write(json.dumps(response, ensure_ascii=False) + "\n")
            output.flush()
