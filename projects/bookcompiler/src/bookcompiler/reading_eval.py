from __future__ import annotations

import json
from typing import Any

from .models import ValidationIssue, utc_now
from .store import Store
from .utils import stable_id
from .validation import validate_analysis_packet


RUBRIC_VERSION = "reading-effectiveness-v1"

# Weights sum to 100.  The rubric is deliberately about *reading effectiveness*,
# not about how polished the prose is.  A beautiful answer that cites one book
# and ignores the other lenses should score badly.
READING_DIMENSIONS: list[dict[str, Any]] = [
    {
        "key": "source_fidelity",
        "label": "原文忠实度",
        "weight": 18,
        "target": "citation_validation",
        "question": "引用是否逐字来自原文，章节和页码是否可核验，是否存在编造或错配？",
    },
    {
        "key": "retrieval_coverage",
        "label": "检索覆盖",
        "weight": 14,
        "target": "retrieval",
        "question": "是否召回了回答所需的关键章节、证据和框架，而不是只抓到表面相似的段落？",
    },
    {
        "key": "framework_fit",
        "label": "框架适配",
        "weight": 12,
        "target": "framework_selection",
        "question": "所用框架是否真的适用于当前问题，而不是只在套用书名或术语？",
    },
    {
        "key": "cross_book_synthesis",
        "label": "跨书综合",
        "weight": 12,
        "target": "retrieval",
        "question": "是否让多本书真正互相补充或对照，而不是把几本书并列摘抄？",
    },
    {
        "key": "cross_lens_integration",
        "label": "跨学科整合",
        "weight": 12,
        "target": "analysis_prompt",
        "question": "经济、政治、法律等镜头是否形成相互制约的整体判断，而不是三篇互不相干的短文？",
    },
    {
        "key": "conflict_handling",
        "label": "冲突处理",
        "weight": 10,
        "target": "analysis_prompt",
        "question": "是否显式处理书与书、镜头与镜头之间的矛盾，而不是把冲突平均掉？",
    },
    {
        "key": "calibration",
        "label": "置信校准",
        "weight": 8,
        "target": "calibration",
        "question": "结论是否给出适用条件、不确定性和反证条件，而不是过度自信？",
    },
    {
        "key": "actionability",
        "label": "可行动性",
        "weight": 8,
        "target": "analysis_prompt",
        "question": "是否给出可观察指标、下一步检查或可执行建议？",
    },
    {
        "key": "failure_mode_awareness",
        "label": "失败模式意识",
        "weight": 6,
        "target": "compilation",
        "question": "是否说明框架何时会失效、有哪些反例和适用边界？",
    },
]

DIMENSION_BY_KEY = {item["key"]: item for item in READING_DIMENSIONS}
TOTAL_WEIGHT = sum(int(item["weight"]) for item in READING_DIMENSIONS)

_ACTION_BY_KEY = {
    "source_fidelity": "先修引用：逐字回查 quote，补齐 book_id、chapter、page；校验失败就删除或标成推断。",
    "retrieval_coverage": "补检索：拆问题、换关键词、增加多跳检索，确认关键章节和框架都被召回。",
    "framework_fit": "重做框架选择：写出“为什么这个框架适用于此事件”，并列出不适用的条件。",
    "cross_book_synthesis": "强制跨书：至少找两本观点不同的书，分别回答“同一问题它会看到什么”。",
    "cross_lens_integration": "做镜头冲突表：每个镜头写判断、证据、与其他镜头的冲突，再合成条件结论。",
    "conflict_handling": "显式列冲突：书与书、镜头与镜头不一致时，不取平均，写清在什么条件下谁优先。",
    "calibration": "补置信校准：写出反证条件、关键不确定性和“什么新证据会改变结论”。",
    "actionability": "补行动层：给出可观察指标、下一步检查、责任主体和时间窗口。",
    "failure_mode_awareness": "补失败模式：为每个框架写至少一个失效条件和一个反例。",
}


def _next_actions(dimensions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "key": item["key"],
            "label": item["label"],
            "mean": item["mean"],
            "action": _ACTION_BY_KEY.get(item["key"], "针对这个维度做一次小样本复盘。"),
        }
        for item in dimensions
        if float(item.get("mean", 10.0)) < 6.0
    ]


def _clip(value: float, low: float = 0.0, high: float = 10.0) -> float:
    return round(max(low, min(high, float(value))), 1)


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator <= 0 else max(0.0, min(1.0, float(numerator) / float(denominator)))


