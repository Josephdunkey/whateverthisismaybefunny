from pathlib import Path

from bookcompiler.models import Chunk
from bookcompiler.parsing import parse_book
from bookcompiler.validation import _validate_citation, find_quote


def test_find_quote_requires_exact_source_text():
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester")

    found = find_quote("A regulator must act within statutory authority.", parsed.chunks)
    fake = find_quote("A regulator may ignore statutory authority whenever markets are stressed.", parsed.chunks)

    assert found is not None
    assert found.chapter_title == "Chapter 3: Legal Authority and Risk"
    assert fake is None

def test_duplicate_quote_prefers_the_cited_chunk():
    quote = "Institutional credibility depends on a credible fiscal backstop."
    chunks = [
        Chunk("c1", "b1", 0, "Chapter 1", 0, "Intro text. " + quote + " More text.", page_start=100, page_end=100),
        Chunk("c2", "b1", 1, "Chapter 2", 0, "Again. " + quote + " End.", page_start=200, page_end=200),
    ]

    issues = _validate_citation(
        {"chunk_id": "c2", "chapter": "Chapter 2", "page": 200, "quote": quote},
        chunks,
        "test",
    )

    assert [issue for issue in issues if issue.severity != "info"] == []
