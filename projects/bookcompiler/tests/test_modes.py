from pathlib import Path

from tests.helpers import compile_verified
from bookcompiler.modes import build_proposal, resolve_proposal
from bookcompiler.parsing import parse_book
from bookcompiler.store import Store


def _seed(store: Store, tmp_path: Path) -> None:
    books = {
        "econ.md": ("Economics of Policy", ["economics"], "When prices change, incentives change. Firms delay investment when the cost of capital rises."),
        "politics.md": ("Politics of Reform", ["politics"], "A government must build a coalition. Veto players can block implementation."),
        "law.md": ("Law of Regulation", ["law"], "A regulator must act within statutory authority. Courts may stay a rule that exceeds jurisdiction."),
    }
    for name, (title, disciplines, body) in books.items():
        path = tmp_path / name
        path.write_text(f"# {title}\n\n## Chapter 1\n\n{body}\n", encoding="utf-8")
        parsed = parse_book(path, title=title, author="Tester", disciplines=disciplines)
        store.add_book(parsed)
        compile_verified(store, parsed.book_id)


def test_direction_mode_requires_confirmation_and_offers_consent_options(tmp_path):
    store = Store(tmp_path / "library.db")
    _seed(store, tmp_path)

    proposal = build_proposal(
        store,
        mode="direction",
        query="new regulation of bank lending",
        lenses=["economics", "politics", "law"],
        direction="legal regulation and statutory authority",
    )

    assert proposal.requires_confirmation is True
    assert proposal.options == ["specified", "specified+recommended", "recommended"]
    assert proposal.specified_books
    assert proposal.recommended_books
    assert "law" in {book["disciplines"][0] for book in proposal.specified_books if book["disciplines"]}

    resolved = resolve_proposal(proposal, "specified+recommended")
    assert len(resolved["books"]) >= len(proposal.specified_books)


def test_auto_mode_does_not_ask_for_confirmation(tmp_path):
    store = Store(tmp_path / "library.db")
    _seed(store, tmp_path)

    proposal = build_proposal(
        store,
        mode="auto",
        query="bank lending regulation",
        lenses=["economics", "politics", "law"],
    )

    assert proposal.requires_confirmation is False
    assert proposal.recommended_books
from bookcompiler.compiler import compile_book


def test_proposal_exposes_framework_choices_and_resolves_them(tmp_path):
    store = Store(tmp_path / "library.db")
    _seed(store, tmp_path)
    for book in store.list_books():
        compile_verified(store, book["book_id"])

    proposal = build_proposal(
        store,
        mode="direction",
        query="bank lending regulation",
        lenses=["economics", "politics", "law"],
        direction="legal regulation and statutory authority",
    )

    assert proposal.specified_frameworks
    assert all(item["framework_id"] for item in proposal.specified_frameworks)
    resolved = resolve_proposal(proposal, "specified")
    assert resolved["frameworks"]
    assert {item["framework_id"] for item in resolved["frameworks"]} == {
        item["framework_id"] for item in proposal.specified_frameworks
    }


def test_books_mode_honors_explicit_framework_ids(tmp_path):
    store = Store(tmp_path / "library.db")
    _seed(store, tmp_path)
    economics = next(book for book in store.list_books() if "Economics" in book["title"])
    compile_verified(store, economics["book_id"])
    framework = store.list_frameworks(book_ids=[economics["book_id"]])[0]

    proposal = build_proposal(
        store,
        mode="books",
        query="bank lending regulation",
        lenses=["economics", "politics", "law"],
        book_ids=[economics["book_id"]],
        framework_ids=[framework["framework_id"]],
    )

    assert proposal.requires_confirmation is True
    assert proposal.specified_frameworks[0]["framework_id"] == framework["framework_id"]
    assert proposal.specified_books[0]["book_id"] == economics["book_id"]
    assert proposal.recommended_books

def test_direction_mode_rejects_empty_direction(tmp_path):
    store = Store(tmp_path / "library.db")
    _seed(store, tmp_path)
    try:
        build_proposal(store, mode="direction", query="bank lending", lenses=["economics"], direction="   ")
    except ValueError as exc:
        assert "direction" in str(exc)
    else:
        raise AssertionError("direction mode should require a direction")


def test_books_mode_rejects_empty_selection(tmp_path):
    store = Store(tmp_path / "library.db")
    _seed(store, tmp_path)
    try:
        build_proposal(store, mode="books", query="bank lending", lenses=["economics"], book_ids=[], framework_ids=[])
    except ValueError as exc:
        assert "book_id" in str(exc) or "framework_id" in str(exc)
    else:
        raise AssertionError("books mode should require an explicit selection")
