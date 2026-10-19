from __future__ import annotations

import json
import os
from typing import Any

from .models import utc_now
from .store import Store, query_terms
from .utils import stable_id


ERROR_TAXONOMY: dict[str, dict[str, str]] = {
    "retrieval_miss": {
        "label": "retrieval miss",
        "meaning": "The relevant book or passage existed but was not retrieved.",
        "target": "retrieval",
    },
    "compilation_error": {
        "label": "compilation error",
        "meaning": "A book card or framework card misstates the source.",
        "target": "compilation",
    },
    "framework_misapplication": {
        "label": "framework misapplication",
        "meaning": "A framework was used outside the conditions stated in its card.",
        "target": "framework_selection",
    },
    "citation_error": {
        "label": "citation error",
        "meaning": "A quote, chapter, page, or attribution is wrong.",
        "target": "citation_validation",
    },
    "lens_omission": {
        "label": "lens omission",
        "meaning": "A requested lens was silently dropped or not represented.",
        "target": "lens_coverage",
    },
    "conflict_suppression": {
        "label": "conflict suppression",
        "meaning": "The analysis averaged away a real disagreement between lenses.",
        "target": "analysis_prompt",
    },
    "overconfidence": {
        "label": "overconfidence",
        "meaning": "The conclusion was stated with more certainty than the evidence supports.",
        "target": "calibration",
    },
    "taste_mismatch": {
        "label": "taste mismatch",
        "meaning": "The style, depth, or format did not match the user's preference.",
        "target": "ranking",
    },
}


DEFAULT_EVOLUTION_CONFIG: dict[str, Any] = {
    "retrieval": {
        "bm25_weight": 0.55,
        "embedding_weight": 0.35,
        "entity_weight": 0.10,
        "lexical_expansion_weight": 0.35,
        "lazy_embed": True,
        "entity_expand": True,
        "rerank": None,
        "rerank_candidates": 40,
    },
    "selection": {
        "lens_weight": 3.0,
        "direction_weight": 2.0,
        "preference_weight": 1.5,
    },
    "preference_overrides": {"books": {}, "frameworks": {}},
    "revision": 0,
}

