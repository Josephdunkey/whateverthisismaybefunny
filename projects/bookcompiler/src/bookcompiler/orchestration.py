"""Automatic multi-role orchestration for one reading analysis.

This module implements a *deterministic role pipeline*, not a free-form chat
between several LLMs.  Each role has an explicit input/output contract and the
trace is stored in ``AnalysisPacket.orchestration`` so a user can audit which
role produced which observation.  Only the independent judge is a separate
model call, and it is never simulated here.
"""

from __future__ import annotations

from typing import Any

from .judge import _citation_audit
from .reading_eval import evaluator_kind
from .store import Store

ROLE_ORDER = [
    "planner",
    "retriever",
    "reader",
    "feynman_explainer",
    "red_team",
    "citation_auditor",
    "lens_reviewer",
    "synthesizer",
    "judge",
    "evolver",
]


def _stage(role: str, status: str, summary: str, outputs: Any = None, inputs: Any = None) -> dict[str, Any]:
    return {
        "role": role,
        "status": status,
        "summary": summary,
        "inputs": inputs or {},
        "outputs": outputs or {},
    }


def _planner(packet: dict[str, Any]) -> dict[str, Any]:
    question = str(packet.get("question", "")).strip()
    lenses = [str(item) for item in packet.get("lenses", []) if str(item)]
    sub_questions = []
    for lens in lenses:
        sub_questions.append(f"From the {lens} lens, what is the causal mechanism at work?")
        sub_questions.append(f"From the {lens} lens, what evidence would falsify the leading explanation?")
    if not sub_questions:
        sub_questions = ["What is the central claim?", "What evidence would change the answer?"]
    if "?" in question or "？" in question:
        sub_questions.insert(0, question)
    return {
        "sub_questions": sub_questions[:10],
        "lenses": lenses,
        "evidence_needed": [
            "book-grounded mechanism, not a generic prior",
            "at least one concrete citation per active lens",
            "strongest counterexample and its conditions",
        ],
        "question": question,
    }


def _lens_coverage(store: Store, packet: dict[str, Any]) -> dict[str, Any]:
    lenses = [str(item) for item in packet.get("lenses", []) if str(item)]
    frameworks = packet.get("frameworks", []) or []
    citations = [item for item in packet.get("citations", []) if isinstance(item, dict)]
    claims = [item for item in packet.get("claims", []) if isinstance(item, dict)]
    coverage: dict[str, Any] = {}
    for lens in lenses:
        lens_frameworks = [fw for fw in frameworks if lens in (fw.get("lenses") or [])]
        framework_ids = {fw.get("framework_id", "") for fw in lens_frameworks}
        lens_claims = [claim for claim in claims if claim.get("book_id") in {fw.get("book_id") for fw in lens_frameworks}]
        lens_citations = [item for item in citations if item.get("book_id") in {fw.get("book_id") for fw in lens_frameworks}]
        coverage[lens] = {
            "frameworks": [fw.get("name", "") for fw in lens_frameworks][:6],
            "framework_ids": sorted(item for item in framework_ids if item),
            "claim_count": len(lens_claims),
            "citation_count": len(lens_citations),
            "status": "covered" if lens_frameworks and lens_citations else ("thin" if lens_frameworks else "missing"),
        }
    return coverage