def _unique(values: list[Any]) -> list[Any]:
    return list(dict.fromkeys(value for value in values if value))


def _chunks_by_book(store: Store, packet: dict[str, Any]) -> dict[str, list[Any]]:
    book_ids: set[str] = set()
    for citation in packet.get("citations", []) or []:
        if isinstance(citation, dict) and citation.get("book_id"):
            book_ids.add(str(citation["book_id"]))
    selection = packet.get("selection", {}) or {}
    for book in selection.get("books", []) or []:
        if isinstance(book, dict) and book.get("book_id"):
            book_ids.add(str(book["book_id"]))
    for framework in packet.get("frameworks", []) or []:
        if isinstance(framework, dict) and framework.get("book_id"):
            book_ids.add(str(framework["book_id"]))
    return {book_id: store.get_chunks(book_id) for book_id in sorted(book_ids) if book_id}


def _validation_issues(store: Store, packet: dict[str, Any]) -> list[Any]:
    try:
        return validate_analysis_packet(packet, _chunks_by_book(store, packet))
    except Exception as exc:
        # Scoring must never make an analysis unreadable.  A validation crash
        # becomes a real error issue, so it lowers the score and stays visible
        # in diagnostics instead of being silently treated as "no problems".
        return [ValidationIssue("error", "validation_crash", f"Validation could not run: {exc}", "reading_eval")]


def auto_scores(store: Store, packet: dict[str, Any]) -> dict[str, float]:
    """Deterministic proxy scores from the packet's own artefacts.

    These are triage signals, not a substitute for a human or independent LLM
    judge.  The caller can override any dimension with a real judgment.
    """
    citations = [item for item in (packet.get("citations") or []) if isinstance(item, dict)]
    evidence = [item for item in (packet.get("evidence") or []) if isinstance(item, dict)]
    frameworks = [item for item in (packet.get("frameworks") or []) if isinstance(item, dict)]
    hypotheses = [item for item in (packet.get("hypotheses") or []) if isinstance(item, dict)]
    lenses = [str(item) for item in (packet.get("lenses") or []) if str(item)]
    issues = _validation_issues(store, packet)
    errors = [issue for issue in issues if getattr(issue, "severity", "") == "error"]
    warnings = [issue for issue in issues if getattr(issue, "severity", "") == "warning"]

    citation_books = _unique([str(item.get("book_id")) for item in citations if item.get("book_id")])
    citation_chunks = _unique([str(item.get("chunk_id")) for item in citations if item.get("chunk_id")])
    citation_ratio = _ratio(len(citations), len(evidence)) if evidence else (1.0 if citations else 0.0)
    chunk_ratio = _ratio(len(citation_chunks), len(citations)) if citations else 0.0
    quote_ok = _ratio(
        sum(1 for item in citations if len(str(item.get("quote", "")).strip()) >= 12),
        len(citations),
    )
    source_fidelity = 3.0 * citation_ratio + 4.0 * chunk_ratio + 3.0 * quote_ok
    source_fidelity -= min(6.0, 2.0 * len(errors))
    if str(packet.get("status", "draft")) != "complete":
        source_fidelity = min(source_fidelity, 8.0)

    covered_lenses: set[str] = set()
    for framework in frameworks:
        covered_lenses.update(str(item) for item in framework.get("lenses", []) if str(item))
    for hypothesis in hypotheses:
        if hypothesis.get("lens"):
            covered_lenses.add(str(hypothesis["lens"]))
    lens_coverage = _ratio(len(set(lenses).intersection(covered_lenses)), len(lenses)) if lenses else 1.0

    book_count = len(citation_books)
    framework_count = len(frameworks)
    retrieval_coverage = 4.0 * min(1.0, book_count / 2.0) + 3.0 * min(1.0, framework_count / 2.0) + 3.0 * lens_coverage
    if len(evidence) < 3:
        retrieval_coverage -= 1.0

    if frameworks:
        lens_match = _ratio(
            sum(1 for item in frameworks if not lenses or set(item.get("lenses", [])).intersection(lenses)),
            len(frameworks),
        )
        applicable = _ratio(sum(1 for item in frameworks if item.get("applicable_when")), len(frameworks))
        steps = _ratio(sum(1 for item in frameworks if item.get("steps")), len(frameworks))
        framework_fit = 4.0 * lens_match + 3.0 * applicable + 3.0 * steps
    else:
        framework_fit = 0.0

    if book_count <= 0:
        cross_book = 0.0
    elif book_count == 1:
        cross_book = 3.0
    elif book_count == 2:
        cross_book = 7.0
    else:
        cross_book = 10.0
    claim_books = _unique(
        str(item.get("book_id"))
        for item in (packet.get("claims") or [])
        if isinstance(item, dict) and item.get("book_id")
    )
    if len(claim_books) >= 2:
        cross_book = min(10.0, cross_book + 1.0)

    if len(lenses) <= 1:
        cross_lens = 7.0
    else:
        cross_lens = 10.0 * _ratio(len(set(lenses).intersection(covered_lenses)), len(lenses))

    conflicts = [item for item in (packet.get("cross_lens_conflicts") or []) if isinstance(item, dict)]
    if len(lenses) <= 1:
        conflict_handling = 7.0
    elif any(item.get("source") == "claim_graph" or item.get("claims") for item in conflicts):
        conflict_handling = 9.0
    elif conflicts:
        conflict_handling = 6.0
    else:
        conflict_handling = 2.0

    uncertainty = str(packet.get("uncertainty") or "").strip()
    conclusion = str(packet.get("conclusion") or "").strip()
    calibration = 0.0
    if uncertainty and not uncertainty.lower().startswith("draft"):
        calibration += 5.0
    elif uncertainty:
        calibration += 2.0
    if conclusion and not conclusion.lower().startswith("draft"):
        calibration += 3.0
    if str(packet.get("status", "draft")) == "complete":
        calibration += 2.0

    checks = [item for item in (packet.get("next_checks") or []) if str(item).strip()]
    actionability = 0.0 if not checks else (5.0 if len(checks) == 1 else 8.0)
    if conclusion and not conclusion.lower().startswith("draft"):
        actionability += 2.0

    if frameworks:
        failure_modes = _ratio(sum(1 for item in frameworks if item.get("failure_modes")), len(frameworks))
        counterexamples = _ratio(sum(1 for item in frameworks if item.get("counterexamples")), len(frameworks))
        failure_awareness = 5.0 * failure_modes + 5.0 * counterexamples
    else:
        failure_awareness = 0.0

    return {
        "source_fidelity": _clip(source_fidelity),
        "retrieval_coverage": _clip(retrieval_coverage),
        "framework_fit": _clip(framework_fit),
        "cross_book_synthesis": _clip(cross_book),
        "cross_lens_integration": _clip(cross_lens),
        "conflict_handling": _clip(conflict_handling),
        "calibration": _clip(calibration),
        "actionability": _clip(actionability),
        "failure_mode_awareness": _clip(failure_awareness),
    }


