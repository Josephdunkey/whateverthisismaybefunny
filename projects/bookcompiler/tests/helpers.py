from __future__ import annotations

from bookcompiler.compiler import compile_book
from bookcompiler.store import Store


def compile_verified(store: Store, book_id: str):
    """Compile heuristically, then simulate an agent-reviewed card.

    Tests that exercise selection/analysis need a learned book.  A heuristic
    compile is deliberately not learned after the status fix, so this helper
    marks the card verified after inspecting the heuristic output.
    """
    result = compile_book(store, book_id)
    card = store.get_book_card(book_id) or {}
    card["status"] = "verified"
    card["confidence"] = "high"
    store.save_book_card(book_id, card)
    return result


def mark_verified(db_path, book_id: str) -> None:
    store = Store(db_path)
    try:
        card = store.get_book_card(book_id) or {}
        card["status"] = "verified"
        card["confidence"] = "high"
        store.save_book_card(book_id, card)
    finally:
        store.close()
