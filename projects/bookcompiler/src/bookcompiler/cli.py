from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .analysis import AnalysisValidationError, apply_analysis_patch, create_analysis
from .compiler import compile_book
from .evolution import decide_evolution, propose_evolutions, recall_memory, replay_cases
from .modes import build_proposal
from .obsidian import export_vault
from .parsing import parse_book
from .reading_eval import evaluate_reading, reading_report, render_reading_report
from .render import (
    render_dashboard,
    render_memo,
    render_selection_card,
    render_source_recommendations,
)
from .source_gaps import recommend_sources
from .store import Store
from .validation import validate_analysis_packet, validate_book_card, validate_framework_card
from . import hindsight
from .llm_compile import compile_with_llm


DEFAULT_DB = Path.home() / ".bookcompiler" / "library.db"


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _store(args: argparse.Namespace) -> Store:
    return Store(args.db)


def _cmd_init(args: argparse.Namespace) -> int:
    store = _store(args)
    store.close()
    print(f"initialized db={args.db}")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    store = _store(args)
    parsed = parse_book(args.path, title=args.title, author=args.author, disciplines=args.discipline or [])
    store.add_book(parsed)
    store.close()
    print(f"book_id={parsed.book_id}")
    print(f"title={parsed.title}")
    print(f"chapters={len(parsed.chapters)} chunks={len(parsed.chunks)}")
    return 0


def _cmd_books(args: argparse.Namespace) -> int:
    store = _store(args)
    books = store.list_books()
    if not books:
        store.close()
        print("no books")
        return 0
    for book in books:
        frameworks = store.list_frameworks(book_ids=[book["book_id"]])
        print(
            f"{book['book_id']}  {book['status']:<10}  {book['title']}  "
            f"({', '.join(book.get('disciplines', []))})  frameworks={len(frameworks)}"
        )
    store.close()
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    store = _store(args)
    book = store.get_book(args.book_id)
    if not book:
        store.close()
        print(f"unknown book_id={args.book_id}")
        return 1
    payload = {
        "book": book,
        "book_card": store.get_book_card(args.book_id),
        "frameworks": store.list_frameworks(book_ids=[args.book_id]),
        "edges": store.list_edges(src_id=args.book_id),
    }
    store.close()
    _print_json(payload)
    return 0


def _cmd_export_text(args: argparse.Namespace) -> int:
    store = _store(args)
    book = store.get_book(args.book_id)
    if not book:
        store.close()
        print(f"unknown book_id={args.book_id}")
        return 1
    chunks = store.get_chunks(args.book_id)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    by_chapter: dict[tuple[int, str], list[Any]] = {}
    for chunk in chunks:
        by_chapter.setdefault((chunk.chapter_index, chunk.chapter_title), []).append(chunk)
    structure_lines = [f"# {book['title']}", "", f"Author: {book['author']}", "", "## Chapters", ""]
    for (index, title), items in sorted(by_chapter.items()):
        filename = f"chapter_{index:03d}.md"
        structure_lines.append(f"- {index}. {title} -> {filename} ({len(items)} chunks)")
        body = "\n\n".join(item.text for item in items)
        (out / filename).write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    (out / "structure.md").write_text("\n".join(structure_lines) + "\n", encoding="utf-8")
    store.close()
    print(f"exported {len(by_chapter)} chapters to {out}")
    return 0


def _cmd_compile(args: argparse.Namespace) -> int:
    store = _store(args)
    patch = json.loads(Path(args.patch).read_text(encoding="utf-8")) if args.patch else None
    result = compile_book(store, args.book_id, patch=patch)
    store.close()
    print(f"book_id={result.book_id}")
    print(f"frameworks={len(result.frameworks)}")
    print(f"issues={len(result.issues)}")
    for issue in result.issues:
        print(f"{issue.severity}: {issue.code}: {issue.message}")
    return 1 if any(issue.severity == "error" for issue in result.issues) else 0


