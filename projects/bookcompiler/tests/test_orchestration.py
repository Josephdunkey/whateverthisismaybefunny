from __future__ import annotations

from pathlib import Path

from bookcompiler.analysis import apply_analysis_patch, create_analysis
from bookcompiler.modes import build_proposal
from bookcompiler.parsing import parse_book
from bookcompiler.store import Store
from tests.helpers import compile_verified


def test_create_analysis_runs_automatic_role_pipeline(tmp_path):
    parsed = parse_book(
        Path("examples/sample_book.md"),
        title="Policy Shocks",
        author="Tester",
        disciplines=["economics", "politics", "law"],
    )
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    proposal = build_proposal(store, "auto", "Central bank cuts reserve requirements", ["economics", "politics", "law"])
    packet = create_analysis(
        store,
        "Central bank cuts reserve requirements",
        ["economics", "politics", "law"],
        proposal,
        "auto",
    )
    orchestration = packet.orchestration
    assert orchestration["execution"] == "automatic"
    assert orchestration["agent_count"] == 10
    roles = {stage["role"] for stage in orchestration["stages"]}
    assert {"planner", "retriever", "reader", "red_team", "citation_auditor", "lens_reviewer", "synthesizer", "judge", "evolver"} <= roles
    assert orchestration["lens_coverage"]
    assert packet.retrieval["channels"]
    assert packet.retrieval["graph"]["available"] is True

    patch = {
        "conclusion": "Conditional conclusion.",
        "uncertainty": "Fails if transmission is blocked.",
        "citations": packet.citations,
        "status": "complete",
    }
    updated = apply_analysis_patch(store, packet.analysis_id, patch)
    stages = {stage["role"]: stage for stage in updated.orchestration["stages"]}
    assert stages["synthesizer"]["status"] == "complete"
    assert stages["citation_auditor"]["status"] == "pass"