from pathlib import Path

import pytest

from bookcompiler.analysis import apply_analysis_patch, create_analysis
from bookcompiler.compiler import compile_book
from tests.helpers import compile_verified
from bookcompiler.evolution import decide_evolution, propose_evolutions
from bookcompiler.models import SelectionProposal
from bookcompiler.modes import build_proposal
from bookcompiler.parsing import parse_book
from bookcompiler.store import Store
from bookcompiler.validation import find_quote, validate_analysis_packet


def test_long_chinese_text_is_chunked_at_sentence_boundaries(tmp_path):
    path = tmp_path / "中文书.txt"
    sentence = "中央银行通过公开市场操作改变基础货币，并经由银行体系影响信贷供给。"
    path.write_text(sentence * 300, encoding="utf-8")

    parsed = parse_book(path, title="中文书", author="Tester", disciplines=["economics"])

    assert len(parsed.chunks) > 1
    assert max(len(chunk.text) for chunk in parsed.chunks) <= 1800
    for chunk in parsed.chunks:
        assert chunk.text.rstrip().endswith(("。", "！", "？"))


def test_analysis_rejects_wrong_chunk_and_chapter_provenance(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester")
    chunk = find_quote("A regulator must act within statutory authority.", parsed.chunks)
    assert chunk is not None

    packet = {
        "lenses": ["law", "economics"],
        "status": "draft",
        "citations": [
            {
                "book_id": parsed.book_id,
                "quote": "A regulator must act within statutory authority.",
                "chunk_id": "wrong-chunk",
                "chapter": "Wrong chapter",
            }
        ],
    }
    issues = validate_analysis_packet(packet, {parsed.book_id: parsed.chunks})
    codes = {issue.code for issue in issues if issue.severity == "error"}
    assert "citation_chunk_mismatch" in codes
    assert "citation_chapter_mismatch" in codes


def test_reproposing_evolution_preserves_promotion_evidence(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    proposal = build_proposal(store, "auto", "Central bank cuts reserve requirements", ["economics", "politics", "law"])
    packet = create_analysis(store, "Central bank cuts reserve requirements", ["economics", "politics", "law"], proposal, "auto")
    store.add_feedback(packet.analysis_id, 2, "Needs another pass.", error_labels=["overconfidence"])

    item = propose_evolutions(store)[0]
    proposal_id = item["proposal_id"]
    decide_evolution(store, proposal_id, "accepted")
    decide_evolution(store, proposal_id, "shadow")
    report = {
        "case_count": 1,
        "structural_pass_count": 1,
        "cases": [{"case_id": "case-1", "structural_pass": True, "issues": []}],
    }
    decide_evolution(store, proposal_id, "promoted", "clean replay", report)

    propose_evolutions(store)

    saved = store.get_evolution_proposal(proposal_id)
    assert saved["status"] == "promoted"
    assert saved["promotion_evidence"]["gate"] == "passed"


def test_reingest_preserves_compiled_artifacts_when_text_is_unchanged(tmp_path):
    source = tmp_path / "book.md"
    source.write_text(Path("examples/sample_book.md").read_text(encoding="utf-8"), encoding="utf-8")
    parsed = parse_book(source, title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    patch = {
        "book_card": {
            "book_id": parsed.book_id,
            "title": parsed.title,
            "author": parsed.author,
            "one_line_thesis": "Policy shocks change prices, coalitions, and legal authority.",
            "core_questions": ["Who bears the cost?"],
            "key_concepts": ["incentives"],
            "assumptions": ["Institutions respond to incentives."],
            "limitations": ["Sample only."],
            "best_for": ["policy analysis"],
            "not_for": ["forecasting"],
            "chapter_coverage": [
                {
                    "chapter": parsed.chunks[0].chapter_title,
                    "summary": "A cited summary.",
                    "citation": {
                        "book_id": parsed.book_id,
                        "quote": parsed.chunks[0].text[:60],
                        "chunk_id": parsed.chunks[0].chunk_id,
                        "chapter": parsed.chunks[0].chapter_title,
                    },
                }
            ],
            "lenses": ["economics", "politics", "law"],
            "confidence": "high",
            "status": "verified",
        },
        "frameworks": [
            {
                "framework_id": "fw-1",
                "book_id": parsed.book_id,
                "name": "Incentive transmission",
                "one_liner": "Trace how a policy changes relative prices and incentives.",
                "lenses": ["economics"],
                "applicable_when": ["A policy changes costs or credit conditions."],
                "inputs": ["The policy change"],
                "steps": ["Identify the price change", "Trace the response"],
                "outputs": ["A transmission path"],
                "failure_modes": ["Fails when prices are administratively fixed."],
                "counterexamples": [],
                "citations": [
                    {
                        "book_id": parsed.book_id,
                        "quote": parsed.chunks[0].text[:60],
                        "chunk_id": parsed.chunks[0].chunk_id,
                        "chapter": parsed.chunks[0].chapter_title,
                    }
                ],
                "related_frameworks": [],
                "confidence": "high",
                "status": "verified",
            }
        ],
    }
    result = compile_book(store, parsed.book_id, patch=patch)
    assert not [issue for issue in result.issues if issue.severity == "error"]
    assert store.get_book_card(parsed.book_id) is not None
    assert store.list_frameworks(book_ids=[parsed.book_id])
    assert store.get_book(parsed.book_id)["status"] == "compiled"

    store.add_book(parsed)
    assert store.get_book_card(parsed.book_id) is not None
    assert store.list_frameworks(book_ids=[parsed.book_id])

    source.write_text(source.read_text(encoding="utf-8") + "\n\n## Chapter 9: New\n\nA changed paragraph with new evidence text.\n", encoding="utf-8")
    changed = parse_book(source, title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store.add_book(changed)
    assert store.get_book_card(parsed.book_id) is None
    assert store.list_frameworks(book_ids=[parsed.book_id]) == []
    assert store.get_book(parsed.book_id)["status"] == "ingested"


def test_analysis_rejects_wrong_page_provenance(tmp_path):
    source = tmp_path / "paged.txt"
    source.write_text(
        "≦ 12 ≧\nA regulator must act within statutory authority.\n≦ 13 ≧\nA second page of text for the source.\n≦ 14 ≧\nA third page of text for the source.\n",
        encoding="utf-8",
    )
    parsed = parse_book(source, title="Paged Policy", author="Tester")
    chunk = find_quote("A regulator must act within statutory authority.", parsed.chunks)
    assert chunk is not None
    packet = {
        "lenses": ["law", "economics"],
        "status": "draft",
        "citations": [
            {
                "book_id": parsed.book_id,
                "quote": "A regulator must act within statutory authority.",
                "chunk_id": chunk.chunk_id,
                "chapter": chunk.chapter_title,
                "page": 9999,
            }
        ],
    }
    issues = validate_analysis_packet(packet, {parsed.book_id: parsed.chunks})
    codes = {issue.code for issue in issues if issue.severity == "error"}
    assert "citation_page_mismatch" in codes


def test_metadata_change_invalidates_compiled_artifacts_but_keeps_chunks(tmp_path):
    source = tmp_path / "book.md"
    source.write_text(Path("examples/sample_book.md").read_text(encoding="utf-8"), encoding="utf-8")
    parsed = parse_book(source, title="Policy Shocks", author="Tester", disciplines=["economics"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    compile_book(store, parsed.book_id)
    assert store.get_book_card(parsed.book_id) is not None
    assert store.list_frameworks(book_ids=[parsed.book_id])

    changed = parse_book(source, title="Policy Shocks", author="Tester", disciplines=["politics", "law"])
    store.add_book(changed)
    assert store.get_book_card(parsed.book_id) is None
    assert store.list_frameworks(book_ids=[parsed.book_id]) == []
    assert store.get_chunks(parsed.book_id)
    assert store.get_book(parsed.book_id)["status"] == "ingested"


def test_create_analysis_refuses_empty_consented_selection(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester")
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    proposal = SelectionProposal(
        mode="direction",
        query="bank lending",
        lenses=["economics", "law"],
        direction="bank credit",
        specified_books=[],
        specified_frameworks=[],
        recommended_books=[],
        recommended_frameworks=[],
        coverage_gaps=[],
        requires_confirmation=True,
        options=["specified", "specified+recommended", "recommended"],
        rationale="test",
    )
    with pytest.raises(ValueError, match="empty"):
        create_analysis(store, "bank lending", ["economics", "law"], proposal, "specified")


def test_analysis_patch_rejects_unknown_status(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester")
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    proposal = build_proposal(store, "auto", "bank lending", ["economics", "law"])
    packet = create_analysis(store, "bank lending", ["economics", "law"], proposal, "auto")
    with pytest.raises(ValueError, match="status"):
        apply_analysis_patch(store, packet.analysis_id, {"status": "verified"})


def test_analysis_rejects_non_integer_page(tmp_path):
    source = tmp_path / "paged-invalid.txt"
    source.write_text(
        "≦ 12 ≧\nA regulator must act within statutory authority.\n≦ 13 ≧\nA second page of text for the source.\n≦ 14 ≧\nA third page of text for the source.\n",
        encoding="utf-8",
    )
    parsed = parse_book(source, title="Paged Policy", author="Tester")
    chunk = find_quote("A regulator must act within statutory authority.", parsed.chunks)
    assert chunk is not None
    packet = {
        "lenses": ["law", "economics"],
        "status": "draft",
        "citations": [
            {
                "book_id": parsed.book_id,
                "quote": "A regulator must act within statutory authority.",
                "chunk_id": chunk.chunk_id,
                "chapter": chunk.chapter_title,
                "page": "not-a-page",
            }
        ],
    }
    issues = validate_analysis_packet(packet, {parsed.book_id: parsed.chunks})
    assert any(issue.code == "invalid_citation_page" for issue in issues)