def _cmd_compile_llm(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        requested = list(args.book_id or [])
        if args.all_ingested:
            requested.extend(
                book["book_id"]
                for book in store.list_books()
                if book.get("status") != "compiled"
            )
        requested = list(dict.fromkeys(book_id for book_id in requested if book_id))
        if not requested:
            print("no books selected")
            return 2
        config = None
        if args.model or args.base_url or args.provider:
            from .llm_compile import _reader_config

            config = _reader_config(
                provider_override=args.provider or None,
                model_override=args.model or None,
                base_url_override=args.base_url or None,
            )
        failures = 0
        for index, book_id in enumerate(requested, start=1):
            book = store.get_book(book_id)
            if not book:
                print(f"[{index}/{len(requested)}] {book_id}: unknown book")
                failures += 1
                continue
            if book.get("status") == "compiled" and not args.force:
                print(f"[{index}/{len(requested)}] skip compiled: {book.get('title', book_id)}")
                continue
            print(f"[{index}/{len(requested)}] reading: {book.get('title', book_id)}")
            try:
                result = compile_with_llm(
                    store,
                    book_id,
                    max_chunks=args.max_chunks,
                    evidence_chars=args.evidence_chars,
                    config=config,
                )
            except Exception as exc:  # noqa: BLE001 - batch must continue
                failures += 1
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                continue
            print(
                f"  OK frameworks={result['frameworks']} evidence={result['evidence_chunks']} "
                f"status={result['book_status']} patch={result['patch_path']}"
            )
            warnings = [issue for issue in result.get("issues", []) if issue.get("severity") == "warning"]
            for warning in warnings[:5]:
                print(f"  warning: {warning.get('code')}: {warning.get('message')}")
        return 1 if failures else 0
    finally:
        store.close()


def _proposal_from_args(args: argparse.Namespace):
    store = _store(args)
    proposal = build_proposal(
        store,
        mode=args.mode,
        query=args.query,
        lenses=args.lenses or ["economics", "politics", "law"],
        book_ids=args.books or [],
        framework_ids=args.frameworks or [],
        direction=args.direction or "",
    )
    return store, proposal


def _cmd_source_gaps(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        recommendations = recommend_sources(
            store,
            args.query,
            lenses=args.lenses or ["economics", "politics", "law"],
            direction=args.direction or "",
            limit=args.limit,
        )
    finally:
        store.close()
    if args.format == "text":
        lines = ["# Source gap report", ""]
        lines.append(f"- Query: {args.query}")
        lines.append(f"- Lenses: {', '.join(args.lenses or ['economics', 'politics', 'law'])}")
        if args.direction:
            lines.append(f"- Direction: {args.direction}")
        lines.append("")
        lines.extend(render_source_recommendations(recommendations).splitlines())
        print("\n".join(lines))
    else:
        _print_json(
            {
                "query": args.query,
                "lenses": args.lenses or ["economics", "politics", "law"],
                "direction": args.direction or "",
                "source_recommendations": recommendations,
            }
        )
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    store, proposal = _proposal_from_args(args)
    store.close()
    if args.format == "text":
        print(render_selection_card(proposal))
    else:
        _print_json(proposal.to_dict())
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    store, proposal = _proposal_from_args(args)
    if proposal.requires_confirmation and not args.confirm:
        store.close()
        if args.format == "text":
            print(render_selection_card(proposal))
        else:
            _print_json(proposal.to_dict())
        print("confirmation_required=specified|specified+recommended|recommended")
        return 2
    packet = create_analysis(
        store,
        args.query,
        args.lenses or ["economics", "politics", "law"],
        proposal,
        args.confirm or "specified+recommended",
    )
    store.close()
    if args.render:
        memo = render_memo(packet.to_dict())
        if args.out:
            Path(args.out).write_text(memo, encoding="utf-8")
            print(f"wrote {args.out}")
        else:
            print(memo)
    else:
        _print_json(packet.to_dict())
    return 0
def _cmd_render(args: argparse.Namespace) -> int:
    store = _store(args)
    packet = store.get_analysis(args.analysis_id)
    store.close()
    if not packet:
        print(f"unknown analysis_id={args.analysis_id}")
        return 1
    memo = render_memo(packet)
    if args.out:
        Path(args.out).write_text(memo, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(memo)
    return 0


def _cmd_analysis_apply(args: argparse.Namespace) -> int:
    store = _store(args)
    patch = json.loads(Path(args.patch).read_text(encoding="utf-8"))
    try:
        packet = apply_analysis_patch(store, args.analysis_id, patch)
    except AnalysisValidationError as exc:
        store.close()
        _print_json([issue.to_dict() for issue in exc.issues])
        return 1
    store.close()
    _print_json(packet.to_dict())
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    store = _store(args)
    issues = []
    if args.analysis:
        packet = store.get_analysis(args.analysis)
        if not packet:
            store.close()
            print(f"unknown analysis_id={args.analysis}")
            return 1
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
        chunks_by_book = {book_id: store.get_chunks(book_id) for book_id in sorted(book_ids)}
        issues = validate_analysis_packet(packet, chunks_by_book)
    elif args.book:
        chunks = store.get_chunks(args.book)
        card = store.get_book_card(args.book)
        if not card:
            from .models import ValidationIssue

            issues.append(ValidationIssue("error", "missing_book_card", "Book has no compiled card", args.book))
        else:
            issues.extend(validate_book_card(card, chunks))
        for framework in store.list_frameworks(book_ids=[args.book]):
            issues.extend(validate_framework_card(framework, chunks))
    else:
        store.close()
        print("provide --book or --analysis")
        return 1
    store.close()
    payload = [issue.to_dict() for issue in issues]
    _print_json(payload)
    return 1 if any(issue.get("severity") == "error" for issue in payload) else 0


def _cmd_feedback(args: argparse.Namespace) -> int:
    store = _store(args)
    feedback_id = store.add_feedback(
        args.analysis,
        args.rating,
        args.note,
        error_labels=args.error or [],
        preferred_book_ids=args.prefer_book or [],
        preferred_framework_ids=args.prefer_framework or [],
        missing_evidence=args.missing_evidence or "",
        outcome=args.outcome or "",
    )
    store.close()
    note = (args.note or "").strip()
    outcome = (args.outcome or "").strip()
    if note or outcome or args.error:
        hindsight.retain(
            f"BookCompiler feedback (rating={args.rating}/5). "
            f"Errors: {', '.join(args.error) or 'none'}. "
            f"Note: {note or 'none'}. Outcome: {outcome or 'none'}.",
            context="BookCompiler feedback",
            document_id=f"feedback-{feedback_id}",
            tags=["feedback"] + list(args.error or []),
            metadata={"source": "bookcompiler", "kind": "feedback", "rating": args.rating},
        )
    print(f"feedback_id={feedback_id}")
    return 0


def _reading_scores_from_args(args: argparse.Namespace) -> dict[str, float]:
    scores: dict[str, Any] = {}
    if getattr(args, "scores", ""):
        payload = json.loads(args.scores)
        if not isinstance(payload, dict):
            raise ValueError("--scores must be a JSON object")
        scores.update(payload)
    if getattr(args, "scores_file", ""):
        payload = json.loads(Path(args.scores_file).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("--scores-file must contain a JSON object")
        scores.update(payload)
    for item in getattr(args, "score", []) or []:
        if "=" not in item:
            raise ValueError("--score must look like dimension=value, e.g. source_fidelity=8")
        key, value = item.split("=", 1)
        scores[key.strip()] = float(value)
    return scores


def _cmd_reading_eval(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        evaluation = evaluate_reading(
            store,
            args.analysis,
            scores=_reading_scores_from_args(args),
            evaluator=args.evaluator,
            note=args.note or "",
            error_labels=args.error or [],
        )
    finally:
        store.close()
    _print_json(evaluation)
    return 0


def _cmd_reading_eval_list(args: argparse.Namespace) -> int:
    store = _store(args)
    evaluations = store.list_reading_evaluations(analysis_id=args.analysis or "", limit=args.limit)
    store.close()
    _print_json(evaluations)
    return 0


def _cmd_reading_report(args: argparse.Namespace) -> int:
    store = _store(args)
    report = reading_report(store, limit=args.limit)
    store.close()
    if args.out:
        Path(args.out).write_text(render_reading_report(report) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
        return 0
    if args.format == "markdown":
        print(render_reading_report(report))
    else:
        _print_json(report)
    return 0


def _cmd_reading_propose(args: argparse.Namespace) -> int:
    store = _store(args)
    proposals = [item for item in propose_evolutions(store, args.min_support) if item.get("source") == "reading_eval"]
    store.close()
    _print_json({"proposals": proposals})
    return 0


def _cmd_obsidian_export(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        manifest = export_vault(
            store,
            args.vault,
            subdir=args.subdir,
            book_ids=args.book or None,
            include_claims=not args.no_claims,
            include_entities=not args.no_entities,
            include_analyses=not args.no_analyses,
            overwrite=not args.no_overwrite,
        )
    finally:
        store.close()
    _print_json(manifest)
    return 0


def _cmd_coverage(args: argparse.Namespace) -> int:
    store = _store(args)
    _print_json(store.coverage())
    store.close()
    return 0


def _cmd_graph(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.node:
        outgoing = store.list_edges(src_id=args.node)
        incoming = store.list_edges(dst_id=args.node)
        edges = {edge["edge_id"]: edge for edge in outgoing + incoming}
        payload = list(edges.values())
    else:
        payload = store.list_edges()
    store.close()
    _print_json(payload)
    return 0


def _cmd_evolution_propose(args: argparse.Namespace) -> int:
    store = _store(args)
    proposals = propose_evolutions(store, min_support=args.min_support)
    store.close()
    _print_json(proposals)
    return 0


def _cmd_evolution_list(args: argparse.Namespace) -> int:
    store = _store(args)
    proposals = store.list_evolution_proposals(status=args.status)
    store.close()
    _print_json(proposals)
    return 0


def _cmd_evolution_decide(args: argparse.Namespace) -> int:
    store = _store(args)
    report = None
    if args.replay_report:
        report = json.loads(Path(args.replay_report).read_text(encoding="utf-8"))
    try:
        proposal = decide_evolution(store, args.proposal_id, args.status, args.note or "", report)
    except ValueError as exc:
        store.close()
        print(f"error: {exc}")
        return 1
    store.close()
    _print_json(proposal)
    return 0


def _cmd_memory(args: argparse.Namespace) -> int:
    store = _store(args)
    lessons = recall_memory(store, args.query or "", args.lenses or ["economics", "politics", "law"])
    store.close()
    _print_json(lessons)
    return 0


def _cmd_hindsight_status(args: argparse.Namespace) -> int:
    _print_json(hindsight.status())
    return 0


def _cmd_hindsight_retain(args: argparse.Namespace) -> int:
    _print_json(
        hindsight.retain(
            args.content,
            context=args.context,
            tags=args.tags or [],
            metadata={"source": "bookcompiler", "kind": "explicit"},
            asynchronous=not args.wait,
        )
    )
    return 0


def _cmd_hindsight_recall(args: argparse.Namespace) -> int:
    _print_json(hindsight.recall(args.query, limit=args.limit, budget=args.budget))
    return 0


def _cmd_embed(args: argparse.Namespace) -> int:
    from .embeddings import get_embedder

    store = _store(args)
    backend = get_embedder(allow_remote=not args.local)
    result = store.embed_pending(backend, book_id=args.book, force=args.rebuild)
    stats = store.embedding_stats(result.get("model", ""))
    store.close()
    _print_json({**result, "stats": stats})
    return 0


def _cmd_entities(args: argparse.Namespace) -> int:
    from .entities import (
        align_entities,
        alignment_audit,
        detect_entities,
        merge_entity_candidate,
        sync_merge_candidates,
        undo_entity_merge,
    )

    store = _store(args)
    payload: Any
    if args.action == "align":
        payload = align_entities(store)
    elif args.action == "audit":
        payload = alignment_audit(store, threshold=args.threshold, limit=args.limit)
    elif args.action == "sync-audit":
        payload = sync_merge_candidates(store, threshold=args.threshold, limit=args.limit)
    elif args.action == "candidates":
        payload = {"candidates": store.list_entity_merge_candidates(status=args.status, limit=args.limit)}
    elif args.action == "merge":
        payload = merge_entity_candidate(store, args.id, note=args.note, confirm=args.confirm)
    elif args.action == "undo-merge":
        payload = undo_entity_merge(store, args.id, note=args.note)
    elif args.action == "show":
        payload = store.get_entity(args.id)
        if payload is None:
            store.close()
            print(f"unknown entity_id={args.id}")
            return 1
    elif args.action == "detect":
        payload = detect_entities(store, args.query or "")
    else:
        payload = store.list_entities(query=args.query or "", cross_book_only=args.cross_book, limit=args.limit)
    store.close()
    _print_json(payload)
    return 0


def _cmd_retrieval(args: argparse.Namespace) -> int:
    from .retrieval import hybrid_search, retrieval_diagnostics

    store = _store(args)
    payload: Any
    if args.diagnostics:
        payload = retrieval_diagnostics(store, args.query, book_ids=args.books or None, limit=args.limit)
    else:
        payload = hybrid_search(
            store,
            args.query,
            book_ids=args.books or None,
            limit=args.limit,
            mode=args.mode,
            rerank=args.rerank,
        )
    store.close()
    _print_json(payload)
    return 0


def _cmd_eval_retrieval(args: argparse.Namespace) -> int:
    from .eval_retrieval import evaluate, load_cases

    store = _store(args)
    report = evaluate(store, load_cases(args.cases), k=args.k)
    store.close()
    if args.out:
        Path(args.out).write_text(__import__("json").dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_json(report)
    return 0


def _cmd_claims(args: argparse.Namespace) -> int:
    from .claims import build_claims, dismiss_conflict, list_claims, supersede_claim

    store = _store(args)
    payload: Any
    if args.action == "build":
        payload = build_claims(store, book_ids=args.books or None, limit_per_book=args.limit_per_book)
    elif args.action == "list":
        payload = list_claims(store, query=args.query or "", book_id=args.book or "", status=args.status or "", limit=args.limit)
    elif args.action == "show":
        payload = store.get_claim(args.id)
        if payload is None:
            store.close()
            print(f"unknown claim_id={args.id}")
            return 1
    elif args.action == "supersede":
        payload = supersede_claim(store, args.id, args.new_id, note=args.note, confirm=args.confirm, force=args.force)
    else:
        payload = dismiss_conflict(store, args.id, args.new_id, note=args.note)
    store.close()
    _print_json(payload)
    return 0


def _cmd_capability(args: argparse.Namespace) -> int:
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

    action = args.action
    if action == "presets":
        _print_json(list_presets())
        return 0
    if action == "list":
        _print_json(list_capabilities(root=args.root or None))
        return 0
    store = _store(args)
    try:
        if action == "status":
            payload = capability_status(args.domain or "", root=args.root or None)
        elif action == "route":
            payload = route_capability(
                store,
                args.query,
                lenses=args.lenses or None,
                limit=args.limit,
                root=args.root or None,
            )
        elif action == "impact":
            payload = capability_impact(store, args.book_id, root=args.root or None)
        elif action == "update":
            payload = update_capability(
                store,
                args.domain,
                book_ids=args.books or None,
                apply=args.apply,
                root=args.root or None,
            )
        elif action == "eval":
            payload = evaluate_capability(
                store,
                args.domain,
                cases_path=args.cases or None,
                limit=args.limit_cases,
                root=args.root or None,
            )
        else:
            payload = build_capability(
                store,
                args.domain,
                title=args.title,
                description=args.description,
                lenses=args.lenses or None,
                book_ids=args.books or None,
                direction=args.direction,
                max_books=args.max_books,
                root=args.root or None,
                version=args.version,
                force=args.force,
            )
    except ValueError as exc:
        payload = {"ok": False, "error": str(exc)}
    finally:
        store.close()
    _print_json(payload)
    return 0 if payload.get("ok") else 1


def _cmd_evolution_config(args: argparse.Namespace) -> int:
    from .evolution import get_evolution_config

    store = _store(args)
    payload = get_evolution_config(store)
    store.close()
    _print_json(payload)
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp import run_stdio

    run_stdio(args.db)
    return 0


def _cmd_gui(args: argparse.Namespace) -> int:
    from .gui import run_gui

    run_gui(args.db, host=args.host, port=args.port, open_browser=args.open)
    return 0


def _cmd_dashboard(args: argparse.Namespace) -> int:
    store = _store(args)
    markdown = render_dashboard(store)
    store.close()
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(markdown)
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    store = _store(args)
    payload = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = payload if isinstance(payload, list) else payload.get("cases", [])
    report = replay_cases(store, cases)
    store.close()
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        _print_json(report)
    return 0 if report["structural_pass_count"] == report["case_count"] else 1
def _cmd_doctor(args: argparse.Namespace) -> int:
    """Explain the runtime that will actually serve retrieval.

    Silent embedding fallback was the most dangerous operational failure:
    retrieval kept working but in a different vector space.  This command makes
    interpreter, model, coverage, reranker and learned-book state explicit.
    """
    import importlib
    import sys

    from .embeddings import get_embedder
    from .rerank import enabled as rerank_enabled
    from .rerank import model_name as rerank_model_name

    store = _store(args)
    warnings: list[str] = []
    try:
        backend = get_embedder()
        embedding = {"model": backend.model, "kind": backend.kind, "dim": backend.dim}
        stats = store.embedding_stats(backend.model)
        embedding.update(stats)
        if not embedding.get("dim"):
            for model_stats in stats.get("models", []):
                if model_stats.get("model") == backend.model and model_stats.get("dim"):
                    embedding["dim"] = model_stats["dim"]
                    break
        if stats.get("coverage", 0.0) < 1.0:
            warnings.append(
                f"embedding coverage is {stats.get('coverage', 0.0):.1%} for {backend.model}; "
                "run `bookcompiler embed` or check the model path"
            )
        if len(stats.get("models", [])) > 1:
            warnings.append(
                "multiple vector spaces exist in chunk_embeddings; retrieval uses only the active model"
            )
        expected_python = Path(__file__).resolve().parents[2] / ".venv" / "Scripts" / "python.exe"
        if expected_python.exists() and Path(sys.executable).resolve() != expected_python.resolve():
            warnings.append(
                f"running under {sys.executable}, not the project venv {expected_python}; "
                "model imports may fail and silently fall back"
            )
        packages: dict[str, str] = {}
        for name in ("numpy", "scipy", "sklearn", "torch", "transformers"):
            try:
                module = importlib.import_module(name)
                packages[name] = str(getattr(module, "__version__", "unknown"))
            except Exception as exc:  # noqa: BLE001 - doctor reports, never crashes
                packages[name] = f"ERROR: {type(exc).__name__}: {exc}"
                warnings.append(f"cannot import {name}: {type(exc).__name__}: {exc}")
        books = store.list_books()
        learned = store.learned_book_ids()
        payload = {
            "python": sys.executable,
            "python_version": sys.version.split()[0],
            "project_venv_python": str(expected_python),
            "db": str(args.db),
            "packages": packages,
            "embedding": embedding,
            "rerank": {
                "enabled": rerank_enabled(),
                "model": rerank_model_name(),
            },
            "books": {
                "total": len(books),
                "compiled": sum(1 for book in books if book.get("status") == "compiled"),
                "ingested": sum(1 for book in books if book.get("status") == "ingested"),
                "learned": len(learned),
                "learned_book_ids": sorted(learned),
            },
            "hindsight": hindsight.status(),
            "warnings": warnings,
        }
    finally:
        store.close()
    _print_json(payload)
    return 0


def _cmd_judge(args: argparse.Namespace) -> int:
    from .judge import JudgeConfig, JudgeError, judge_analysis

    store = _store(args)
    try:
        config = JudgeConfig(
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
            timeout=args.timeout,
        )
        result = judge_analysis(
            store,
            args.analysis,
            config=config,
            dry_run=args.dry_run,
            allow_draft=args.allow_draft,
            note=args.note or "",
            max_citations=args.max_citations,
            save_prompt=args.prompt_out or "",
        )
    except JudgeError as exc:
        store.close()
        print(f"judge error: {exc}")
        return 2
    finally:
        try:
            store.close()
        except Exception:
            pass
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        _print_json(result)
    return 0


def _cmd_judge_status(args: argparse.Namespace) -> int:
    from .judge import judge_status

    _print_json(judge_status())
    return 0


def _cmd_graphrag(args: argparse.Namespace) -> int:
    from .graph_rag import build_graph, graph_status, list_communities, query_graph, fused_search_report

    store = _store(args)
    try:
        if args.action == "build":
            payload = build_graph(store)
        elif args.action == "status":
            payload = graph_status(store)
        elif args.action == "communities":
            payload = {"communities": list_communities(store, limit=args.limit)}
        else:
            if args.mode == "graph":
                payload = query_graph(store, args.query, book_ids=args.books or None, limit=args.limit)
            else:
                payload = fused_search_report(store, args.query, book_ids=args.books or None, limit=args.limit)
    finally:
        store.close()
    _print_json(payload)
    return 0


def _cmd_obsidian_sync(args: argparse.Namespace) -> int:
    from .obsidian_sync import sync_obsidian

    store = _store(args)
    try:
        payload = sync_obsidian(
            store,
            args.vault,
            subdir=args.subdir,
            inbox=args.inbox,
            direction=args.direction,
            book_ids=args.books or None,
            overwrite=not args.no_overwrite,
            prune=args.prune,
            init=not args.no_init,
            preserve_edits=not args.overwrite_user_edits,
        )
    finally:
        store.close()
    _print_json(payload)
    return 0


def _cmd_hindsight_obsidian_sync(args: argparse.Namespace) -> int:
    from .hindsight_obsidian import sync_memories

    payload = sync_memories(
        args.vault,
        subdir=args.subdir,
        inbox=args.inbox,
        direction=args.direction,
    )
    _print_json(payload)
    return 0 if payload.get("ok") else 1


def _cmd_hindsight_obsidian_status(args: argparse.Namespace) -> int:
    from .hindsight_obsidian import hindsight_obsidian_status

    _print_json(hindsight_obsidian_status(args.vault))
    return 0


def _cmd_obsidian_sync_all(args: argparse.Namespace) -> int:
    from .hindsight_obsidian import sync_memories
    from .obsidian_sync import sync_obsidian

    store = _store(args)
    try:
        book = sync_obsidian(
            store,
            args.vault,
            subdir=args.subdir,
            inbox=args.inbox,
            direction=args.direction,
            book_ids=args.books or None,
            overwrite=not args.no_overwrite,
            prune=args.prune,
            init=not args.no_init,
            preserve_edits=not args.overwrite_user_edits,
        )
    finally:
        store.close()
    memories = sync_memories(
        args.vault,
        subdir=args.hindsight_subdir,
        inbox=args.hindsight_inbox,
        direction=args.direction,
    )
    payload = {
        "ok": bool(book and memories.get("ok")),
        "bookcompiler": book,
        "hindsight": memories,
    }
    _print_json(payload)
    return 0 if payload["ok"] else 1


def _cmd_obsidian_notes(args: argparse.Namespace) -> int:
    from .obsidian_sync import list_reader_notes

    store = _store(args)
    try:
        payload = {
            "notes": list_reader_notes(
                store,
                query=args.query or "",
                target_type=args.target_type or "",
                target_id=args.target_id or "",
                status=args.status,
                limit=args.limit,
            )
        }
    finally:
        store.close()
    _print_json(payload)
    return 0


def _cmd_obsidian_review(args: argparse.Namespace) -> int:
    from .obsidian_sync import grade_review, list_due_reviews

    store = _store(args)
    try:
        if args.grade is None:
            payload = {"due": list_due_reviews(store, due_before=args.due_before or "", limit=args.limit)}
        else:
            if not args.item:
                raise SystemExit("--item is required when --grade is used")
            payload = grade_review(store, args.item, args.grade, note=args.note or "")
    finally:
        store.close()
    _print_json(payload)
    return 0


def _cmd_obsidian_status(args: argparse.Namespace) -> int:
    from .obsidian_sync import obsidian_status

    store = _store(args)
    try:
        payload = obsidian_status(store, vault=args.vault or "")
    finally:
        store.close()
    _print_json(payload)
    return 0


def _cmd_orchestrate(args: argparse.Namespace) -> int:
    from .orchestration import orchestrate_analysis

    store = _store(args)
    try:
        packet = store.get_analysis(args.analysis)
        if not packet:
            raise SystemExit(f"unknown analysis_id: {args.analysis}")
        payload = orchestrate_analysis(
            store,
            packet,
            retrieval=packet.get("retrieval", {}),
            reader_notes=packet.get("reader_notes", []),
        )
    finally:
        store.close()
    _print_json(payload)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bookcompiler", description="Compile books into cited judgment frameworks.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="Initialize the local library")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("ingest", help="Ingest a TXT, Markdown, PDF, or EPUB book")
    p.add_argument("path")
    p.add_argument("--title")
    p.add_argument("--author", default="Unknown")
    p.add_argument("--discipline", action="append", default=[])
    p.set_defaults(func=_cmd_ingest)

    p = sub.add_parser("books", help="List the library")
    p.set_defaults(func=_cmd_books)

    p = sub.add_parser("show", help="Show a book, its card, frameworks, and provenance edges")
    p.add_argument("book_id")
    p.set_defaults(func=_cmd_show)

    p = sub.add_parser("export-text", help="Export chapter text for agent reading")
    p.add_argument("book_id")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_cmd_export_text)

    p = sub.add_parser("compile", help="Compile book cards and framework cards")
    p.add_argument("book_id")
    p.add_argument("--patch", help="Optional JSON patch produced by the agent")
    p.set_defaults(func=_cmd_compile)

    p = sub.add_parser("compile-llm", help="Read books with the configured cloud model and verify every citation")
    p.add_argument("book_id", nargs="*", default=[])
    p.add_argument("--all-ingested", action="store_true", help="Read every book that is not compiled yet")
    p.add_argument("--force", action="store_true", help="Recompile even when a book is already compiled")
    p.add_argument("--max-chunks", type=int, default=28, help="Evidence chunks sent to the reader (default 28)")
    p.add_argument("--evidence-chars", type=int, default=1200, help="Characters per evidence chunk (default 1200)")
    p.add_argument("--model", default="", help="Override the reader model")
    p.add_argument("--provider", default="", help="Override the reader provider")
    p.add_argument("--base-url", default="", help="Override the reader base URL")
    p.set_defaults(func=_cmd_compile_llm)

    p = sub.add_parser(
        "source-gaps",
        help="Suggest authoritative sources to download and ingest for an uncovered question",
    )
    p.add_argument("--query", required=True)
    p.add_argument("--lenses", nargs="+", default=["economics", "politics", "law"])
    p.add_argument("--direction", default="")
    p.add_argument("--limit", type=int, default=6)
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=_cmd_source_gaps)

    for name, helptext, func in [
        ("plan", "Show the selection card without running analysis", _cmd_plan),
        ("analyze", "Create an AnalysisPacket", _cmd_analyze),
    ]:
        p = sub.add_parser(name, help=helptext)
        p.add_argument("--mode", choices=["auto", "direction", "books"], required=True)
        p.add_argument("--query", required=True)
        p.add_argument("--lenses", nargs="+", default=["economics", "politics", "law"])
        p.add_argument("--books", nargs="*", default=[])
        p.add_argument("--frameworks", nargs="*", default=[])
        p.add_argument("--direction", default="")
        p.add_argument("--format", choices=["json", "text"], default="json")
        if name == "analyze":
            p.add_argument("--confirm", choices=["specified", "specified+recommended", "recommended"], default="")
            p.add_argument("--render", action="store_true")
            p.add_argument("--out")
        p.set_defaults(func=func)

    p = sub.add_parser("render", help="Render a stored AnalysisPacket to Markdown")
    p.add_argument("analysis_id")
    p.add_argument("--out")
    p.set_defaults(func=_cmd_render)

    p = sub.add_parser("analysis-apply", help="Apply and validate an agent-written AnalysisPacket patch")
    p.add_argument("analysis_id")
    p.add_argument("--patch", required=True)
    p.set_defaults(func=_cmd_analysis_apply)

    p = sub.add_parser("validate", help="Validate a compiled book or analysis")
    p.add_argument("--book")
    p.add_argument("--analysis")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("feedback", help="Record structured feedback for self-evolution")
    p.add_argument("--analysis", required=True)
    p.add_argument("--rating", type=int, choices=range(1, 6), required=True)
    p.add_argument("--note", default="")
    p.add_argument("--error", action="append", default=[], help="Error label such as retrieval_miss or overconfidence")
    p.add_argument("--prefer-book", action="append", default=[])
    p.add_argument("--prefer-framework", action="append", default=[])
    p.add_argument("--missing-evidence", default="")
    p.add_argument("--outcome", default="")
    p.set_defaults(func=_cmd_feedback)

    p = sub.add_parser("obsidian-export", help="Export books, frameworks, claims, and entities as an Obsidian vault")
    p.add_argument("--vault", required=True, help="Obsidian vault root")
    p.add_argument("--subdir", default="BookCompiler", help="Folder inside the vault; defaults to BookCompiler")
    p.add_argument("--book", action="append", default=[], help="Only export this book_id (repeatable)")
    p.add_argument("--no-claims", action="store_true")
    p.add_argument("--no-entities", action="store_true")
    p.add_argument("--no-analyses", action="store_true")
    p.add_argument("--no-overwrite", action="store_true")
    p.set_defaults(func=_cmd_obsidian_export)

    p = sub.add_parser("reading-eval", help="Score how well an answer used the learned books")
    p.add_argument("--analysis", required=True)
    p.add_argument("--score", action="append", default=[], help="dimension=0..10, e.g. source_fidelity=8")
    p.add_argument("--scores", default="", help="JSON object of dimension -> 0..10")
    p.add_argument("--scores-file", default="", help="Path to a JSON object of dimension -> 0..10")
    p.add_argument("--evaluator", default="auto", help="auto, human, llm_judge, or mixed")
    p.add_argument("--note", default="")
    p.add_argument("--error", action="append", default=[])
    p.set_defaults(func=_cmd_reading_eval)

    p = sub.add_parser("reading-eval-list", help="List reading-effectiveness evaluations")
    p.add_argument("--analysis", default="")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=_cmd_reading_eval_list)

    p = sub.add_parser("reading-report", help="Aggregate reading-effectiveness scores and weak dimensions")
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--format", choices=["json", "markdown"], default="markdown")
    p.add_argument("--out", default="")
    p.set_defaults(func=_cmd_reading_report)

    p = sub.add_parser("reading-propose", help="Create evolution proposals from weak reading dimensions")
    p.add_argument("--min-support", type=int, default=1)
    p.set_defaults(func=_cmd_reading_propose)

    p = sub.add_parser("coverage", help="Show library coverage by discipline and lens")
    p.set_defaults(func=_cmd_coverage)

    p = sub.add_parser("graph", help="Show provenance edges")
    p.add_argument("--node", default=None)
    p.set_defaults(func=_cmd_graph)

    p = sub.add_parser("dashboard", help="Render a Markdown dashboard of the learned library")
    p.add_argument("--out")
    p.set_defaults(func=_cmd_dashboard)

    p = sub.add_parser("memory", help="Recall feedback and memory lessons for a query")
    p.add_argument("--query", default="")
    p.add_argument("--lenses", nargs="+", default=["economics", "politics", "law"])
    p.set_defaults(func=_cmd_memory)

    p = sub.add_parser("evolution-propose", help="Create evidence-backed self-evolution proposals")
    p.add_argument("--min-support", type=int, default=1)
    p.set_defaults(func=_cmd_evolution_propose)

    p = sub.add_parser("evolution-list", help="List self-evolution proposals")
    p.add_argument("--status", choices=["proposed", "accepted", "rejected", "shadow", "promoted", "rolled_back"])
    p.set_defaults(func=_cmd_evolution_list)

    p = sub.add_parser("evolution-decide", help="Accept, reject, shadow, promote, or roll back a proposal")
    p.add_argument("proposal_id")
    p.add_argument("--status", required=True, choices=["accepted", "rejected", "shadow", "promoted", "rolled_back"])
    p.add_argument("--note", default="")
    p.add_argument("--replay-report", default="", help="Required for promotion; output of `replay --out`")
    p.set_defaults(func=_cmd_evolution_decide)

    p = sub.add_parser("embed", help="Build or rebuild chunk embeddings")
    p.add_argument("--book", default=None)
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--local", action="store_true", help="Ignore a configured remote embedding backend")
    p.set_defaults(func=_cmd_embed)

    p = sub.add_parser("entities", help="Align and inspect cross-book entities")
    p.add_argument("action", choices=["align", "audit", "sync-audit", "candidates", "list", "show", "detect", "merge", "undo-merge"])
    p.add_argument("--id", default="")
    p.add_argument("--query", default="")
    p.add_argument("--cross-book", action="store_true")
    p.add_argument("--status", default="")
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--note", default="")
    p.add_argument("--threshold", type=float, default=0.62)
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(func=_cmd_entities)

    p = sub.add_parser("claims", help="Build and inspect the claim-level knowledge graph")
    p.add_argument("action", choices=["build", "list", "show", "supersede", "dismiss"])
    p.add_argument("--id", default="")
    p.add_argument("--new-id", default="")
    p.add_argument("--books", nargs="*", default=[])
    p.add_argument("--book", default="")
    p.add_argument("--query", default="")
    p.add_argument("--status", default="")
    p.add_argument("--note", default="")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--limit-per-book", type=int, default=120)
    p.add_argument("--confirm", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=_cmd_claims)

    p = sub.add_parser("capability", help="Build, inspect, route, and evaluate domain capability packs")
    p.add_argument("action", choices=["list", "presets", "status", "build", "route", "impact", "update", "eval"])
    p.add_argument("--domain", default="")
    p.add_argument("--title", default="")
    p.add_argument("--description", default="")
    p.add_argument("--lenses", nargs="*", default=[])
    p.add_argument("--books", nargs="*", default=[])
    p.add_argument("--direction", default="")
    p.add_argument("--book-id", default="")
    p.add_argument("--query", default="")
    p.add_argument("--cases", default="")
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--limit-cases", type=int, default=0)
    p.add_argument("--max-books", type=int, default=8)
    p.add_argument("--version", default="")
    p.add_argument("--root", default="")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=_cmd_capability)

    p = sub.add_parser("retrieval", help="Run hybrid retrieval and show score breakdowns")
    p.add_argument("--query", required=True)
    p.add_argument("--books", nargs="*", default=[])
    p.add_argument("--mode", choices=["hybrid", "lexical"], default="hybrid")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--diagnostics", action="store_true")
    rerank_group = p.add_mutually_exclusive_group()
    rerank_group.add_argument("--rerank", dest="rerank", action="store_true", default=None)
    rerank_group.add_argument("--no-rerank", dest="rerank", action="store_false")
    p.set_defaults(func=_cmd_retrieval)

    p = sub.add_parser("eval-retrieval", help="Compare lexical, hybrid, and hybrid+rerank retrieval")
    p.add_argument("--cases", default=None, help="JSON file with query/expected_terms cases")
    p.add_argument("--k", type=int, default=8)
    p.add_argument("--out", default=None)
    p.set_defaults(func=_cmd_eval_retrieval)

    p = sub.add_parser("evolution-config", help="Show the active bounded evolution config")
    p.set_defaults(func=_cmd_evolution_config)

    p = sub.add_parser("hindsight-status", help="Check the Hindsight long-term memory connection")
    p.set_defaults(func=_cmd_hindsight_status)

    p = sub.add_parser("hindsight-retain", help="Store one durable lesson in Hindsight")
    p.add_argument("content")
    p.add_argument("--context", default="BookCompiler explicit memory")
    p.add_argument("--tags", nargs="+", default=[])
    p.add_argument("--wait", action="store_true", help="Wait for fact extraction instead of running async")
    p.set_defaults(func=_cmd_hindsight_retain)

    p = sub.add_parser("hindsight-recall", help="Recall durable lessons from Hindsight")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--budget", choices=["low", "mid", "high"], default="low")
    p.set_defaults(func=_cmd_hindsight_recall)

    p = sub.add_parser("judge", help="Run an independent blind judge and persist its nine scores")
    p.add_argument("--analysis", required=True)
    p.add_argument("--provider", choices=["ollama", "openai", "openai-compatible"], default="ollama")
    p.add_argument("--model", default="qwen2.5:7b-instruct-q4_K_M")
    p.add_argument("--base-url", default="http://127.0.0.1:11434")
    p.add_argument("--timeout", type=float, default=240.0)
    p.add_argument("--dry-run", action="store_true", help="Print the blind prompt without calling a model")
    p.add_argument("--allow-draft", action="store_true")
    p.add_argument("--prompt-out", default="")
    p.add_argument("--max-citations", type=int, default=24)
    p.add_argument("--note", default="")
    p.add_argument("--out", default="")
    p.set_defaults(func=_cmd_judge)

    p = sub.add_parser("judge-status", help="Show the configured independent judge and its boundary")
    p.set_defaults(func=_cmd_judge_status)

    p = sub.add_parser("graphrag", help="Build, inspect, or query the GraphRAG sidecar")
    p.add_argument("action", choices=["build", "status", "query", "communities"])
    p.add_argument("--query", default="")
    p.add_argument("--books", nargs="*", default=[])
    p.add_argument("--mode", choices=["hybrid", "graph"], default="hybrid")
    p.add_argument("--limit", type=int, default=12)
    p.set_defaults(func=_cmd_graphrag)

    p = sub.add_parser("obsidian-sync", help="Controlled two-way Obsidian sync (generated notes out, inbox notes in)")
    p.add_argument("--vault", default="", help="Obsidian vault; defaults to BOOKCOMPILER_OBSIDIAN_VAULT")
    p.add_argument("--subdir", default="")
    p.add_argument("--inbox", default="")
    p.add_argument("--direction", choices=["export", "import", "both"], default="both")
    p.add_argument("--books", nargs="*", default=[])
    p.add_argument("--no-overwrite", action="store_true")
    p.add_argument("--overwrite-user-edits", action="store_true", help="Allow generated notes to overwrite files you edited")
    p.add_argument("--prune", action="store_true", help="Mark notes missing when deleted from the inbox")
    p.add_argument("--no-init", action="store_true")
    p.set_defaults(func=_cmd_obsidian_sync)

    p = sub.add_parser("hindsight-obsidian-sync", help="Mirror Hindsight memories to Obsidian and push edits back")
    p.add_argument("--vault", default="", help="Obsidian vault; defaults to BOOKCOMPILER_OBSIDIAN_VAULT")
    p.add_argument("--subdir", default="", help="Defaults to HINDSIGHT_OBSIDIAN_SUBDIR")
    p.add_argument("--inbox", default="", help="Inbox for new memories; defaults to HINDSIGHT_OBSIDIAN_INBOX")
    p.add_argument("--direction", choices=["export", "import", "both"], default="both")
    p.set_defaults(func=_cmd_hindsight_obsidian_sync)

    p = sub.add_parser("hindsight-obsidian-status", help="Show the Hindsight Obsidian mirror status")
    p.add_argument("--vault", default="")
    p.set_defaults(func=_cmd_hindsight_obsidian_status)

    p = sub.add_parser("obsidian-sync-all", help="Sync BookCompiler results and Hindsight memories with Obsidian")
    p.add_argument("--vault", default="", help="Obsidian vault; defaults to BOOKCOMPILER_OBSIDIAN_VAULT")
    p.add_argument("--subdir", default="")
    p.add_argument("--inbox", default="")
    p.add_argument("--direction", choices=["export", "import", "both"], default="both")
    p.add_argument("--books", nargs="*", default=[])
    p.add_argument("--no-overwrite", action="store_true")
    p.add_argument("--overwrite-user-edits", action="store_true")
    p.add_argument("--prune", action="store_true")
    p.add_argument("--no-init", action="store_true")
    p.add_argument("--hindsight-subdir", default="")
    p.add_argument("--hindsight-inbox", default="")
    p.set_defaults(func=_cmd_obsidian_sync_all)

    p = sub.add_parser("obsidian-notes", help="List imported reader notes (memory, never citations)")
    p.add_argument("--query", default="")
    p.add_argument("--target-type", default="")
    p.add_argument("--target-id", default="")
    p.add_argument("--status", default="active")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=_cmd_obsidian_notes)

    p = sub.add_parser("obsidian-review", help="List due reading notes or grade one review item")
    p.add_argument("--item", default="")
    p.add_argument("--grade", type=int, choices=range(0, 6), default=None)
    p.add_argument("--due-before", default="")
    p.add_argument("--note", default="")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=_cmd_obsidian_review)

    p = sub.add_parser("obsidian-status", help="Show Obsidian sync/note/review counts")
    p.add_argument("--vault", default="")
    p.set_defaults(func=_cmd_obsidian_status)

    p = sub.add_parser("orchestrate", help="Run the automatic multi-role trace for an existing analysis")
    p.add_argument("--analysis", required=True)
    p.set_defaults(func=_cmd_orchestrate)

    p = sub.add_parser("doctor", help="Check interpreter, embedding coverage, reranker, and learned books")
    p.set_defaults(func=_cmd_doctor)

    p = sub.add_parser("mcp", help="Run the BookCompiler MCP server over stdio")
    p.set_defaults(func=_cmd_mcp)

    p = sub.add_parser("gui", help="Start the local web GUI")
    p.add_argument("--db", default=argparse.SUPPRESS, help="SQLite database path (overrides the global --db)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true", help="Open the GUI in the default browser")
    p.set_defaults(func=_cmd_gui)

    p = sub.add_parser("replay", help="Run structural replay cases and report regressions")
    p.add_argument("cases")
    p.add_argument("--out")
    p.set_defaults(func=_cmd_replay)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())