def _validate_scores(scores: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in scores.items():
        if key not in DIMENSION_BY_KEY:
            raise ValueError(f"unknown reading dimension: {key}; expected one of {', '.join(DIMENSION_BY_KEY)}")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"score for {key} must be a number between 0 and 10") from exc
        if not 0 <= number <= 10:
            raise ValueError(f"score for {key} must be between 0 and 10")
        result[key] = round(number, 1)
    return result


def evaluate_reading(
    store: Store,
    analysis_id: str,
    scores: dict[str, Any] | None = None,
    evaluator: str = "auto",
    note: str = "",
    error_labels: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score one analysis and persist the evaluation.

    `scores` overrides the deterministic proxies.  An override means the caller
    has actually judged that dimension (human or independent LLM judge); the
    remaining dimensions stay as explicit proxies.
    """
    packet = store.get_analysis(analysis_id)
    if not packet:
        raise ValueError(f"Unknown analysis_id: {analysis_id}")
    proxies = auto_scores(store, packet)
    overrides = _validate_scores(scores or {})
    values = {**proxies, **overrides}
    evaluator = (evaluator or "auto").strip() or "auto"
    if evaluator == "auto" and overrides:
        evaluator = "mixed"
    if evaluator == "auto":
        evaluator = "auto_proxy"

    weighted = {
        item["key"]: round(values[item["key"]] / 10.0 * float(item["weight"]), 2)
        for item in READING_DIMENSIONS
    }
    total = round(sum(weighted.values()), 2)
    diagnostics = {
        "status": packet.get("status", "draft"),
        "book_count": len(_unique([str(item.get("book_id")) for item in (packet.get("citations") or []) if item.get("book_id")])),
        "framework_count": len(packet.get("frameworks") or []),
        "citation_count": len(packet.get("citations") or []),
        "evidence_count": len(packet.get("evidence") or []),
        "claim_count": len(packet.get("claims") or []),
        "lens_count": len(packet.get("lenses") or []),
        "validation_error_count": sum(
            1 for issue in _validation_issues(store, packet) if getattr(issue, "severity", "") == "error"
        ),
        "validation_warning_count": sum(
            1 for issue in _validation_issues(store, packet) if getattr(issue, "severity", "") == "warning"
        ),
        "auto_proxy": True,
    }
    payload = {
        "evaluation_id": stable_id(
            "reading-eval",
            analysis_id,
            RUBRIC_VERSION,
            json.dumps(values, ensure_ascii=False, sort_keys=True),
            evaluator,
            note,
            utc_now(),
        ),
        "analysis_id": analysis_id,
        "created_at": utc_now(),
        "rubric_version": RUBRIC_VERSION,
        "evaluator": evaluator,
        "scores": values,
        "auto_proxy": proxies,
        "overrides": overrides,
        "weights": {item["key"]: item["weight"] for item in READING_DIMENSIONS},
        "weighted": weighted,
        "total": total,
        "note": note,
        "error_labels": list(error_labels or []),
        "diagnostics": diagnostics,
        "metadata": metadata or {},
    }
    store.save_reading_evaluation(payload)
    return payload


def evaluator_kind(evaluator: str) -> str:
    value = str(evaluator or "").strip().lower()
    if value.startswith("llm_judge"):
        return "llm_judge"
    if value.startswith("human"):
        return "human"
    if value.startswith("mixed"):
        return "mixed"
    if value in {"auto", "auto_proxy", ""}:
        return "auto_proxy"
    return "other"


def _proxy_calibration(evaluations: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare independent scores with the deterministic proxy.

    Positive deltas mean the independent judge was more generous than the
    proxy; negative deltas mean it was harsher.  Only dimensions that were
    actually overridden are counted.
    """
    deltas: dict[str, list[float]] = {}
    for evaluation in evaluations:
        overrides = evaluation.get("overrides") or {}
        proxy = evaluation.get("auto_proxy") or {}
        scores = evaluation.get("scores") or {}
        for key, value in overrides.items():
            if key not in proxy or key not in scores:
                continue
            deltas.setdefault(key, []).append(float(scores[key]) - float(proxy[key]))
    result: dict[str, Any] = {}
    for key, values in deltas.items():
        result[key] = {
            "n": len(values),
            "mean_delta": round(sum(values) / len(values), 2),
            "mean_abs_delta": round(sum(abs(value) for value in values) / len(values), 2),
            "min_delta": round(min(values), 1),
            "max_delta": round(max(values), 1),
        }
    return result


def reading_report(store: Store, limit: int = 500) -> dict[str, Any]:
    evaluations = store.list_reading_evaluations(limit=limit)
    if not evaluations:
        return {
            "rubric_version": RUBRIC_VERSION,
            "count": 0,
            "message": "No reading evaluations yet. Run `reading-eval --analysis <id>` after an answer is complete.",
            "dimensions": [],
            "low_dimensions": [],
            "next_actions": [],
            "error_label_counts": {},
            "evaluator_breakdown": {},
            "independent_count": 0,
            "proxy_calibration": {},
        }

    chronological = list(reversed(evaluations))
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for evaluation in chronological:
        by_kind.setdefault(evaluator_kind(str(evaluation.get("evaluator", ""))), []).append(evaluation)
    independent = [
        evaluation
        for evaluation in chronological
        if evaluator_kind(str(evaluation.get("evaluator", ""))) in {"llm_judge", "human", "mixed"}
    ]
    # Prefer real, independent judgments for the headline report.  If there are
    # none, fall back to proxies and label that fact explicitly.
    scored = independent or chronological
    basis = "independent" if independent else "auto_proxy"

    dimensions = []
    for item in READING_DIMENSIONS:
        key = item["key"]
        values = [float(evaluation.get("scores", {}).get(key, 0.0)) for evaluation in scored]
        dimensions.append(
            {
                "key": key,
                "label": item["label"],
                "weight": item["weight"],
                "mean": round(sum(values) / len(values), 2),
                "latest": values[-1],
                "min": min(values),
                "max": max(values),
            }
        )
    totals = [float(evaluation.get("total", 0.0)) for evaluation in scored]
    recent = totals[-5:]
    older = totals[-10:-5]
    trend = round(sum(recent) / len(recent) - sum(older) / len(older), 2) if older else 0.0
    bands = {"0-59": 0, "60-74": 0, "75-89": 0, "90-100": 0}
    for total in totals:
        if total < 60:
            bands["0-59"] += 1
        elif total < 75:
            bands["60-74"] += 1
        elif total < 90:
            bands["75-89"] += 1
        else:
            bands["90-100"] += 1
    labels: dict[str, int] = {}
    for evaluation in scored:
        for label in evaluation.get("error_labels", []):
            labels[label] = labels.get(label, 0) + 1

    evaluator_breakdown: dict[str, Any] = {}
    for kind, items in by_kind.items():
        kind_totals = [float(item.get("total", 0.0)) for item in items]
        evaluator_breakdown[kind] = {
            "count": len(items),
            "mean_total": round(sum(kind_totals) / len(kind_totals), 2),
            "latest_total": kind_totals[-1],
        }
    independent_totals = [float(item.get("total", 0.0)) for item in independent]
    return {
        "rubric_version": RUBRIC_VERSION,
        "count": len(evaluations),
        "basis": basis,
        "mean_total": round(sum(totals) / len(totals), 2),
        "latest_total": totals[-1],
        "trend_recent5_minus_previous5": trend,
        "score_bands": bands,
        "dimensions": dimensions,
        "low_dimensions": [item for item in dimensions if item["mean"] < 6.0],
        "next_actions": _next_actions(dimensions),
        "error_label_counts": dict(sorted(labels.items(), key=lambda pair: -pair[1])),
        "evaluator_breakdown": evaluator_breakdown,
        "independent_count": len(independent),
        "independent_mean_total": (
            round(sum(independent_totals) / len(independent_totals), 2) if independent_totals else None
        ),
        "proxy_calibration": _proxy_calibration(independent),
        "latest": evaluations[:10],
    }


def render_reading_report(report: dict[str, Any]) -> str:
    lines = ["# Reading effectiveness report", ""]
    lines.append(f"- Rubric: `{report.get('rubric_version', RUBRIC_VERSION)}`")
    lines.append(f"- Evaluations: {report.get('count', 0)}")
    if not report.get("count"):
        lines.append("")
        lines.append(str(report.get("message", "No evaluations yet.")))
        return "\n".join(lines)
    lines.append(f"- Mean total: {report.get('mean_total')}/100")
    lines.append(f"- Latest total: {report.get('latest_total')}/100")
    lines.append(f"- Recent trend: {report.get('trend_recent5_minus_previous5'):+}")
    lines.append("")
    lines.append("## Dimensions")
    lines.append("")
    lines.append("| Dimension | Weight | Mean | Latest | Min | Max |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for item in report.get("dimensions", []):
        lines.append(
            f"| {item['label']} (`{item['key']}`) | {item['weight']} | {item['mean']} | "
            f"{item['latest']} | {item['min']} | {item['max']} |"
        )
    lines.append("")
    lines.append("## Low dimensions")
    lines.append("")
    low = report.get("low_dimensions", [])
    if not low:
        lines.append("_None below 6.0._")
    for item in low:
        lines.append(f"- {item['label']} (`{item['key']}`): mean {item['mean']}/10")
    lines.append("")
    lines.append("## Next practice")
    lines.append("")
    actions = report.get("next_actions", [])
    if not actions:
        lines.append("_No dimension is below 6.0; keep collecting evaluations._")
    for item in actions:
        lines.append(f"- **{item['label']}** ({item['mean']}/10): {item['action']}")
    lines.append("")
    lines.append("## Error labels")
    lines.append("")
    labels = report.get("error_label_counts", {})
    if not labels:
        lines.append("_None recorded._")
    for label, count in labels.items():
        lines.append(f"- `{label}`: {count}")
    lines.append("")
    lines.append("## Recent evaluations")
    lines.append("")
    for item in report.get("latest", []):
        lines.append(
            f"- `{item.get('evaluation_id', '')}` analysis `{item.get('analysis_id', '')}`: "
            f"{item.get('total', 0)}/100 ({item.get('evaluator', '')})"
        )
        if item.get("note"):
            lines.append(f"  - {item['note']}")
    return "\n".join(lines)