def _red_team(packet: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    attacks: list[dict[str, Any]] = []
    for framework in packet.get("frameworks", []) or []:
        for mode in (framework.get("failure_modes") or [])[:2]:
            attacks.append(
                {
                    "type": "framework_failure_mode",
                    "source": framework.get("name", ""),
                    "challenge": str(mode),
                }
            )
    for conflict in packet.get("cross_lens_conflicts", []) or []:
        attacks.append(
            {
                "type": "claim_or_lens_conflict",
                "source": conflict.get("source", "cross_lens"),
                "challenge": conflict.get("description", ""),
            }
        )
    for lens, item in coverage.items():
        if item["status"] != "covered":
            attacks.append(
                {
                    "type": "missing_lens_evidence",
                    "source": lens,
                    "challenge": f"The {lens} lens has status={item['status']}; do not average it away.",
                }
            )
    if not packet.get("citations"):
        attacks.append({"type": "no_citation", "source": "audit", "challenge": "No citations are attached yet."})
    return {"attacks": attacks[:20], "count": len(attacks)}


def _feynman(packet: dict[str, Any]) -> dict[str, Any]:
    frameworks = packet.get("frameworks", []) or []
    concept_lines = []
    for framework in frameworks[:5]:
        name = framework.get("name", "")
        one_liner = framework.get("one_liner", "")
        if name:
            concept_lines.append(f"{name}: {one_liner}".strip())
    return {
        "plain_language_draft": (
            "Explain the answer as if to a smart friend with no domain vocabulary: "
            + " | ".join(concept_lines)
            if concept_lines
            else "No framework is available yet; explain the question and list what is missing."
        ),
        "analogy_required": True,
        "self_check": "If the explanation cannot be restated without jargon, it is not finished.",
        "status": "draft_requires_synthesizer",
    }


def _evolver(store: Store, packet: dict[str, Any]) -> dict[str, Any]:
    analysis_id = str(packet.get("analysis_id", ""))
    evaluations = store.list_reading_evaluations(analysis_id=analysis_id, limit=50) if analysis_id else []
    independent = [item for item in evaluations if evaluator_kind(str(item.get("evaluator", ""))) in {"llm_judge", "human", "mixed"}]
    if not independent:
        return {
            "status": "waiting_for_independent_score",
            "message": "auto_proxy is triage only; no evolution proposal is generated from it.",
            "independent_count": 0,
        }
    latest = independent[0]
    return {
        "status": "ready",
        "evaluator": latest.get("evaluator"),
        "total": latest.get("total"),
        "low_dimensions": [
            key for key, value in (latest.get("scores") or {}).items() if float(value) < 7.0
        ],
        "next": "run evolution-propose after a real judge or human score; review before promotion",
    }


def orchestrate_analysis(
    store: Store,
    packet: dict[str, Any],
    retrieval: dict[str, Any] | None = None,
    reader_notes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the fixed role pipeline and return an auditable trace."""
    packet = dict(packet)
    retrieval = retrieval or packet.get("retrieval", {}) or {}
    reader_notes = reader_notes if reader_notes is not None else packet.get("reader_notes", []) or []
    stages: list[dict[str, Any]] = []

    plan = _planner(packet)
    stages.append(_stage("planner", "complete", f"{len(plan['sub_questions'])} sub-questions planned", plan))

    channels = retrieval.get("channels", {}) if isinstance(retrieval, dict) else {}
    graph = retrieval.get("graph", {}) if isinstance(retrieval, dict) else {}
    stages.append(
        _stage(
            "retriever",
            "complete" if channels else "degraded",
            f"hybrid={len(channels.get('hybrid', []))}, graph={len(channels.get('graph', []))}, fused={len(channels.get('fused', []))}",
            {"channels": {key: len(value) for key, value in channels.items()}, "graph": graph,
             "communities": (retrieval or {}).get("communities", [])},
        )
    )

    stages.append(
        _stage(
            "reader",
            "complete" if reader_notes else "empty",
            f"{len(reader_notes)} user-authored note(s) recalled as memory context",
            {"notes": reader_notes[:8], "memory_only": True, "never_citations": True},
        )
    )

    feynman = _feynman(packet)
    stages.append(_stage("feynman_explainer", "draft", "plain-language draft generated; not a conclusion", feynman))

    coverage = _lens_coverage(store, packet)
    red = _red_team(packet, coverage)
    stages.append(_stage("red_team", "complete", f"{red['count']} challenge(s) generated", red))

    audit = _citation_audit(packet, store)
    stages.append(
        _stage(
            "citation_auditor",
            "pass" if audit.get("checked") and not audit.get("error_count") else ("fail" if audit.get("checked") else "unavailable"),
            f"errors={audit.get('error_count', 'n/a')}, warnings={audit.get('warning_count', 'n/a')}",
            audit,
        )
    )
    stages.append(_stage("lens_reviewer", "complete", f"{len(coverage)} lens/lenses inspected", coverage))

    stages.append(
        _stage(
            "synthesizer",
            "waiting_for_final_answer" if str(packet.get("status", "draft")) != "complete" else "complete",
            "Synthesis is owned by the calling agent; this stage does not fabricate a conclusion.",
            {"conclusion_present": bool(str(packet.get("conclusion", "")).strip()), "status": packet.get("status")},
        )
    )
    stages.append(
        _stage(
            "judge",
            "waiting_for_independent_judge",
            "No score is produced here. Run the independent judge after status=complete.",
            {"auto_proxy_is_not_a_judge": True},
        )
    )
    stages.append(_stage("evolver", "complete", "Independent-score gate evaluated", _evolver(store, packet)))

    stop_conditions = [
        "citation_auditor must not report an error before a final answer is trusted",
        "every active lens needs at least one framework and one citation, otherwise mark uncertainty",
        "reader notes are memory only and never become citations",
        "no evolution proposal from auto_proxy alone",
    ]
    next_actions = []
    if not channels:
        next_actions.append("rebuild retrieval / graph sidecar")
    if not coverage or any(item["status"] != "covered" for item in coverage.values()):
        next_actions.append("fill missing lens evidence or state the coverage gap")
    if red["count"]:
        next_actions.append("answer the strongest red-team challenge explicitly")
    if str(packet.get("status", "draft")) != "complete":
        next_actions.append("write the final conclusion and citations, then apply the patch")
    else:
        next_actions.append("run the independent judge (Ollama/OpenAI-compatible)")

    return {
        "execution": "automatic",
        "mode": "deterministic-role-pipeline",
        "agent_count": len(ROLE_ORDER),
        "stages": stages,
        "lens_coverage": coverage,
        "red_team": red,
        "stop_conditions": stop_conditions,
        "next_actions": next_actions,
        "boundary": "Roles are deterministic stages, not free-form multi-LLM debate. The judge is the only additional independent model call.",
    }