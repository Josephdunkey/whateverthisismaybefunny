from pathlib import Path

from bookcompiler.claims import extract_claims
from bookcompiler.parsing import parse_book
from bookcompiler.store import Store


def test_english_claims_are_extracted_with_quotes(tmp_path):
    path = tmp_path / "english.md"
    path.write_text(
        "# Debt Crises\n\n## Chapter 1\n\n"
        "Loose lending standards lead to more debt and asset bubbles. "
        "A central bank requires credibility to reduce inflation. "
        "High leverage constrains growth and increases fragility.\n",
        encoding="utf-8",
    )
    store = Store(tmp_path / "library.db")
    parsed = parse_book(path, title="Debt Crises", author="Tester", disciplines=["economics"])
    store.add_book(parsed)

    claims = extract_claims(store, parsed.book_id)

    assert claims
    assert any(item["predicate"] == "causes" for item in claims)
    assert any(item["predicate"] == "requires" for item in claims)
    assert all(item["quote"] for item in claims)
    assert all(item["chunk_id"] for item in claims)
