from __future__ import annotations

import json
import mimetypes
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import hindsight
from .analysis import AnalysisValidationError, apply_analysis_patch, create_analysis
from .compiler import compile_book
from .embeddings import get_embedder
from .entities import (
    align_entities,
    alignment_audit,
    detect_entities,
    merge_entity_candidate,
    sync_merge_candidates,
    undo_entity_merge,
)
from .evolution import decide_evolution, get_evolution_config, is_executable, propose_evolutions, recall_memory, replay_cases
from .modes import build_proposal
from .retrieval import hybrid_search, retrieval_diagnostics
from .parsing import parse_book
from .store import Store

VERSION = "0.5.1"
WEB_DIR = Path(__file__).with_name("web")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value).__name__}")


class GuiHandler(BaseHTTPRequestHandler):
    server_version = "BookCompilerGUI/0.5"
    db_path: Path = Path("library.db")

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep the terminal quiet unless the user explicitly asks for access logs.
        import os

        if os.environ.get("BOOKCOMPILER_GUI_LOG"):
            super().log_message(fmt, *args)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _send_error_json(self, status: int, message: str, **extra: Any) -> None:
        payload = {"ok": False, "error": message}
        payload.update(extra)
        self._send_json(payload, status)

    def _store(self) -> Store:
        return Store(self.db_path)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        if length > 20 * 1024 * 1024:
            raise ValueError("request body is too large (limit 20 MB)")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON body: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in {"/", "/index.html"}:
                self._serve_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
                return
            if path == "/app.js":
                self._serve_file(WEB_DIR / "app.js", "application/javascript; charset=utf-8")
                return
            if path == "/style.css":
                self._serve_file(WEB_DIR / "style.css", "text/css; charset=utf-8")
                return
            if path == "/api/health":
                self._send_json({"ok": True, "version": VERSION})
                return
            if path == "/api/status":
                self._api_status()
                return
            if path == "/api/books":
                self._api_books()
                return
            if path == "/api/frameworks":
                self._api_frameworks()
                return
            if path.startswith("/api/books/"):
                self._api_book(path.split("/")[3])
                return
            if path == "/api/analyses":
                self._api_analyses()
                return
            if path.startswith("/api/analysis/"):
                self._api_analysis(path.split("/")[3])
                return
            if path == "/api/memory":
                self._api_memory(parse_qs(parsed.query))
                return
            if path == "/api/evolution":
                self._api_evolution()
                return
            if path == "/api/graph":
                self._api_graph(parse_qs(parsed.query))
                return
            if path == "/api/entities":
                self._api_entities(parse_qs(parsed.query))
                return
            if path == "/api/entities/audit":
                self._api_entities_audit(parse_qs(parsed.query))
                return
            if path == "/api/entities/candidates":
                self._api_entity_candidates(parse_qs(parsed.query))
                return
            if path == "/api/claims":
                self._api_claims(parse_qs(parsed.query))
                return
            if path.startswith("/api/claims/"):
                self._api_claim_detail(path.split("/")[3])
                return
            if path.startswith("/api/entities/"):
                self._api_entity(path.split("/")[3])
                return
            if path == "/api/retrieval":
                self._api_retrieval(parse_qs(parsed.query))
                return
            if path == "/api/judge/status":
                self._api_judge_status()
                return
            if path == "/api/models":
                self._api_models()
                return
            if path == "/api/graphrag/status":
                self._api_graphrag_status()
                return
            if path == "/api/graphrag/query":
                self._api_graphrag_query(parse_qs(parsed.query))
                return
            if path == "/api/graphrag/communities":
                self._api_graphrag_communities(parse_qs(parsed.query))
                return
            if path == "/api/obsidian/status":
                self._api_obsidian_status(parse_qs(parsed.query))
                return
            if path == "/api/obsidian/notes":
                self._api_obsidian_notes(parse_qs(parsed.query))
                return
            if path == "/api/obsidian/reviews":
                self._api_obsidian_reviews(parse_qs(parsed.query))
                return
            if path == "/api/obsidian/hindsight/status":
                self._api_hindsight_obsidian_status(parse_qs(parsed.query))
                return
            self._send_error_json(404, f"unknown route: {path}")
        except Exception as exc:  # surface a readable error to the local user
            self._send_error_json(500, f"{type(exc).__name__}: {exc}")

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_json()
            if path == "/api/plan":
                self._api_plan(body)
                return
            if path == "/api/analyze":
                self._api_analyze(body)
                return
            if path == "/api/analysis-patch":
                self._api_analysis_patch(body)
                return
            if path == "/api/feedback":
                self._api_feedback(body)
                return
            if path == "/api/evolution/propose":
                self._api_evolution_propose(body)
                return
            if path == "/api/evolution/decide":
                self._api_evolution_decide(body)
                return
            if path == "/api/replay":
                self._api_replay(body)
                return
            if path == "/api/ingest":
                self._api_ingest(body)
                return
            if path == "/api/compile":
                self._api_compile(body)
                return
            if path == "/api/entities/align":
                self._api_entities_align(body)
                return
            if path == "/api/entities/sync-audit":
                self._api_entities_sync_audit(body)
                return
            if path == "/api/entities/merge":
                self._api_entities_merge(body)
                return
            if path == "/api/entities/undo-merge":
                self._api_entities_undo_merge(body)
                return
            if path == "/api/entities/reject":
                self._api_entities_reject(body)
                return
            if path == "/api/claims/build":
                self._api_claims_build(body)
                return
            if path == "/api/claims/supersede":
                self._api_claims_supersede(body)
                return
            if path == "/api/claims/dismiss":
                self._api_claims_dismiss(body)
                return
            if path == "/api/embeddings/backfill":
                self._api_embeddings_backfill(body)
                return
            if path == "/api/judge":
                self._api_judge(body)
                return
            if path == "/api/models/judge":
                self._api_models_judge(body)
                return
            if path == "/api/models/hermes":
                self._api_models_hermes(body)
                return
            if path == "/api/models/hindsight":
                self._api_models_hindsight(body)
                return
            if path == "/api/models/preset":
                self._api_models_preset(body)
                return
            if path == "/api/graphrag/build":
                self._api_graphrag_build(body)
                return
            if path == "/api/obsidian/sync":
                self._api_obsidian_sync(body)
                return
            if path == "/api/obsidian/grade":
                self._api_obsidian_grade(body)
                return
            if path == "/api/obsidian/hindsight/sync":
                self._api_hindsight_obsidian_sync(body)
                return
            if path == "/api/obsidian/sync-all":
                self._api_obsidian_sync_all(body)
                return
            self._send_error_json(404, f"unknown route: {path}")
        except AnalysisValidationError as exc:
            self._send_error_json(400, str(exc), issues=[issue.to_dict() for issue in exc.issues])
        except FileNotFoundError as exc:
            self._send_error_json(404, str(exc))
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            self._send_error_json(500, f"{type(exc).__name__}: {exc}")

    def _serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self._send_error_json(404, f"missing GUI asset: {path.name}")
            return
        body = path.read_bytes()
        self._send(200, body, content_type)

    # ---- API implementations -------------------------------------------------

    def _api_status(self) -> None:
        store = self._store()
        try:
            coverage = store.coverage()
            payload = {
                "ok": True,
                "version": VERSION,
                "db": str(self.db_path),
                "coverage": coverage,
                "embedding": store.embedding_stats(get_embedder().model),
                "entities": store.entity_stats(),
                "evolution": get_evolution_config(store),
                "hindsight": hindsight.status(),
                "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            }
        finally:
            store.close()
        self._send_json(payload)

    def _api_books(self) -> None:
        store = self._store()
        try:
            books = store.list_books()
            result = []
            for book in books:
                book_id = book["book_id"]
                frameworks = store.list_frameworks(book_ids=[book_id])
                card = store.get_book_card(book_id)
                chunk_count = store.conn.execute("SELECT COUNT(*) FROM chunks WHERE book_id = ?", (book_id,)).fetchone()[0]
                result.append(
                    {
                        **book,
                        "framework_count": len(frameworks),
                        "chunk_count": chunk_count,
                        "card_status": (card or {}).get("status"),
                        "card_confidence": (card or {}).get("confidence"),
                        "one_line_thesis": (card or {}).get("one_line_thesis", ""),
                    }
                )
        finally:
            store.close()
        self._send_json({"ok": True, "books": result})

    def _api_frameworks(self) -> None:
        store = self._store()
        try:
            frameworks = store.list_frameworks()
            titles = {book["book_id"]: book["title"] for book in store.list_books()}
            result = [{**item, "book_title": titles.get(item.get("book_id"), "")} for item in frameworks]
        finally:
            store.close()
        self._send_json({"ok": True, "frameworks": result})

    def _api_book(self, book_id: str) -> None:
        store = self._store()
        try:
            book = store.get_book(book_id)
            if not book:
                self._send_error_json(404, f"unknown book_id: {book_id}")
                return
            chapters = [
                dict(row)
                for row in store.conn.execute(
                    "SELECT chapter_index, chapter_title, COUNT(*) AS chunk_count FROM chunks WHERE book_id = ? GROUP BY chapter_index, chapter_title ORDER BY chapter_index",
                    (book_id,),
                ).fetchall()
            ]
            payload = {
                "ok": True,
                "book": book,
                "book_card": store.get_book_card(book_id),
                "frameworks": store.list_frameworks(book_ids=[book_id]),
                "edges": store.list_edges(src_id=book_id),
                "chapters": chapters,
            }
        finally:
            store.close()
        self._send_json(payload)

    def _api_analyses(self) -> None:
        store = self._store()
        try:
            rows = store.list_analyses()
            result = []
            for packet in rows:
                selection = packet.get("selection", {}) if isinstance(packet.get("selection"), dict) else {}
                result.append(
                    {
                        "analysis_id": packet.get("analysis_id"),
                        "question": packet.get("question"),
                        "mode": packet.get("mode"),
                        "lenses": packet.get("lenses", []),
                        "status": packet.get("status"),
                        "created_at": packet.get("created_at"),
                        "conclusion": packet.get("conclusion", ""),
                        "book_count": len(selection.get("books", [])),
                        "citation_count": len(packet.get("citations", [])),
                        "choice": selection.get("choice"),
                    }
                )
        finally:
            store.close()
        self._send_json({"ok": True, "analyses": result})

    def _api_analysis(self, analysis_id: str) -> None:
        store = self._store()
        try:
            packet = store.get_analysis(analysis_id)
            if not packet:
                self._send_error_json(404, f"unknown analysis_id: {analysis_id}")
                return
            titles = {book["book_id"]: book["title"] for book in store.list_books()}
            payload = {"ok": True, "analysis": packet, "book_titles": titles}
        finally:
            store.close()
        self._send_json(payload)

    def _api_memory(self, query: dict[str, list[str]]) -> None:
        text = (query.get("query") or [""])[0]
        lenses = (query.get("lenses") or ["economics,politics,law"])[0].split(",")
        lenses = [item.strip() for item in lenses if item.strip()]
        store = self._store()
        try:
            lessons = recall_memory(store, text, lenses or ["economics", "politics", "law"])
        finally:
            store.close()
        self._send_json({"ok": True, "lessons": lessons})

    def _api_evolution(self) -> None:
        store = self._store()
        try:
            proposals = store.list_evolution_proposals()
            for proposal in proposals:
                proposal["executable"] = is_executable(proposal)
            config = get_evolution_config(store)
        finally:
            store.close()
        self._send_json({"ok": True, "proposals": proposals, "config": config})

    def _api_entities(self, query: dict[str, list[str]]) -> None:
        text = (query.get("query") or [""])[0]
        cross_book = (query.get("cross_book") or ["false"])[0].lower() in {"1", "true", "yes"}
        limit = int((query.get("limit") or ["100"])[0])
        store = self._store()
        try:
            entities = store.list_entities(query=text, cross_book_only=cross_book, limit=limit)
            detected = detect_entities(store, text) if text else []
            stats = store.entity_stats()
        finally:
            store.close()
        self._send_json({"ok": True, "entities": entities, "detected": detected, "stats": stats})

    def _api_entities_audit(self, query: dict[str, list[str]]) -> None:
        limit = int((query.get("limit") or ["50"])[0])
        store = self._store()
        try:
            report = alignment_audit(store, limit=limit)
        finally:
            store.close()
        self._send_json({"ok": True, "review_only": True, **report})

    def _api_entity(self, entity_id: str) -> None:
        store = self._store()
        try:
            entity = store.get_entity(entity_id)
        finally:
            store.close()
        if not entity:
            self._send_error_json(404, f"unknown entity_id: {entity_id}")
            return
        self._send_json({"ok": True, "entity": entity})

    def _api_entity_candidates(self, query: dict[str, list[str]]) -> None:
        status = (query.get("status") or [""])[0]
        limit = int((query.get("limit") or ["100"])[0])
        store = self._store()
        try:
            candidates = store.list_entity_merge_candidates(status=status, limit=limit)
        finally:
            store.close()
        self._send_json({"ok": True, "candidates": candidates})

    def _api_claim_detail(self, claim_id: str) -> None:
        store = self._store()
        try:
            claim = store.get_claim(claim_id)
        finally:
            store.close()
        if not claim:
            self._send_error_json(404, f"unknown claim_id: {claim_id}")
            return
        self._send_json({"ok": True, "claim": claim})

    def _api_entities_reject(self, body: dict[str, Any]) -> None:
        store = self._store()
        try:
            candidate = store.set_entity_merge_candidate(
                str(body.get("candidate_id", "")),
                "rejected",
                str(body.get("note", "reviewed: keep separate")),
            )
        finally:
            store.close()
        if not candidate:
            self._send_error_json(404, "unknown candidate_id")
            return
        self._send_json({"ok": True, "candidate": candidate})

    def _api_entities_sync_audit(self, body: dict[str, Any]) -> None:
        store = self._store()
        try:
            report = sync_merge_candidates(
                store,
                threshold=float(body.get("threshold", 0.62)),
                limit=int(body.get("limit", 50)),
            )
        finally:
            store.close()
        self._send_json({"ok": True, "review_only": True, **report})

    def _api_entities_merge(self, body: dict[str, Any]) -> None:
        store = self._store()
        try:
            result = merge_entity_candidate(
                store,
                str(body.get("candidate_id", "")),
                note=str(body.get("note", "")),
                confirm=bool(body.get("confirm", False)),
            )
        finally:
            store.close()
        self._send_json({"ok": True, **result})

    def _api_entities_undo_merge(self, body: dict[str, Any]) -> None:
        store = self._store()
        try:
            result = undo_entity_merge(store, str(body.get("candidate_id", "")), note=str(body.get("note", "")))
        finally:
            store.close()
        self._send_json({"ok": True, **result})

    def _api_claims(self, query: dict[str, list[str]]) -> None:
        from .claims import list_claims

        store = self._store()
        try:
            payload = list_claims(
                store,
                query=(query.get("query") or [""])[0],
                book_id=(query.get("book") or [""])[0],
                status=(query.get("status") or [""])[0],
                limit=int((query.get("limit") or ["100"])[0]),
            )
        finally:
            store.close()
        self._send_json({"ok": True, **payload})

    def _api_claims_build(self, body: dict[str, Any]) -> None:
        from .claims import build_claims

        store = self._store()
        try:
            payload = build_claims(
                store,
                book_ids=list(body.get("book_ids") or []) or None,
                limit_per_book=int(body.get("limit_per_book", 120)),
                replace=bool(body.get("replace", True)),
            )
        finally:
            store.close()
        self._send_json({"ok": True, **payload})

    def _api_claims_supersede(self, body: dict[str, Any]) -> None:
        from .claims import supersede_claim

        store = self._store()
        try:
            payload = supersede_claim(
                store,
                str(body.get("claim_id", "")),
                str(body.get("new_claim_id", "")),
                note=str(body.get("note", "")),
                confirm=bool(body.get("confirm", False)),
                force=bool(body.get("force", False)),
            )
        finally:
            store.close()
        self._send_json({"ok": True, **payload})

    def _api_claims_dismiss(self, body: dict[str, Any]) -> None:
        from .claims import dismiss_conflict

        store = self._store()
        try:
            payload = dismiss_conflict(store, str(body.get("claim_id", "")), str(body.get("new_claim_id", "")), note=str(body.get("note", "")))
        finally:
            store.close()
        self._send_json({"ok": True, **payload})

    def _api_entities_align(self, body: dict[str, Any]) -> None:
        store = self._store()
        try:
            stats = align_entities(store)
        finally:
            store.close()
        self._send_json({"ok": True, **stats})

    def _api_embeddings_backfill(self, body: dict[str, Any]) -> None:
        from .embeddings import get_embedder

        store = self._store()
        try:
            backend = get_embedder(allow_remote=not bool(body.get("local")))
            result = store.embed_pending(backend, book_id=body.get("book_id"), force=bool(body.get("rebuild")))
            stats = store.embedding_stats(result.get("model", ""))
        finally:
            store.close()
        self._send_json({"ok": True, **result, "stats": stats})

    def _api_retrieval(self, query: dict[str, list[str]]) -> None:
        text = (query.get("query") or [""])[0]
        limit = int((query.get("limit") or ["8"])[0])
        store = self._store()
        try:
            diagnostics = retrieval_diagnostics(store, text, limit=limit)
        finally:
            store.close()
        self._send_json({"ok": True, **diagnostics})

    def _api_graph(self, query: dict[str, list[str]]) -> None:
        node = (query.get("node") or [""])[0].strip()
        store = self._store()
        try:
            if node:
                edges = store.list_edges(src_id=node) + store.list_edges(dst_id=node)
                deduped = {edge["edge_id"]: edge for edge in edges}
                payload = list(deduped.values())
            else:
                payload = store.list_edges()
        finally:
            store.close()
        self._send_json({"ok": True, "edges": payload})

    def _api_judge_status(self) -> None:
        from .judge import judge_status

        self._send_json({"ok": True, **judge_status()})

    def _api_models(self) -> None:
        from .model_settings import model_overview

        self._send_json({"ok": True, **model_overview()})

    def _api_models_judge(self, body: dict[str, Any]) -> None:
        from .model_settings import judge_model_status, model_overview, set_judge_default

        result = set_judge_default(
            provider=str(body.get("provider", "ollama")),
            model=str(body.get("model", "")),
            base_url=str(body.get("base_url", "")),
        )
        self._send_json({"ok": True, **result, "overview": model_overview(), "status": judge_model_status()})

    def _api_models_hindsight(self, body: dict[str, Any]) -> None:
        from .model_settings import model_overview, set_hindsight_default

        result = set_hindsight_default(
            provider=str(body.get("provider", "ollama")),
            model=str(body.get("model", "")),
            base_url=str(body.get("base_url", "")),
        )
        self._send_json({"ok": True, **result, "overview": model_overview()})

    def _api_models_hermes(self, body: dict[str, Any]) -> None:
        from .model_settings import hermes_status, model_overview, set_hermes_default

        result = set_hermes_default(
            model=str(body.get("model", "")),
            provider=str(body.get("provider", "custom")),
            base_url=str(body.get("base_url", "")),
        )
        self._send_json({"ok": True, **result, "overview": model_overview(), "status": hermes_status()})

    def _api_models_preset(self, body: dict[str, Any]) -> None:
        from .model_settings import model_overview
        from .switch_models import apply_preset_data

        name = str(body.get("name", "cloud")).strip().lower()
        results = apply_preset_data(name)
        self._send_json(
            {
                "ok": not any(result.get("error") for _, result in results),
                "preset": name,
                "results": [{"target": label, **result} for label, result in results],
                "overview": model_overview(),
            }
        )

    def _api_judge(self, body: dict[str, Any]) -> None:
        from .judge import JudgeConfig, judge_analysis

        analysis_id = str(body.get("analysis_id", "")).strip()
        if not analysis_id:
            raise ValueError("analysis_id is required")
        store = self._store()
        try:
            result = judge_analysis(
                store,
                analysis_id,
                config=JudgeConfig(
                    provider=str(body.get("provider", "ollama")),
                    model=str(body.get("model", "qwen2.5:7b-instruct-q4_K_M")),
                    base_url=str(body.get("base_url", "http://127.0.0.1:11434")),
                ),
                dry_run=bool(body.get("dry_run", False)),
                allow_draft=bool(body.get("allow_draft", False)),
                note=str(body.get("note", "")),
            )
        finally:
            store.close()
        self._send_json({"ok": True, **result})

    def _api_graphrag_status(self) -> None:
        from .graph_rag import graph_status

        store = self._store()
        try:
            payload = graph_status(store)
        finally:
            store.close()
        self._send_json({"ok": True, **payload})

    def _api_graphrag_build(self, body: dict[str, Any]) -> None:
        from .graph_rag import build_graph

        store = self._store()
        try:
            payload = build_graph(store)
        finally:
            store.close()
        self._send_json({"ok": True, **payload})

    def _api_graphrag_query(self, query: dict[str, list[str]]) -> None:
        from .graph_rag import fused_search_report, query_graph

        text = (query.get("query") or [""])[0]
        if not text:
            raise ValueError("query is required")
        limit = int((query.get("limit") or ["8"])[0])
        mode = (query.get("mode") or ["hybrid"])[0]
        books = [item for item in (query.get("books") or []) if item]
        store = self._store()
        try:
            if mode == "graph":
                payload = query_graph(store, text, book_ids=books or None, limit=limit)
            else:
                payload = fused_search_report(store, text, book_ids=books or None, limit=limit)
        finally:
            store.close()
        self._send_json({"ok": True, **payload})

    def _api_graphrag_communities(self, query: dict[str, list[str]]) -> None:
        from .graph_rag import list_communities

        limit = int((query.get("limit") or ["30"])[0])
        store = self._store()
        try:
            payload = list_communities(store, limit=limit)
        finally:
            store.close()
        self._send_json({"ok": True, "communities": payload})

    def _api_obsidian_status(self, query: dict[str, list[str]]) -> None:
        from .obsidian_sync import obsidian_status

        vault = (query.get("vault") or [""])[0]
        store = self._store()
        try:
            payload = obsidian_status(store, vault=vault)
        finally:
            store.close()
        self._send_json({"ok": True, **payload})

    def _api_obsidian_notes(self, query: dict[str, list[str]]) -> None:
        from .obsidian_sync import list_reader_notes

        store = self._store()
        try:
            notes = list_reader_notes(
                store,
                query=(query.get("query") or [""])[0],
                status=(query.get("status") or ["active"])[0],
                limit=int((query.get("limit") or ["50"])[0]),
            )
        finally:
            store.close()
        self._send_json({"ok": True, "notes": notes})

    def _api_obsidian_reviews(self, query: dict[str, list[str]]) -> None:
        from .obsidian_sync import list_due_reviews

        store = self._store()
        try:
            due = list_due_reviews(store, limit=int((query.get("limit") or ["50"])[0]))
        finally:
            store.close()
        self._send_json({"ok": True, "due": due})

    def _api_obsidian_sync(self, body: dict[str, Any]) -> None:
        from .obsidian_sync import sync_obsidian

        vault = str(body.get("vault", "")).strip()
        store = self._store()
        try:
            payload = sync_obsidian(
                store,
                vault,
                subdir=str(body.get("subdir", "")),
                inbox=str(body.get("inbox", "")),
                direction=str(body.get("direction", "both")),
                preserve_edits=not bool(body.get("overwrite_user_edits", False)),
            )
        finally:
            store.close()
        self._send_json({"ok": True, **payload})

    def _api_obsidian_grade(self, body: dict[str, Any]) -> None:
        from .obsidian_sync import grade_review

        store = self._store()
        try:
            payload = grade_review(
                store,
                str(body.get("item_id", "")),
                int(body.get("grade", 0)),
                note=str(body.get("note", "")),
            )
        finally:
            store.close()
        self._send_json({"ok": True, **payload})

    def _api_hindsight_obsidian_status(self, query: dict[str, list[str]]) -> None:
        from .hindsight_obsidian import hindsight_obsidian_status

        vault = (query.get("vault") or [""])[0]
        self._send_json({"ok": True, **hindsight_obsidian_status(vault)})

    def _api_hindsight_obsidian_sync(self, body: dict[str, Any]) -> None:
        from .hindsight_obsidian import sync_memories

        payload = sync_memories(
            str(body.get("vault", "")).strip(),
            subdir=str(body.get("subdir", "")),
            inbox=str(body.get("inbox", "")),
            direction=str(body.get("direction", "both")),
        )
        self._send_json(payload)

    def _api_obsidian_sync_all(self, body: dict[str, Any]) -> None:
        from .hindsight_obsidian import sync_memories
        from .obsidian_sync import sync_obsidian

        vault = str(body.get("vault", "")).strip()
        store = self._store()
        try:
            book = sync_obsidian(
                store,
                vault,
                subdir=str(body.get("subdir", "")),
                inbox=str(body.get("inbox", "")),
                direction=str(body.get("direction", "both")),
                preserve_edits=not bool(body.get("overwrite_user_edits", False)),
            )
        finally:
            store.close()
        memories = sync_memories(
            vault,
            subdir=str(body.get("hindsight_subdir", "")),
            inbox=str(body.get("hindsight_inbox", "")),
            direction=str(body.get("direction", "both")),
        )
        self._send_json({"ok": bool(memories.get("ok")), "bookcompiler": book, "hindsight": memories})

    def _proposal(self, store: Store, body: dict[str, Any]):
        lenses = body.get("lenses") or ["economics", "politics", "law"]
        return build_proposal(
            store,
            mode=str(body.get("mode", "auto")),
            query=str(body.get("query", "")),
            lenses=lenses,
            book_ids=body.get("book_ids") or [],
            framework_ids=body.get("framework_ids") or [],
            direction=str(body.get("direction", "")),
        )

    def _api_plan(self, body: dict[str, Any]) -> None:
        store = self._store()
        try:
            proposal = self._proposal(store, body)
        finally:
            store.close()
        self._send_json({"ok": True, "proposal": proposal.to_dict()})

    def _api_analyze(self, body: dict[str, Any]) -> None:
        store = self._store()
        try:
            proposal = self._proposal(store, body)
            choice = str(body.get("choice", "") or "")
            if proposal.requires_confirmation and not choice:
                self._send_json(
                    {
                        "ok": False,
                        "error": "confirmation_required",
                        "message": "This mode requires an explicit consent choice.",
                        "proposal": proposal.to_dict(),
                    },
                    409,
                )
                return
            if proposal.requires_confirmation and choice not in proposal.options:
                raise ValueError(f"choice must be one of: {', '.join(proposal.options)}")
            packet = create_analysis(
                store,
                str(body.get("query", "")),
                body.get("lenses") or ["economics", "politics", "law"],
                proposal,
                choice or "specified+recommended",
            )
            titles = {book["book_id"]: book["title"] for book in store.list_books()}
        finally:
            store.close()
        self._send_json({"ok": True, "analysis": packet.to_dict(), "proposal": proposal.to_dict(), "book_titles": titles})

    def _api_analysis_patch(self, body: dict[str, Any]) -> None:
        analysis_id = str(body.get("analysis_id", "")).strip()
        patch = body.get("patch")
        if not analysis_id:
            raise ValueError("analysis_id is required")
        if not isinstance(patch, dict):
            raise ValueError("patch must be a JSON object")
        store = self._store()
        try:
            packet = apply_analysis_patch(store, analysis_id, patch)
            titles = {book["book_id"]: book["title"] for book in store.list_books()}
        finally:
            store.close()
        self._send_json({"ok": True, "analysis": packet.to_dict(), "book_titles": titles})

    def _api_feedback(self, body: dict[str, Any]) -> None:
        analysis_id = str(body.get("analysis_id", "")).strip()
        rating = int(body.get("rating", 0))
        if not analysis_id:
            raise ValueError("analysis_id is required")
        if rating < 1 or rating > 5:
            raise ValueError("rating must be between 1 and 5")
        store = self._store()
        try:
            if not store.get_analysis(analysis_id):
                raise ValueError(f"unknown analysis_id: {analysis_id}")
            feedback_id = store.add_feedback(
                analysis_id,
                rating,
                str(body.get("note", "")),
                error_labels=body.get("error_labels") or [],
                preferred_book_ids=body.get("preferred_book_ids") or [],
                preferred_framework_ids=body.get("preferred_framework_ids") or [],
                missing_evidence=str(body.get("missing_evidence", "")),
                outcome=str(body.get("outcome", "")),
            )
        finally:
            store.close()
        self._send_json({"ok": True, "feedback_id": feedback_id})

    def _api_evolution_propose(self, body: dict[str, Any]) -> None:
        store = self._store()
        try:
            proposals = propose_evolutions(store, min_support=int(body.get("min_support", 1)))
        finally:
            store.close()
        self._send_json({"ok": True, "proposals": proposals})

    def _api_evolution_decide(self, body: dict[str, Any]) -> None:
        proposal_id = str(body.get("proposal_id", "")).strip()
        status = str(body.get("status", "")).strip()
        if not proposal_id or not status:
            raise ValueError("proposal_id and status are required")
        report = body.get("replay_report")
        if report is None and body.get("replay_report_path"):
            report = json.loads(Path(body["replay_report_path"]).read_text(encoding="utf-8"))
        store = self._store()
        try:
            proposal = decide_evolution(store, proposal_id, status, str(body.get("note", "")), report)
        finally:
            store.close()
        self._send_json({"ok": True, "proposal": proposal})

    def _api_replay(self, body: dict[str, Any]) -> None:
        cases = body.get("cases")
        if cases is None and body.get("analysis_ids"):
            cases = []
            store = self._store()
            try:
                for analysis_id in body["analysis_ids"]:
                    packet = store.get_analysis(str(analysis_id))
                    if not packet:
                        continue
                    selection = packet.get("selection", {})
                    cases.append(
                        {
                            "case_id": str(analysis_id),
                            "query": packet.get("question", ""),
                            "lenses": packet.get("lenses", ["economics", "politics", "law"]),
                            "mode": packet.get("mode", "auto"),
                            "choice": selection.get("choice", "specified+recommended"),
                            "book_ids": [book.get("book_id") for book in selection.get("books", [])],
                            "framework_ids": [fw.get("framework_id") for fw in selection.get("frameworks", [])],
                        }
                    )
            finally:
                store.close()
        if not isinstance(cases, list) or not cases:
            raise ValueError("cases or analysis_ids are required")
        store = self._store()
        try:
            report = replay_cases(store, cases)
        finally:
            store.close()
        self._send_json({"ok": True, "report": report})

    def _api_ingest(self, body: dict[str, Any]) -> None:
        raw_path = str(body.get("path", "")).strip()
        if not raw_path:
            raise ValueError("path is required")
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"file not found: {path}")
        if path.suffix.lower() not in {".txt", ".md", ".markdown", ".pdf", ".epub"}:
            raise ValueError("supported formats: .txt, .md, .markdown, .pdf, .epub")
        parsed = parse_book(
            path,
            title=body.get("title") or None,
            author=str(body.get("author") or "Unknown"),
            disciplines=body.get("disciplines") or [],
        )
        store = self._store()
        try:
            store.add_book(parsed)
        finally:
            store.close()
        self._send_json(
            {
                "ok": True,
                "book_id": parsed.book_id,
                "title": parsed.title,
                "chapters": len(parsed.chapters),
                "chunks": len(parsed.chunks),
            }
        )

    def _api_compile(self, body: dict[str, Any]) -> None:
        book_id = str(body.get("book_id", "")).strip()
        if not book_id:
            raise ValueError("book_id is required")
        patch = body.get("patch")
        if patch is not None and not isinstance(patch, dict):
            raise ValueError("patch must be a JSON object")
        store = self._store()
        try:
            result = compile_book(store, book_id, patch=patch)
        finally:
            store.close()
        self._send_json({"ok": not any(issue.severity == "error" for issue in result.issues), "result": result.to_dict()})


def make_server(db_path: str | Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    db_path = Path(db_path).expanduser().resolve()
    Store(db_path).close()  # initialize the schema before serving

    class BoundHandler(GuiHandler):
        pass

    BoundHandler.db_path = db_path
    server = ThreadingHTTPServer((host, port), BoundHandler)
    server.daemon_threads = True
    return server


def run_gui(db_path: str | Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = False) -> None:
    candidates = [0] if port == 0 else list(range(port, port + 6))
    server = None
    for candidate in candidates:
        try:
            server = make_server(db_path, host, candidate)
            break
        except OSError as exc:
            if candidate == candidates[-1]:
                raise
            print(f"port {candidate} is busy ({exc}); trying {candidate + 1}...")
    assert server is not None
    actual_host, actual_port = server.server_address[:2]
    url = f"http://{actual_host}:{actual_port}/"
    print(f"bookcompiler GUI: {url}")
    print(f"database: {Path(db_path).expanduser().resolve()}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Thread(target=lambda: (time.sleep(0.8), webbrowser.open(url)), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run_gui("library.db")
