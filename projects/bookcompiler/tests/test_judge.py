from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bookcompiler.analysis import create_analysis
from bookcompiler.judge import JudgeError, judge_analysis
from bookcompiler.modes import build_proposal
from bookcompiler.parsing import parse_book
from bookcompiler.reading_eval import reading_report
from bookcompiler.store import Store
from tests.helpers import compile_verified


class FakeJudge:
    provider = "fake"
    model = "fake-judge-1"
    config = SimpleNamespace(base_url="http://fake")

    def __init__(self, response: str):
        self.response = response

    def chat(self, prompt: str) -> str:
        assert "auto_proxy" not in prompt
        return self.response


def _packet(tmp_path, complete: bool = True):
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
    if complete:
        packet.status = "complete"
        packet.conclusion = "Conditional conclusion with explicit uncertainty."
        store.save_analysis(packet)
    return store, packet


def _payload():
    return {
        "scores": {
            "source_fidelity": 8.0,
            "retrieval_coverage": 7.0,
            "framework_fit": 6.5,
            "cross_book_synthesis": 5.0,
            "cross_lens_integration": 6.0,
            "conflict_handling": 4.0,
            "calibration": 7.0,
            "actionability": 6.0,
            "failure_mode_awareness": 5.5,
        },
        "error_labels": ["conflict_suppression"],
        "note": "Usable but conflict handling is weak.",
        "strongest_part": "citation fidelity",
        "weakest_part": "conflict handling",
    }


def test_real_judge_persists_independent_scores_and_report_prefers_them(tmp_path):
    store, packet = _packet(tmp_path)
    result = judge_analysis(store, packet.analysis_id, judge=FakeJudge(json.dumps(_payload())))
    assert result["evaluator"] == "llm_judge:fake-judge-1"
    assert result["metadata"]["blind"] is True
    assert result["metadata"]["proxy_scores_hidden"] is True
    assert 0.0 < result["total"] < 100.0
    report = reading_report(store)
    assert report["basis"] == "independent"
    assert report["independent_count"] == 1
    assert report["evaluator_breakdown"]["llm_judge"]["count"] == 1
    assert report["proxy_calibration"]


def test_judge_rejects_draft_and_invalid_json_without_writing(tmp_path):
    store, packet = _packet(tmp_path, complete=False)
    with pytest.raises(JudgeError):
        judge_analysis(store, packet.analysis_id, judge=FakeJudge(json.dumps(_payload())))
    assert store.list_reading_evaluations(analysis_id=packet.analysis_id) == []

    packet.status = "complete"
    store.save_analysis(packet)
    with pytest.raises(Exception):
        judge_analysis(store, packet.analysis_id, judge=FakeJudge("not a json object"))
    assert store.list_reading_evaluations(analysis_id=packet.analysis_id) == []


def test_judge_missing_dimension_is_rejected(tmp_path):
    store, packet = _packet(tmp_path)
    payload = _payload()
    payload["scores"].pop("conflict_handling")
    with pytest.raises(Exception):
        judge_analysis(store, packet.analysis_id, judge=FakeJudge(json.dumps(payload)))
    assert store.list_reading_evaluations(analysis_id=packet.analysis_id) == []