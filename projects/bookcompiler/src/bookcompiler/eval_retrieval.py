"""Deterministic retrieval evaluation for lexical / hybrid / hybrid+rerank.

This is a small, transparent benchmark: each case names terms that must appear
in a retrieved passage.  It is not a substitute for blind quality judging, but
it catches regressions that a structural replay cannot see.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .retrieval import hybrid_search
from .store import Store
from .utils import normalize_text

DEFAULT_CASES: list[dict[str, Any]] = [
    {"case_id": "rrr-credit", "expected_book_ids": ["976b3c244642d321"], "query": "降准是否必然导致银行信贷扩张", "expected_terms": ["存款准备金率", "信贷", "基础货币"]},
    {"case_id": "cb-balance-sheet", "expected_book_ids": ["976b3c244642d321"], "query": "中央银行资产负债表如何影响基础货币", "expected_terms": ["资产负债表", "基础货币"]},
    {"case_id": "land-finance", "expected_book_ids": ["24617d60273da367"], "query": "土地出让收入与地方财政的关系", "expected_terms": ["土地出让", "地方财政"]},
    {"case_id": "tax-sharing", "expected_book_ids": ["24617d60273da367"], "query": "分税制改革如何改变地方政府行为", "expected_terms": ["分税制", "地方政府"]},
    {"case_id": "shadow-banking", "expected_book_ids": ["976b3c244642d321", "24617d60273da367"], "query": "影子银行与银行监管", "expected_terms": ["影子银行", "监管"]},
    {"case_id": "money-endogenous", "expected_book_ids": ["976b3c244642d321"], "query": "货币供给是内生还是外生", "expected_terms": ["内生", "货币供给"]},
    {"case_id": "fiscal-decentralization", "expected_book_ids": ["24617d60273da367"], "query": "财政分权与经济增长", "expected_terms": ["财政分权", "经济增长"]},
    {"case_id": "lgfv-debt", "expected_book_ids": ["24617d60273da367"], "query": "地方政府融资平台债务风险", "expected_terms": ["融资平台", "债务"]},
    {"case_id": "rule-of-law", "expected_book_ids": ["03576cf3e546ced0"], "query": "依法治国与党的领导的关系", "expected_terms": ["依法治国", "党的领导"]},
    {"case_id": "minsky", "expected_book_ids": ["a7086a05970476d8"], "query": "明斯基的金融不稳定假说", "expected_terms": ["明斯基", "不稳定"]},
    {"case_id": "liquidity", "expected_book_ids": ["976b3c244642d321"], "query": "银行体系流动性短缺与存款准备金", "expected_terms": ["流动性", "准备金"]},
    {"case_id": "npc", "expected_book_ids": ["03576cf3e546ced0"], "query": "人民代表大会制度与当代中国政治", "expected_terms": ["人民代表大会", "人大"]},
]


def load_cases(path: str | Path | None = None) -> list[dict[str, Any]]:
    if not path:
        return list(DEFAULT_CASES)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("cases", [])
    if not isinstance(data, list):
        raise ValueError("evaluation file must contain a list of cases")
    return data


def _contains(hit: dict[str, Any], terms: list[str]) -> bool:
    text = normalize_text(str(hit.get("text", ""))).lower()
    return any(normalize_text(str(term)).lower() in text for term in terms if str(term).strip())


def _contains_all(hit: dict[str, Any], terms: list[str]) -> bool:
    """Stricter check: every required term must appear in the same passage."""
    text = normalize_text(str(hit.get("text", ""))).lower()
    required = [normalize_text(str(term)).lower() for term in terms if str(term).strip()]
    return bool(required) and all(term in text for term in required)


def _run_mode(store: Store, cases: list[dict[str, Any]], mode: str, k: int, book_ids: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for case in cases:
        query = str(case.get("query", ""))
        terms = [str(term) for term in case.get("expected_terms", [])]
        expected_books = set(case.get("expected_book_ids", []))
        case_started = time.perf_counter()
        if mode == "lexical":
            hits = hybrid_search(store, query, book_ids=book_ids, limit=k, mode="lexical", rerank=False)
        elif mode == "hybrid":
            hits = hybrid_search(store, query, book_ids=book_ids, limit=k, mode="hybrid", rerank=False)
        else:
            hits = hybrid_search(store, query, book_ids=book_ids, limit=k, mode="hybrid", rerank=True)
        rank = next((index + 1 for index, hit in enumerate(hits) if _contains(hit, terms)), None)
        strict_rank = next((index + 1 for index, hit in enumerate(hits) if _contains_all(hit, terms)), None)
        book_rank = next(
            (index + 1 for index, hit in enumerate(hits) if hit.get("book_id") in expected_books),
            None,
        ) if expected_books else None
        results.append(
            {
                "case_id": case.get("case_id", query[:20]),
                "query": query,
                "hit": rank is not None,
                "rank": rank,
                "mrr": round(1.0 / rank, 4) if rank else 0.0,
                "strict_hit": strict_rank is not None,
                "strict_rank": strict_rank,
                "strict_mrr": round(1.0 / strict_rank, 4) if strict_rank else 0.0,
                "book_hit": book_rank is not None if expected_books else None,
                "book_rank": book_rank,
                "latency_ms": round((time.perf_counter() - case_started) * 1000, 1),
                "reranked": bool((hits[0].get("retrieval") or {}).get("rerank", {}).get("reranked")) if hits else False,
                "top": [
                    {
                        "book_id": hit.get("book_id"),
                        "chunk_id": hit.get("chunk_id"),
                        "page": hit.get("page_start"),
                        "score": hit.get("score"),
                    }
                    for hit in hits[:3]
                ],
            }
        )
    total = len(results)
    book_cases = [item for item in results if item["book_hit"] is not None]
    return {
        "mode": mode,
        "k": k,
        "case_count": total,
        "hit_at_k": round(sum(1 for item in results if item["hit"]) / total, 4) if total else 0.0,
        "mrr": round(sum(float(item["mrr"]) for item in results) / total, 4) if total else 0.0,
        "strict_hit_at_k": round(sum(1 for item in results if item["strict_hit"]) / total, 4) if total else 0.0,
        "strict_mrr": round(sum(float(item["strict_mrr"]) for item in results) / total, 4) if total else 0.0,
        "book_hit_at_k": round(sum(1 for item in book_cases if item["book_hit"]) / len(book_cases), 4) if book_cases else None,
        "mean_latency_ms": round((time.perf_counter() - started) * 1000 / total, 1) if total else 0.0,
        "cases": results,
    }


def evaluate(store: Store, cases: list[dict[str, Any]] | None = None, k: int = 8) -> dict[str, Any]:
    cases = cases or list(DEFAULT_CASES)
    learned = sorted(store.learned_book_ids())
    report = {
        "case_count": len(cases),
        "learned_book_ids": learned,
        "modes": {},
        "note": (
            "hit@k uses expected_terms supplied per case; it measures whether a passage "
            "containing any required term is retrieved. strict_hit@k requires every term "
            "in the same passage. Neither metric proves an answer is correct."
        ),
    }
    for mode in ("lexical", "hybrid", "hybrid+rerank"):
        report["modes"][mode] = _run_mode(store, cases, mode, k, learned)
    return report

def quick_hybrid_metrics(store: Store, k: int = 5, cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Fast, deterministic metrics for the evolution shadow/canary gate.

    This intentionally uses hybrid retrieval without the cross-encoder so the
    gate stays cheap and comparable before and after a config patch.
    """
    cases = cases or list(DEFAULT_CASES)
    learned = sorted(store.learned_book_ids())
    hits = 0
    reciprocal = 0.0
    books: set[str] = set()
    for case in cases:
        query = str(case.get("query", ""))
        terms = [str(term) for term in case.get("expected_terms", [])]
        results = hybrid_search(store, query, book_ids=learned, limit=k, mode="hybrid", rerank=False)
        books.update(str(item.get("book_id", "")) for item in results)
        rank = next((index + 1 for index, item in enumerate(results) if _contains(item, terms)), None)
        if rank:
            hits += 1
            reciprocal += 1.0 / rank
    total = len(cases)
    return {
        "case_count": total,
        "hit_at_k": round(hits / total, 4) if total else 0.0,
        "mrr": round(reciprocal / total, 4) if total else 0.0,
        "book_coverage": round(len(books) / len(learned), 4) if learned else 0.0,
        "learned_books": len(learned),
    }