EXECUTABLE_CHANGES = {"book_preference_boost", "framework_preference_boost", "retrieval_weight_adjustment"}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base, ensure_ascii=False))
    for key, value in (overlay or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_evolution_config(store: Store) -> dict[str, Any]:
    saved = store.get_state("evolution_config", {})
    return _deep_merge(DEFAULT_EVOLUTION_CONFIG, saved if isinstance(saved, dict) else {})


def is_executable(proposal: dict[str, Any]) -> bool:
    change = proposal.get("change", {})
    return isinstance(change, dict) and change.get("kind") in EXECUTABLE_CHANGES


def _apply_change(config: dict[str, Any], change: dict[str, Any]) -> dict[str, Any]:
    kind = str(change.get("kind", ""))
    if kind == "book_preference_boost":
        book_id = str(change.get("book_id", ""))
        if not book_id:
            raise ValueError("book_preference_boost requires book_id")
        current = float(config["preference_overrides"].get("books", {}).get(book_id, 0.0))
        config["preference_overrides"].setdefault("books", {})[book_id] = round(min(4.0, current + float(change.get("weight_delta", 1.5))), 3)
    elif kind == "framework_preference_boost":
        framework_id = str(change.get("framework_id", ""))
        if not framework_id:
            raise ValueError("framework_preference_boost requires framework_id")
        current = float(config["preference_overrides"].get("frameworks", {}).get(framework_id, 0.0))
        config["preference_overrides"].setdefault("frameworks", {})[framework_id] = round(min(4.0, current + float(change.get("weight_delta", 1.5))), 3)
    elif kind == "retrieval_weight_adjustment":
        for key in ("bm25_weight", "embedding_weight", "entity_weight"):
            if key in change:
                config["retrieval"][key] = max(0.0, min(1.0, float(change[key])))
        total = sum(float(config["retrieval"].get(key, 0.0)) for key in ("bm25_weight", "embedding_weight", "entity_weight"))
        if total <= 0:
            raise ValueError("retrieval weights must not all be zero")
    else:
        raise ValueError(f"change kind '{kind}' is not executable")
    config["revision"] = int(config.get("revision", 0)) + 1
    return config


def shadow_evaluate(store: Store, proposal: dict[str, Any], k: int = 5, cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Compare a candidate config against production without promoting it.

    The gate rejects changes that reduce retrieval hit rate, MRR, or cross-book
    coverage beyond small tolerances. It is deliberately narrow: only bounded
    retrieval/preference config is evaluated, never cards, quotes, prompts, or
    code.
    """
    from .eval_retrieval import quick_hybrid_metrics

    baseline_config = get_evolution_config(store)
    candidate_config = _apply_change(_deep_merge(DEFAULT_EVOLUTION_CONFIG, baseline_config), proposal.get("change", {}))
    try:
        store.set_state("evolution_config", candidate_config)
        candidate = quick_hybrid_metrics(store, k=k, cases=cases)
    finally:
        store.set_state("evolution_config", baseline_config)
    baseline = quick_hybrid_metrics(store, k=k, cases=cases)
    hit_tolerance = float(os.environ.get("BOOKCOMPILER_GATE_HIT_TOL", "0.02"))
    mrr_tolerance = float(os.environ.get("BOOKCOMPILER_GATE_MRR_TOL", "0.03"))
    coverage_tolerance = float(os.environ.get("BOOKCOMPILER_GATE_COVERAGE_TOL", "0.05"))
    reasons: list[str] = []
    if candidate["hit_at_k"] < baseline["hit_at_k"] - hit_tolerance:
        reasons.append(f"hit@k dropped {baseline['hit_at_k']} -> {candidate['hit_at_k']}")
    if candidate["mrr"] < baseline["mrr"] - mrr_tolerance:
        reasons.append(f"MRR dropped {baseline['mrr']} -> {candidate['mrr']}")
    if candidate["book_coverage"] < baseline["book_coverage"] - coverage_tolerance:
        reasons.append(f"book coverage dropped {baseline['book_coverage']} -> {candidate['book_coverage']}")
    result = {
        "gate": "passed" if not reasons else "failed",
        "passed": not reasons,
        "reasons": reasons,
        "baseline": baseline,
        "candidate": candidate,
        "tolerance": {"hit_at_k": hit_tolerance, "mrr": mrr_tolerance, "book_coverage": coverage_tolerance},
        "scope": "retrieval-only shadow; structural replay is checked separately",
        "evaluated_at": utc_now(),
    }
    store.record_evolution_run(
        str(proposal.get("proposal_id", "")),
        "shadow",
        result,
        {"baseline_config": baseline_config, "candidate_config": candidate_config},
    )
    return result


def _validate_quality_gate(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise ValueError("promotion requires a quality report; shadow evaluation is run automatically when possible")
    if report.get("passed") is not True:
        reasons = report.get("reasons") or ["quality report did not pass"]
        raise ValueError("quality gate failed: " + "; ".join(str(reason) for reason in reasons))
    return report


def apply_evolution(store: Store, proposal_id: str, replay_report: dict[str, Any] | None = None, quality_report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply an executable proposal only after structural and quality gates.

    Flow: replay gate -> shadow retrieval comparison -> candidate canary ->
    promote. If the canary degrades metrics, the pre-promotion snapshot is
    restored automatically and the proposal stays in shadow status.
    """
    proposal = store.get_evolution_proposal(proposal_id)
    if not proposal:
        raise ValueError(f"Unknown proposal_id: {proposal_id}")
    if proposal.get("status") != "shadow":
        raise ValueError("only a proposal in shadow status can be promoted/applied")
    if not is_executable(proposal):
        raise ValueError("proposal has no executable change; keep it as an advisory review item")
    evidence = _validate_replay_gate(replay_report)
    quality = quality_report if isinstance(quality_report, dict) else shadow_evaluate(store, proposal)
    _validate_quality_gate(quality)
    snapshot = get_evolution_config(store)
    candidate = _apply_change(_deep_merge(DEFAULT_EVOLUTION_CONFIG, snapshot), proposal.get("change", {}))
    run_id = ""
    try:
        store.set_state("evolution_config", candidate)
        from .eval_retrieval import quick_hybrid_metrics

        canary = quick_hybrid_metrics(store, k=5)
        baseline = quality.get("baseline", {})
        canary_reasons: list[str] = []
        if baseline:
            if canary["hit_at_k"] < float(baseline.get("hit_at_k", 0.0)) - float(os.environ.get("BOOKCOMPILER_GATE_HIT_TOL", "0.02")):
                canary_reasons.append("canary hit@k dropped")
            if canary["mrr"] < float(baseline.get("mrr", 0.0)) - float(os.environ.get("BOOKCOMPILER_GATE_MRR_TOL", "0.03")):
                canary_reasons.append("canary MRR dropped")
        canary_report = {
            "gate": "passed" if not canary_reasons else "failed",
            "passed": not canary_reasons,
            "reasons": canary_reasons,
            "metrics": canary,
            "baseline": baseline,
        }
        if canary_reasons:
            store.set_state("evolution_config", snapshot)
            result = store.set_evolution_status(proposal_id, "shadow", "auto-rollback: " + "; ".join(canary_reasons))
            result["auto_rolled_back"] = True
            result["canary"] = canary_report
            store.save_evolution_proposal(result)
            store.record_evolution_run(proposal_id, "canary-failed", canary_report, {"before": snapshot, "attempted": candidate})
            raise ValueError("canary gate failed; production config restored: " + "; ".join(canary_reasons))
        evidence = {**evidence, "execution": "bounded-config-patch", "revision": candidate["revision"], "quality_gate": quality.get("gate")}
        result = store.set_evolution_status(proposal_id, "promoted", "applied bounded config patch")
        result["promotion_evidence"] = evidence
        result["quality_report"] = quality
        result["canary"] = canary_report
        result["applied_config"] = candidate
        store.save_evolution_proposal(result)
        run_id = store.record_evolution_run(proposal_id, "promote", {**evidence, "canary": canary_report}, {"before": snapshot, "after": candidate})
    except ValueError:
        raise
    except Exception:
        store.set_state("evolution_config", snapshot)
        store.record_evolution_run(proposal_id, "promote-failed", {"error": "apply failed"}, {"before": snapshot, "after": candidate})
        raise
    result["run_id"] = run_id
    return result


def rollback_evolution(store: Store, proposal_id: str, note: str = "") -> dict[str, Any]:
    proposal = store.get_evolution_proposal(proposal_id)
    if not proposal:
        raise ValueError(f"Unknown proposal_id: {proposal_id}")
    if proposal.get("status") != "promoted":
        raise ValueError("only a promoted proposal can be rolled back")
    rows = store.conn.execute(
        "SELECT snapshot FROM evolution_runs WHERE proposal_id = ? AND mode = 'promote' ORDER BY created_at DESC LIMIT 1",
        (proposal_id,),
    ).fetchall()
    snapshot = json.loads(rows[0]["snapshot"]) if rows else {}
    before = get_evolution_config(store)
    restore = (snapshot or {}).get("before", DEFAULT_EVOLUTION_CONFIG)
    store.set_state("evolution_config", restore)
    result = store.set_evolution_status(proposal_id, "rolled_back", note or "restored pre-promotion snapshot")
    result["restored_config"] = restore
    store.save_evolution_proposal(result)
    store.record_evolution_run(proposal_id, "rollback", {"restored_revision": restore.get("revision", 0)}, {"before": before, "after": restore})
    return result


def recall_memory(store: Store, query: str, lenses: list[str], limit: int = 8) -> list[dict[str, Any]]:
    """Hindsight-style recall: retrieve lessons from feedback and explicit memory.

    Books are not stored here. The memory layer stores decisions, corrections, and
    preferences, while source text remains in the library and is cited from it.
    """
    query_set = set(query_terms(query))
    lens_set = set(lenses)
    analyses = {item.get("analysis_id", ""): item for item in store.list_analyses()}
    book_titles = {book["book_id"]: book["title"] for book in store.list_books()}
    framework_names = {item["framework_id"]: item["name"] for item in store.list_frameworks()}
    scored: list[tuple[float, dict[str, Any]]] = []

    for feedback in store.list_feedback():
        analysis = analyses.get(feedback.get("analysis_id", ""), {})
        prior_question = analysis.get("question", "")
        overlap = len(query_set.intersection(set(query_terms(prior_question))))
        lens_overlap = len(lens_set.intersection(set(analysis.get("lenses", []))))
        if overlap == 0 and lens_overlap == 0:
            continue
        rating = int(feedback.get("rating", 3))
        score = 2.0 * overlap + 1.0 * lens_overlap + (1.0 if rating <= 2 else 0.25)
        lesson = {
            "source": "feedback",
            "feedback_id": feedback.get("feedback_id"),
            "analysis_id": feedback.get("analysis_id"),
            "prior_question": prior_question,
            "rating": rating,
            "error_labels": feedback.get("error_labels", []),
            "note": feedback.get("note", ""),
            "missing_evidence": feedback.get("missing_evidence", ""),
            "outcome": feedback.get("outcome", ""),
            "preferred_books": [book_titles.get(book_id, book_id) for book_id in feedback.get("preferred_book_ids", [])],
            "preferred_frameworks": [
                framework_names.get(framework_id, framework_id)
                for framework_id in feedback.get("preferred_framework_ids", [])
            ],
            "relevance": round(score, 3),
        }
        scored.append((score, lesson))

    for memory in store.list_memory():
        value_text = json.dumps(memory.get("value"), ensure_ascii=False)
        text = f"{memory.get('kind', '')} {memory.get('key', '')} {value_text}"
        overlap = len(query_set.intersection(set(query_terms(text))))
        if overlap == 0:
            continue
        lesson = {
            "source": "memory",
            "memory_id": memory.get("memory_id"),
            "kind": memory.get("kind"),
            "key": memory.get("key"),
            "value": memory.get("value"),
            "relevance": round(float(overlap), 3),
        }
        scored.append((float(overlap), lesson))

    scored.sort(key=lambda pair: -pair[0])
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, lesson in scored:
        key = str(lesson.get("feedback_id") or lesson.get("memory_id") or lesson.get("analysis_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(lesson)
        if len(deduped) >= limit:
            break

    # Optional long-term memory.  Hindsight stores lessons, not book text, and
    # its failure must never break local recall.  Reserve up to half the slots
    # so a long local feedback history cannot crowd out durable corrections.
    try:
        from . import hindsight

        if hindsight.enabled():
            remote, _meta = hindsight.merged_lessons(query, limit=limit)
            if remote:
                remote_take = min(len(remote), max(1, limit // 2))
                local_take = max(0, limit - remote_take)
                merged = deduped[:local_take] + remote[:remote_take]
                deduped = merged[:limit]
    except Exception:
        # Deliberately silent: memory is an enhancement, not a dependency.
        pass
    return deduped
def _proposal(
    target: str,
    change: dict[str, Any],
    rationale: str,
    feedback_ids: list[str],
    support: int,
    risk: str,
    rollback: str,
) -> dict[str, Any]:
    created_at = utc_now()
    proposal_id = stable_id("v2", target, json.dumps(change, ensure_ascii=False, sort_keys=True), ",".join(sorted(feedback_ids)))
    return {
        "proposal_id": proposal_id,
        "version": "v2",
        "created_at": created_at,
        "status": "proposed",
        "target": target,
        "change": change,
        "rationale": rationale,
        "support": support,
        "evidence_feedback_ids": sorted(set(feedback_ids)),
        "risk": risk,
        "rollback": rollback,
        "gate": "Replay evaluation and explicit acceptance are required before promotion.",
    }


def _reading_proposals(store: Store, min_support: int = 1, threshold: float = 6.0) -> list[dict[str, Any]]:
    """Turn weak reading-effectiveness dimensions into evidence-backed proposals.

    These proposals are advisory by default: a low score tells the system where
    to look, but it does not justify silently rewriting a book card or prompt.
    Promotion still goes through the replay gate and the normal status machine.
    """
    from .reading_eval import DIMENSION_BY_KEY, RUBRIC_VERSION, evaluator_kind

    # auto_proxy is a deterministic triage signal. It must never drive
    # "learning" proposals as if it were an independent quality judgement.
    evaluations = [
        evaluation
        for evaluation in store.list_reading_evaluations(limit=2000)
        if evaluator_kind(str(evaluation.get("evaluator", ""))) in {"llm_judge", "human", "mixed"}
    ]
    if not evaluations:
        return []
    actions = {
        "source_fidelity": "Re-check citation extraction and validation; add the failing quotes to the replay set.",
        "retrieval_coverage": "Run eval-retrieval; try query expansion or RRF fusion before adding new books.",
        "framework_fit": "Review framework applicability conditions and the selection ranking.",
        "cross_book_synthesis": "Require at least two independent books before synthesis; add a cross-book comparison check.",
        "cross_lens_integration": "Require one causal mechanism per lens; add lens-specific hypothesis prompts.",
        "conflict_handling": "Surface claim-graph conflicts explicitly; never average incompatible lenses.",
        "calibration": "Require uncertainty and falsification conditions before an analysis can be marked complete.",
        "actionability": "Require observable next checks and a conditional conclusion.",
        "failure_mode_awareness": "Require failure_modes and counterexamples on framework cards.",
    }
    proposals: list[dict[str, Any]] = []
    for key, dimension in DIMENSION_BY_KEY.items():
        low_ids = [
            str(evaluation.get("evaluation_id", ""))
            for evaluation in evaluations
            if float(evaluation.get("scores", {}).get(key, 0.0)) < threshold
        ]
        if len(low_ids) < min_support:
            continue
        proposal = _proposal(
            target=dimension.get("target", "analysis_prompt"),
            change={
                "kind": "review_reading_dimension",
                "dimension": key,
                "label": dimension.get("label", key),
                "mean_below_threshold": threshold,
                "action": actions.get(key, "Review the affected layer and replay the change."),
            },
            rationale=(
                f"Reading-effectiveness dimension '{dimension.get('label', key)}' "
                f"was below {threshold}/10 in {len(low_ids)} evaluation(s)."
            ),
            feedback_ids=low_ids,
            support=len(low_ids),
            risk="A small evaluation set can overfit; a low proxy score may reflect a draft packet rather than a real reading failure.",
            rollback="Keep the previous card, prompt, or ranking version and restore it if replay quality drops.",
        )
        proposal["source"] = "reading_eval"
        proposal["rubric_version"] = RUBRIC_VERSION
        proposal["evidence_evaluation_ids"] = low_ids
        proposal["evidence_feedback_ids"] = []
        proposals.append(proposal)
    return proposals


def propose_evolutions(store: Store, min_support: int = 1) -> list[dict[str, Any]]:
    feedback_items = store.list_feedback()
    if not feedback_items and not store.list_reading_evaluations(limit=1):
        return []
    proposals: dict[str, dict[str, Any]] = {}
    label_feedback: dict[str, list[str]] = {}
    book_feedback: dict[str, list[str]] = {}
    framework_feedback: dict[str, list[str]] = {}
    missing_evidence_feedback: dict[str, list[str]] = {}
    low_rating_feedback: list[str] = []
    low_rating_analysis_ids: list[str] = []

    for feedback in feedback_items:
        feedback_id = feedback.get("feedback_id", "")
        rating = int(feedback.get("rating", 3))
        if rating <= 2:
            low_rating_feedback.append(feedback_id)
            if feedback.get("analysis_id"):
                low_rating_analysis_ids.append(feedback["analysis_id"])
        for label in feedback.get("error_labels", []):
            label_feedback.setdefault(label, []).append(feedback_id)
        for book_id in feedback.get("preferred_book_ids", []):
            book_feedback.setdefault(book_id, []).append(feedback_id)
        for framework_id in feedback.get("preferred_framework_ids", []):
            framework_feedback.setdefault(framework_id, []).append(feedback_id)
        missing = str(feedback.get("missing_evidence", "")).strip()
        if missing:
            missing_evidence_feedback.setdefault(missing, []).append(feedback_id)

    for label, feedback_ids in sorted(label_feedback.items()):
        if label == "retrieval_miss":
            # Repeated retrieval misses get a bounded, executable candidate
            # below instead of an advisory-only "review the problem" item.
            continue
        if len(feedback_ids) < min_support:
            continue
        taxonomy = ERROR_TAXONOMY.get(label, {"label": label, "target": "analysis_prompt"})
        proposal = _proposal(
            target=taxonomy.get("target", "analysis_prompt"),
            change={
                "kind": "review_error_pattern",
                "error_label": label,
                "action": "Create a candidate patch for the affected layer and replay it before promotion.",
            },
            rationale=f"Repeated feedback label '{taxonomy.get('label', label)}' with {len(feedback_ids)} supporting item(s).",
            feedback_ids=feedback_ids,
            support=len(feedback_ids),
            risk="A local fix may overfit a small number of examples.",
            rollback="Keep the previous card, prompt, or ranking version and restore it if replay quality drops.",
        )
        proposals[proposal["proposal_id"]] = proposal

    retrieval_miss_feedback = label_feedback.get("retrieval_miss", [])
    if len(retrieval_miss_feedback) >= min_support:
        retrieval = get_evolution_config(store).get("retrieval", {})
        bm25 = float(retrieval.get("bm25_weight", 0.55))
        embedding = float(retrieval.get("embedding_weight", 0.35))
        entity = float(retrieval.get("entity_weight", 0.10))
        shift = round(min(0.05, max(0.0, bm25 - 0.35)), 3)
        if shift > 0:
            proposal = _proposal(
                target="retrieval",
                change={
                    "kind": "retrieval_weight_adjustment",
                    "bm25_weight": round(bm25 - shift, 3),
                    "embedding_weight": round(min(0.55, embedding + shift), 3),
                    "entity_weight": round(entity, 3),
                },
                rationale=(
                    f"{len(retrieval_miss_feedback)} retrieval-miss feedback item(s): "
                    "the source existed but lexical retrieval did not surface it. "
                    f"Shift {shift:.2f} weight from BM25 to embedding."
                ),
                feedback_ids=retrieval_miss_feedback,
                support=len(retrieval_miss_feedback),
                risk=(
                    "A small feedback sample may overfit; embedding retrieval is "
                    "also only as good as the configured embedding backend."
                ),
                rollback=(
                    "Restore the pre-promotion snapshot; retrieval weights are "
                    "configuration only and do not alter book text or cards."
                ),
            )
            proposals[proposal["proposal_id"]] = proposal

    for book_id, feedback_ids in sorted(book_feedback.items()):
        if len(feedback_ids) < min_support:
            continue
        book = store.get_book(book_id)
        title = book["title"] if book else book_id
        proposal = _proposal(
            target="ranking",
            change={"kind": "book_preference_boost", "book_id": book_id, "weight_delta": 1.5},
            rationale=f"Book '{title}' was explicitly preferred in past feedback.",
            feedback_ids=feedback_ids,
            support=len(feedback_ids),
            risk="Preference feedback can create a rich-get-richer loop.",
            rollback="Set weight_delta to zero or remove the preference row; source evidence is unchanged.",
        )
        proposals[proposal["proposal_id"]] = proposal

    for framework_id, feedback_ids in sorted(framework_feedback.items()):
        if len(feedback_ids) < min_support:
            continue
        framework = store.get_framework(framework_id)
        name = framework.get("name", framework_id) if framework else framework_id
        proposal = _proposal(
            target="ranking",
            change={"kind": "framework_preference_boost", "framework_id": framework_id, "weight_delta": 1.5},
            rationale=f"Framework '{name}' was explicitly preferred in past feedback.",
            feedback_ids=feedback_ids,
            support=len(feedback_ids),
            risk="A preferred framework may crowd out better-fitting alternatives.",
            rollback="Remove the weight or cap it during selection; the framework card itself is unchanged.",
        )
        proposals[proposal["proposal_id"]] = proposal

    for missing, feedback_ids in sorted(missing_evidence_feedback.items()):
        if len(feedback_ids) < min_support:
            continue
        proposal = _proposal(
            target="retrieval",
            change={
                "kind": "add_missing_source_or_query_expansion",
                "missing_evidence": missing,
                "action": "Propose a candidate book for approval or add a transparent query-expansion rule.",
            },
            rationale="The user identified evidence that the library or retrieval layer did not supply.",
            feedback_ids=feedback_ids,
            support=len(feedback_ids),
            risk="Silently ingesting a source would violate the approval gate.",
            rollback="Remove the expansion rule or the newly approved book from the library.",
        )
        proposals[proposal["proposal_id"]] = proposal

    if len(low_rating_feedback) >= min_support:
        proposal = _proposal(
            target="analysis_prompt",
            change={"kind": "review_low_rated_analyses", "analysis_ids": sorted(set(low_rating_analysis_ids))},
            rationale=f"{len(low_rating_feedback)} analysis result(s) were rated 1 or 2.",
            feedback_ids=low_rating_feedback,
            support=len(low_rating_feedback),
            risk="A low rating may reflect taste rather than reasoning quality.",
            rollback="Keep prompt versions immutable and compare before and after on the replay set.",
        )
        proposals[proposal["proposal_id"]] = proposal

    for proposal in _reading_proposals(store, min_support=min_support):
        proposals[proposal["proposal_id"]] = proposal

    result = sorted(proposals.values(), key=lambda item: (-item["support"], item["target"], item["proposal_id"]))
    for proposal in result:
        existing = store.get_evolution_proposal(proposal["proposal_id"])
        if existing:
            proposal["status"] = existing.get("status", "proposed")
            for key in ("decided_at", "decision_note", "promotion_evidence"):
                if key in existing:
                    proposal[key] = existing[key]
        store.save_evolution_proposal(proposal)
    return result
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"accepted", "rejected"},
    "accepted": {"shadow", "rejected"},
    "shadow": {"promoted", "rolled_back", "rejected"},
    "promoted": {"rolled_back"},
    "rolled_back": set(),
    "rejected": set(),
}


def _validate_replay_gate(report: dict[str, Any] | None) -> dict[str, Any]:
    """Promotion is allowed only after a clean structural replay.

    This gate is intentionally deterministic. It proves that the candidate run did
    not introduce citation, selection, or structural regressions on the replay set;
    it does not claim that the candidate is qualitatively better.
    """
    if not isinstance(report, dict):
        raise ValueError("promotion requires a replay report; run `bookcompiler replay ... --out report.json` first")
    cases = report.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("replay report has no cases; promotion needs at least one replay case")
    reported_count = int(report.get("case_count", -1))
    passed_count = int(report.get("structural_pass_count", -1))
    if reported_count != len(cases):
        raise ValueError("replay report is inconsistent: case_count does not match cases")
    if passed_count != len(cases):
        raise ValueError(f"replay gate failed: {passed_count}/{len(cases)} cases passed")
    failures: list[str] = []
    for case in cases:
        issues = case.get("issues", []) if isinstance(case, dict) else []
        errors = [issue for issue in issues if isinstance(issue, dict) and issue.get("severity") == "error"]
        if not isinstance(case, dict) or not case.get("structural_pass") or errors:
            failures.append(str(case.get("case_id", "unknown")) if isinstance(case, dict) else "unknown")
    if failures:
        raise ValueError("replay gate failed for cases: " + ", ".join(failures))
    regressions = report.get("regressions", [])
    if regressions:
        raise ValueError(f"replay gate failed: {len(regressions)} regression(s) reported")
    return {
        "gate": "passed",
        "case_count": len(cases),
        "structural_pass_count": passed_count,
        "generated_at": report.get("generated_at", ""),
        "scope": "structural regression only; not a blind quality benchmark",
    }


def decide_evolution(
    store: Store,
    proposal_id: str,
    status: str,
    note: str = "",
    replay_report: dict[str, Any] | None = None,
    quality_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    allowed = {"accepted", "rejected", "shadow", "promoted", "rolled_back"}
    if status not in allowed:
        raise ValueError(f"status must be one of: {', '.join(sorted(allowed))}")
    proposal = store.get_evolution_proposal(proposal_id)
    if not proposal:
        raise ValueError(f"Unknown proposal_id: {proposal_id}")
    current = proposal.get("status", "proposed")
    if status == current:
        return proposal
    permitted = ALLOWED_TRANSITIONS.get(current, set())
    if status not in permitted:
        raise ValueError(
            f"illegal transition {current} -> {status}; allowed from {current}: "
            + (", ".join(sorted(permitted)) or "none")
        )
    if status == "promoted":
        if is_executable(proposal):
            return apply_evolution(store, proposal_id, replay_report, quality_report)
        promotion_evidence = _validate_replay_gate(replay_report)
        promotion_evidence["execution"] = "advisory-only"
        result = store.set_evolution_status(proposal_id, status, note)
        result["promotion_evidence"] = promotion_evidence
        store.save_evolution_proposal(result)
        return result
    if status == "rolled_back" and current == "promoted":
        return rollback_evolution(store, proposal_id, note)
    result = store.set_evolution_status(proposal_id, status, note)
    return result


def replay_cases(store: Store, cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the deterministic structural replay harness.

    This is not a substitute for blind human or LLM-as-judge quality scoring.
    It checks selection, citation, lens coverage, and validation regressions.
    """
    from .analysis import create_analysis
    from .modes import build_proposal
    from .validation import validate_analysis_packet

    results: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        query = case.get("query", "")
        lenses = case.get("lenses", ["economics", "politics", "law"])
        mode = case.get("mode", "auto")
        choice = case.get("choice", "specified+recommended")
        proposal = build_proposal(
            store,
            mode=mode,
            query=query,
            lenses=lenses,
            book_ids=case.get("book_ids", []),
            framework_ids=case.get("framework_ids", []),
            direction=case.get("direction", ""),
        )
        packet = create_analysis(store, query, lenses, proposal, choice)
        packet_dict = packet.to_dict()
        book_ids = [book.get("book_id", "") for book in packet_dict.get("selection", {}).get("books", [])]
        framework_ids = [framework.get("framework_id", "") for framework in packet_dict.get("frameworks", [])]
        chunks_by_book = {book_id: store.get_chunks(book_id) for book_id in book_ids if book_id}
        issues = validate_analysis_packet(packet_dict, chunks_by_book)
        expected_books = set(case.get("expected_book_ids", []))
        expected_frameworks = set(case.get("expected_framework_ids", []))
        expected_lenses = set(case.get("lenses", lenses))
        covered_lenses = set()
        for framework in packet_dict.get("frameworks", []):
            covered_lenses.update(framework.get("lenses", []))
        results.append(
            {
                "case_id": case.get("case_id", f"case-{index}"),
                "query": query,
                "analysis_id": packet.analysis_id,
                "mode": mode,
                "choice": choice,
                "books": book_ids,
                "frameworks": framework_ids,
                "citation_count": len(packet_dict.get("citations", [])),
                "memory_lessons": len(packet_dict.get("memory_context", [])),
                "book_hit_rate": round(len(expected_books.intersection(book_ids)) / len(expected_books), 3) if expected_books else None,
                "framework_hit_rate": round(len(expected_frameworks.intersection(framework_ids)) / len(expected_frameworks), 3) if expected_frameworks else None,
                "lens_coverage": round(len(expected_lenses.intersection(covered_lenses)) / len(expected_lenses), 3) if expected_lenses else None,
                "structural_pass": not any(issue.severity == "error" for issue in issues),
                "issues": [issue.to_dict() for issue in issues],
            }
        )
    return {
        "generated_at": utc_now(),
        "case_count": len(results),
        "structural_pass_count": sum(1 for item in results if item["structural_pass"]),
        "cases": results,
    }