from __future__ import annotations

from pathlib import Path

from bookcompiler.analysis import create_analysis
from bookcompiler.modes import build_proposal
from bookcompiler.obsidian_sync import (
    grade_review,
    list_due_reviews,
    list_reader_notes,
    obsidian_status,
    sync_obsidian,
)
from bookcompiler.parsing import parse_book
from bookcompiler.store import Store
from tests.helpers import compile_verified


def _store_with_book(tmp_path):
    parsed = parse_book(
        Path("examples/sample_book.md"),
        title="Policy Shocks",
        author="Tester",
        disciplines=["economics", "politics", "law"],
    )
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    return store, parsed


def test_inbox_import_is_idempotent_targeted_and_reviewable(tmp_path):
    store, parsed = _store_with_book(tmp_path)
    vault = tmp_path / "vault"
    inbox = vault / "BookCompiler Inbox"
    inbox.mkdir(parents=True)
    note = inbox / "monetary.md"
    note.write_text(
        f"""---
note_id: note-001
target_type: book
target_id: {parsed.book_id}
title: My monetary note
tags: [monetary-policy, doubt]
rating: 4
mastery: 0.3
review_due: 2020-01-01
---

Transmission may be weaker than the book claims. [[Books/Policy Shocks]]
""",
        encoding="utf-8",
    )
    first = sync_obsidian(store, vault, direction="import")
    assert first["import"]["created"] == 1
    second = sync_obsidian(store, vault, direction="import")
    assert second["import"]["unchanged"] == 1
    notes = list_reader_notes(store, status="active")
    assert notes[0]["note_id"] == "note-001"
    assert notes[0]["tags"] == ["monetary-policy", "doubt"]
    due = list_due_reviews(store)
    assert due
    graded = grade_review(store, due[0]["item_id"], 5)
    assert graded["mastery"] > 0.3
    assert obsidian_status(store)["notes"]["active"] == 1


def test_orphan_and_missing_are_marked_not_destroyed(tmp_path):
    store, _ = _store_with_book(tmp_path)
    vault = tmp_path / "vault"
    inbox = vault / "BookCompiler Inbox"
    inbox.mkdir(parents=True)
    orphan = inbox / "orphan.md"
    orphan.write_text("---\ntarget_type: book\ntarget_id: missing-book\n---\n\nDoubt.\n", encoding="utf-8")
    result = sync_obsidian(store, vault, direction="import")
    assert result["import"]["orphaned"] == 1
    assert list_reader_notes(store, status="orphaned")[0]["path"].endswith("orphan.md")
    orphan.unlink()
    result = sync_obsidian(store, vault, direction="import", prune=False)
    assert result["import"]["missing"] == 1
    assert list_reader_notes(store, status="missing")[0]["path"].endswith("orphan.md")


def test_reader_notes_are_memory_not_citations(tmp_path):
    store, parsed = _store_with_book(tmp_path)
    vault = tmp_path / "vault"
    inbox = vault / "BookCompiler Inbox"
    inbox.mkdir(parents=True)
    (inbox / "note.md").write_text(
        f"---\ntarget_type: book\ntarget_id: {parsed.book_id}\ntitle: Reserve requirement doubt\n---\n\n"
        "My own doubt: banks may hoard reserves.\n",
        encoding="utf-8",
    )
    sync_obsidian(store, vault, direction="import")
    proposal = build_proposal(store, "auto", "Central bank cuts reserve requirements", ["economics", "politics", "law"])
    packet = create_analysis(
        store,
        "Central bank cuts reserve requirements",
        ["economics", "politics", "law"],
        proposal,
        "auto",
    )
    assert packet.reader_notes
    assert packet.reader_notes[0]["kind"] == "reader_note"
    citation_blob = repr(packet.citations)
    assert "banks may hoard reserves" not in citation_blob
    assert any(stage["role"] == "reader" for stage in packet.orchestration["stages"])