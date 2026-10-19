from pathlib import Path

from bookcompiler.analysis import create_analysis
from tests.helpers import compile_verified
from bookcompiler.evolution import decide_evolution, propose_evolutions, recall_memory, replay_cases
from bookcompiler.modes import build_proposal
from bookcompiler.parsing import parse_book
from bookcompiler.store import Store


def _setup(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    proposal = build_proposal(store, "auto", "Central bank cuts reserve requirements", ["economics", "politics", "law"])
    packet = create_analysis(store, "Central bank cuts reserve requirements", ["economics", "politics", "law"], proposal, "auto")
    return store, parsed, packet


def test_structured_feedback_drives_memory_and_evolution_proposals(tmp_path):
    store, parsed, packet = _setup(tmp_path)
    framework_id = packet.frameworks[0]["framework_id"]

    store.add_feedback(
        packet.analysis_id,
        2,
        "The legal lens was not explicit enough.",
        error_labels=["lens_omission", "overconfidence"],
        preferred_book_ids=[parsed.book_id],
        preferred_framework_ids=[framework_id],
        missing_evidence="A source on statutory delegation.",
        outcome="User asked for a revision.",
    )

    weights = store.preference_weights()
    assert weights["books"][parsed.book_id] == 1.0
    assert weights["frameworks"][framework_id] == 1.0

    lessons = recall_memory(store, "reserve requirements and legal authority", ["economics", "politics", "law"])
    assert lessons
    assert lessons[0]["source"] == "feedback"

    proposals = propose_evolutions(store)
    targets = {proposal["target"] for proposal in proposals}
    assert "lens_coverage" in targets
    assert "retrieval" in targets
    assert store.list_evolution_proposals()

    accepted = decide_evolution(store, proposals[0]["proposal_id"], "accepted", "Run replay first.")
    assert accepted["status"] == "accepted"


def test_replay_reports_structural_health(tmp_path):
    store, parsed, _ = _setup(tmp_path)

    report = replay_cases(
        store,
        [
            {
                "case_id": "case-1",
                "query": "Bank lending regulation",
                "lenses": ["economics", "politics", "law"],
                "mode": "auto",
                "expected_book_ids": [parsed.book_id],
            }
        ],
    )

    assert report["case_count"] == 1
    assert report["structural_pass_count"] == 1
    assert report["cases"][0]["citation_count"] > 0
    assert report["cases"][0]["book_hit_rate"] == 1.0

def test_promotion_requires_shadow_state_and_clean_replay(tmp_path):
    store, _, packet = _setup(tmp_path)
    store.add_feedback(packet.analysis_id, 2, "Needs another pass.", error_labels=["overconfidence"])
    proposal = propose_evolutions(store)[0]
    proposal_id = proposal["proposal_id"]

    try:
        decide_evolution(store, proposal_id, "promoted", "skip the gate")
        raise AssertionError("promotion from proposed should fail")
    except ValueError as exc:
        assert "illegal transition" in str(exc)

    decide_evolution(store, proposal_id, "accepted", "gate accepted")
    decide_evolution(store, proposal_id, "shadow", "run in shadow")

    try:
        decide_evolution(store, proposal_id, "promoted", "no report")
        raise AssertionError("promotion without replay should fail")
    except ValueError as exc:
        assert "replay report" in str(exc)

    report = {
        "generated_at": "2026-01-01T00:00:00Z",
        "case_count": 1,
        "structural_pass_count": 1,
        "cases": [{"case_id": "case-1", "structural_pass": True, "issues": []}],
    }
    promoted = decide_evolution(store, proposal_id, "promoted", "clean replay", report)
    assert promoted["status"] == "promoted"
    assert promoted["promotion_evidence"]["gate"] == "passed"

    rolled_back = decide_evolution(store, proposal_id, "rolled_back", "regression in production")
    assert rolled_back["status"] == "rolled_back"

