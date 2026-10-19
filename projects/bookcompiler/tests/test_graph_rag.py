from __future__ import annotations

from pathlib import Path

from bookcompiler.graph_rag import build_graph, fused_search_report, graph_status, query_graph
from bookcompiler.parsing import parse_book
from bookcompiler.store import Store
from tests.helpers import compile_verified


def _graph_store(tmp_path):
    parsed = parse_book(
        Path("examples/sample_book.md"),
        title="Policy Shocks",
        author="Tester",
        disciplines=["economics", "politics", "law"],
    )
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    return store


def test_graph_build_and_query_returns_chunks(tmp_path):
    store = _graph_store(tmp_path)
    stats = build_graph(store)
    assert stats["nodes"] > 0
    assert stats["edges"] > 0
    assert stats["communities"] >= 1
    status = graph_status(store)
    assert status["available"] is True
    assert status["stale"] is False
    result = query_graph(store, "bank legal authority", limit=5)
    assert result["available"] is True
    assert result["items"]
    assert all(item["source"] == "graph" for item in result["items"])


def test_fused_search_has_both_channels_and_graph_failure_falls_back(tmp_path):
    store = _graph_store(tmp_path)
    build_graph(store)
    report = fused_search_report(store, "bank legal authority", limit=5)
    assert report["channels"]["hybrid"]
    assert report["channels"]["graph"]
    assert report["channels"]["fused"]
    assert any("graph" in item["channels"] for item in report["items"])

    from bookcompiler.graph_rag import graph_path_for

    graph_path_for(store).unlink()
    fallback = fused_search_report(store, "bank legal authority", limit=5)
    assert fallback["channels"]["hybrid"]
    assert fallback["graph"]["available"] is False
    assert fallback["items"]