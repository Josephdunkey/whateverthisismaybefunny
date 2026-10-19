from pathlib import Path

from bookcompiler.parsing import parse_book
from bookcompiler.store import Store


def test_store_indexes_book_and_finds_relevant_chunk(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester")
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)

    results = store.search_chunks("legal authority jurisdiction", limit=5)

    assert results
    assert any("Legal Authority" in item["chapter_title"] for item in results)
    assert any("statutory authority" in item["text"] for item in results)
    assert store.get_book(parsed.book_id)["title"] == "Policy Shocks"