from bookcompiler.parsing import parse_book


def test_parse_markdown_splits_chapters_and_keeps_page_metadata(tmp_path):
    book_path = tmp_path / "book.md"
    book_path.write_text(
        "# Test Book\n\n"
        "## Chapter 1: First\n\n"
        "Alpha beta gamma. This is the first chapter.\n\n"
        "## Chapter 2: Second\n\n"
        "Delta epsilon zeta. This is the second chapter.\n",
        encoding="utf-8",
    )

    parsed = parse_book(book_path, title="Test Book", author="Tester", disciplines=["economics"])

    assert parsed.title == "Test Book"
    assert len(parsed.chapters) == 2
    assert parsed.chapters[0].title == "Chapter 1: First"
    assert "first chapter" in parsed.chapters[0].text
    assert parsed.chapters[1].title == "Chapter 2: Second"
    assert parsed.chunks
    assert all(chunk.book_id == parsed.book_id for chunk in parsed.chunks)
