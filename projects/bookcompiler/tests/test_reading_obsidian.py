from __future__ import annotations

from pathlib import Path

from bookcompiler.analysis import create_analysis
from bookcompiler.evolution import propose_evolutions
from bookcompiler.mcp import BookCompilerMCP
from bookcompiler.modes import build_proposal
from bookcompiler.obsidian import export_vault
from bookcompiler.parsing import parse_book
from bookcompiler.reading_eval import READING_DIMENSIONS, evaluate_reading, reading_report
from bookcompiler.store import Store

from tests.helpers import compile_verified


def _learned_store(tmp_path: Path) -> tuple[Store, str]:
    store = Store(tmp_path / "library.db")
    parsed = parse_book(
        Path("examples/sample_book.md"),
        title="Policy Shocks",
        author="Tester",
        disciplines=["economics", "politics", "law"],
    )
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    return store, parsed.book_id


def _draft_packet(store: Store, book_id: str):
    proposal = build_proposal(
        store,
        mode="auto",
        query="A central bank cuts reserve requirements during a fiscal expansion.",
        lenses=["economics", "politics", "law"],
        book_ids=[book_id],
    )
    return create_analysis(
        store,
        "A central bank cuts reserve requirements during a fiscal expansion.",
        ["economics", "politics", "law"],
        proposal,
        "auto",
    )


def test_reading_eval_scores_nine_dimensions_and_persists(tmp_path):
    store, book_id = _learned_store(tmp_path)
    packet = _draft_packet(store, book_id)

    evaluation = evaluate_reading(store, packet.analysis_id)

    assert set(evaluation["scores"]) == {item["key"] for item in READING_DIMENSIONS}
    assert all(item["label"] and "?" not in item["label"] for item in READING_DIMENSIONS)
    assert 0 <= evaluation["total"] <= 100
    assert evaluation["evaluator"] == "auto_proxy"
    stored = store.list_reading_evaluations(analysis_id=packet.analysis_id)
    assert len(stored) == 1
    assert stored[0]["evaluation_id"] == evaluation["evaluation_id"]


def test_reading_eval_accepts_human_overrides_and_reports_low_dimensions(tmp_path):
    store, book_id = _learned_store(tmp_path)
    packet = _draft_packet(store, book_id)

    evaluation = evaluate_reading(
        store,
        packet.analysis_id,
        scores={"source_fidelity": 9, "retrieval_coverage": 2, "cross_book_synthesis": 1},
        evaluator="human",
        note="only one book was genuinely used",
        error_labels=["retrieval_miss"],
    )

    assert evaluation["scores"]["source_fidelity"] == 9
    assert evaluation["scores"]["retrieval_coverage"] == 2
    assert evaluation["evaluator"] == "human"
    report = reading_report(store)
    assert report["count"] == 1
    assert report["error_label_counts"]["retrieval_miss"] == 1
    low_keys = {item["key"] for item in report["low_dimensions"]}
    assert "cross_book_synthesis" in low_keys
    assert any(item["key"] == "cross_book_synthesis" for item in report["next_actions"])


def test_reading_eval_creates_advisory_evolution_proposal(tmp_path):
    store, book_id = _learned_store(tmp_path)
    packet = _draft_packet(store, book_id)
    evaluate_reading(
        store,
        packet.analysis_id,
        scores={"source_fidelity": 2, "retrieval_coverage": 2},
        evaluator="human",
        note="weak source use",
    )

    proposals = propose_evolutions(store, min_support=1)
    reading = [item for item in proposals if item.get("source") == "reading_eval"]

    assert reading
    assert any(item["change"]["kind"] == "review_reading_dimension" for item in reading)
    assert all(item["evidence_evaluation_ids"] for item in reading)


def test_obsidian_export_writes_links_and_manifest(tmp_path):
    store, book_id = _learned_store(tmp_path)
    vault = tmp_path / "vault"

    manifest = export_vault(store, vault)

    root = vault / "BookCompiler"
    assert (root / "BookCompiler MOC.md").exists()
    assert list((root / "Books").glob("*.md"))
    assert list((root / "Frameworks").glob("*.md"))
    assert (root / ".bookcompiler-export.json").exists()
    book_note = next((root / "Books").glob("*.md")).read_text(encoding="utf-8")
    assert "bookcompiler/book" in book_note
    assert "[[BookCompiler MOC]]" in book_note
    assert manifest["counts"]["books"] == 1


def test_mcp_reading_eval_tool_scores_an_analysis(tmp_path):
    store, book_id = _learned_store(tmp_path)
    packet = _draft_packet(store, book_id)
    db_path = store.db_path if hasattr(store, "db_path") else str(tmp_path / "library.db")
    store.close()

    mcp = BookCompilerMCP(db_path)
    payload = mcp.call_tool("book_reading_eval", {"action": "score", "analysis_id": packet.analysis_id})

    assert payload["analysis_id"] == packet.analysis_id
    assert 0 <= payload["total"] <= 100


def test_obsidian_export_preserves_manual_edits(tmp_path):
    store, book_id = _learned_store(tmp_path)
    vault = tmp_path / "vault"
    export_vault(store, vault)
    note = next((vault / "BookCompiler" / "Books").glob("*.md"))
    original = note.read_text(encoding="utf-8")
    note.write_text(original + "\n\nMy manual correction.\n", encoding="utf-8")

    manifest = export_vault(store, vault)

    assert manifest["preserved_user_edits"]
    assert "My manual correction." in note.read_text(encoding="utf-8")
    assert list(note.parent.glob("*.generated.md"))
