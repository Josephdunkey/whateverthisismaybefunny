from pathlib import Path

from bookcompiler.analysis import create_analysis
from tests.helpers import compile_verified
from bookcompiler.modes import build_proposal
from bookcompiler.parsing import parse_book
from bookcompiler.render import render_memo
from bookcompiler.store import Store


def test_analysis_packet_contains_lenses_frameworks_and_citations(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    proposal = build_proposal(store, "auto", "Central bank cuts reserve requirements", ["economics", "politics", "law"])
    packet = create_analysis(store, "Central bank cuts reserve requirements", ["economics", "politics", "law"], proposal, "auto")

    assert packet.question == "Central bank cuts reserve requirements"
    assert packet.lenses == ["economics", "politics", "law"]
    assert packet.frameworks
    assert packet.citations
    assert packet.status == "draft"
    memo = render_memo(packet.to_dict())
    assert "Central bank cuts reserve requirements" in memo
    assert "Framework" in memo
    assert "Draft" in memo
import pytest

from bookcompiler.analysis import AnalysisValidationError, apply_analysis_patch


def _draft(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    proposal = build_proposal(store, "auto", "Central bank cuts reserve requirements", ["economics", "politics", "law"])
    packet = create_analysis(store, "Central bank cuts reserve requirements", ["economics", "politics", "law"], proposal, "auto")
    return store, packet


def _complete_patch(packet):
    citation = packet.citations[0]
    return {
        "hypotheses": [
            {
                "lens": "economics",
                "claim": "A reserve cut lowers funding costs and may support credit.",
                "framework_id": packet.frameworks[0]["framework_id"],
                "supporting_evidence": [citation],
                "confidence": "medium",
            }
        ],
        "counterevidence": [
            {
                "description": "Banks may not pass the liquidity through to households.",
                "citation": packet.citations[1],
            }
        ],
        "cross_lens_conflicts": [
            {
                "lenses": ["economics", "law"],
                "description": "Economic desirability does not establish legal authority.",
                "resolution": "Treat legal authority as a separate gate.",
            }
        ],
        "conclusion": "The policy is conditionally expansionary if legal authority and transmission both hold.",
        "uncertainty": "The conclusion weakens if banks hoard liquidity or courts stay the measure.",
        "next_checks": ["Check reserve balances.", "Check the statutory delegation."],
        "citations": packet.citations,
        "jurisdiction": "Example jurisdiction",
        "not_legal_advice": True,
        "status": "complete",
    }


def test_analysis_apply_accepts_complete_patch_and_keeps_citations(tmp_path):
    store, packet = _draft(tmp_path)

    applied = apply_analysis_patch(store, packet.analysis_id, _complete_patch(packet))

    assert applied.status == "complete"
    assert applied.conclusion
    assert applied.not_legal_advice is True
    stored = store.get_analysis(packet.analysis_id)
    assert stored["status"] == "complete"
    assert store.list_edges(src_id=packet.analysis_id)


def test_analysis_apply_rejects_missing_legal_disclaimer(tmp_path):
    store, packet = _draft(tmp_path)
    patch = _complete_patch(packet)
    patch["not_legal_advice"] = False

    with pytest.raises(AnalysisValidationError) as exc:
        apply_analysis_patch(store, packet.analysis_id, patch)

    assert any(issue.code == "legal_disclaimer_missing" for issue in exc.value.issues)
    assert store.get_analysis(packet.analysis_id)["status"] == "draft"


def test_analysis_apply_rejects_fabricated_citation(tmp_path):
    store, packet = _draft(tmp_path)
    patch = _complete_patch(packet)
    patch["citations"] = [{
        "book_id": packet.citations[0]["book_id"],
        "quote": "This quotation does not exist in the source book.",
        "chapter": "Fake chapter",
        "page": None,
    }]

    with pytest.raises(AnalysisValidationError) as exc:
        apply_analysis_patch(store, packet.analysis_id, patch)

    assert any(issue.code == "unsupported_quote" for issue in exc.value.issues)