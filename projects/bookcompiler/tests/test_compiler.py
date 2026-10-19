from pathlib import Path

from bookcompiler.compiler import compile_book
from bookcompiler.parsing import parse_book
from bookcompiler.store import Store


def test_compile_book_produces_cited_frameworks(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)

    result = compile_book(store, parsed.book_id)

    assert result.book_card.title == "Policy Shocks"
    assert result.book_card.one_line_thesis
    assert result.frameworks
    assert all(framework.citations for framework in result.frameworks)
    assert all(issue.severity != "error" for issue in result.issues)
    assert store.get_book_card(parsed.book_id)["title"] == "Policy Shocks"
    assert store.list_frameworks(book_ids=[parsed.book_id])
def _valid_patch(parsed):
    chunks = parsed.chunks
    quotes = [chunk.text.split(".")[0] + "." for chunk in chunks]
    return {
        "book_card": {
            "book_id": parsed.book_id,
            "title": parsed.title,
            "author": parsed.author,
            "one_line_thesis": "Policy shocks change prices, coalitions, and legal authority.",
            "core_questions": ["Who bears the cost?", "Who can block implementation?"],
            "key_concepts": ["incentives", "coalition", "jurisdiction"],
            "assumptions": ["Institutions respond to incentives."],
            "limitations": ["The book is a sample."],
            "best_for": ["policy shock analysis"],
            "not_for": ["forecasting"],
            "chapter_coverage": [
                {
                    "chapter": chunk.chapter_title,
                    "summary": chunk.text[:80],
                    "citation": {
                        "book_id": parsed.book_id,
                        "quote": quote,
                        "chunk_id": chunk.chunk_id,
                        "chapter": chunk.chapter_title,
                        "page": chunk.page_start,
                    },
                }
                for chunk, quote in zip(chunks, quotes)
            ],
            "lenses": ["economics", "politics", "law"],
            "confidence": "high",
            "status": "verified",
        },
        "frameworks": [
            {
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
                        "quote": quotes[0],
                        "chunk_id": chunks[0].chunk_id,
                        "chapter": chunks[0].chapter_title,
                        "page": chunks[0].page_start,
                    }
                ],
                "related_frameworks": [],
                "confidence": "high",
                "status": "verified",
            }
        ],
    }


def test_compile_accepts_agent_patch_with_exact_citations(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)

    result = compile_book(store, parsed.book_id, patch=_valid_patch(parsed))

    assert not [issue for issue in result.issues if issue.severity == "error"]
    assert result.book_card.status == "verified"
    assert result.frameworks[0].status == "verified"
    assert store.get_book_card(parsed.book_id)["confidence"] == "high"


def test_compile_rejects_fabricated_quote_without_saving(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    patch = _valid_patch(parsed)
    patch["frameworks"][0]["citations"][0]["quote"] = "The central bank may ignore all statutory limits during a crisis."

    result = compile_book(store, parsed.book_id, patch=patch)

    assert any(issue.code == "unsupported_quote" for issue in result.issues)
    assert result.frameworks == []
    assert store.get_book_card(parsed.book_id) is None


def test_compile_rejects_book_card_with_fabricated_chapter_citation(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    patch = _valid_patch(parsed)
    patch["book_card"]["chapter_coverage"][0]["citation"]["quote"] = "This sentence was never printed in the book."

    result = compile_book(store, parsed.book_id, patch=patch)

    assert any(issue.code == "unsupported_quote" for issue in result.issues)
    assert store.get_book_card(parsed.book_id) is None