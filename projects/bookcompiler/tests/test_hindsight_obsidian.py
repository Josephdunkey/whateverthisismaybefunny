from __future__ import annotations

import json
from pathlib import Path

from bookcompiler import hindsight_obsidian as ho


def _memory(memory_id="mem-0001", text="???????????", state="valid", fact_type="world"):
    return {
        "id": memory_id,
        "text": text,
        "context": "BookCompiler test",
        "fact_type": fact_type,
        "state": state,
        "tags": ["preference"],
        "entities": [{"name": "??"}],
        "document_id": "doc-1",
        "date": "2026-10-18",
    }


def _setup(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault_root = vault
    state = tmp_path / "state.json"
    monkeypatch.setattr(ho, "vault_path", lambda vault="": Path(vault) if vault else vault_root)
    monkeypatch.setattr(ho, "state_path", lambda: state)
    monkeypatch.setattr(ho, "enabled", lambda: True)
    monkeypatch.setattr(ho, "bank_id", lambda: "bookcompiler")
    return vault, state


def test_export_writes_editable_and_read_only_notes(tmp_path, monkeypatch):
    vault, state = _setup(tmp_path, monkeypatch)
    memories = [
        _memory("11111111-1111-1111-1111-111111111111", "???????????", "valid", "world"),
        _memory("22222222-2222-2222-2222-222222222222", "???????????????", "valid", "observation"),
    ]
    monkeypatch.setattr(ho, "list_memories", lambda **kwargs: {"ok": True, "items": memories, "total": len(memories)})

    result = ho.export_memories(subdir="Hindsight")

    assert result["ok"] is True
    root = vault / "Hindsight"
    files = list(root.rglob("*.md"))
    assert len(files) == 3  # two memories + README
    assert result["counts"]["written"] == 2
    assert (root / "Memories" / "world").exists()
    assert (root / "Observations" / "observation").exists()
    assert state.is_file()


def test_export_preserves_user_edit_and_writes_conflict(tmp_path, monkeypatch):
    vault, _ = _setup(tmp_path, monkeypatch)
    memory = _memory("33333333-3333-3333-3333-333333333333")
    monkeypatch.setattr(ho, "list_memories", lambda **kwargs: {"ok": True, "items": [memory], "total": 1})
    ho.export_memories(subdir="Hindsight")
    path = next((vault / "Hindsight" / "Memories").rglob("*.md"))
    text = path.read_text(encoding="utf-8")
    edited = text.replace("???????????", "???????????????")
    path.write_text(edited, encoding="utf-8")

    changed = dict(memory)
    changed["text"] = "?????????????????"
    monkeypatch.setattr(ho, "list_memories", lambda **kwargs: {"ok": True, "items": [changed], "total": 1})
    result = ho.export_memories(subdir="Hindsight")

    assert result["counts"]["preserved_user_edits"] == 1
    assert result["counts"]["conflicts"] == 1
    assert "???????????????" in path.read_text(encoding="utf-8")
    assert list(path.parent.glob("*.conflict-*.md"))


def test_import_pushes_user_edit_to_hindsight(tmp_path, monkeypatch):
    vault, _ = _setup(tmp_path, monkeypatch)
    memory = _memory("44444444-4444-4444-4444-444444444444")
    monkeypatch.setattr(ho, "list_memories", lambda **kwargs: {"ok": True, "items": [memory], "total": 1})
    ho.export_memories(subdir="Hindsight")
    path = next((vault / "Hindsight" / "Memories").rglob("*.md"))
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("???????????", "??????????????"), encoding="utf-8")

    calls = []

    def fake_update(memory_id, **kwargs):
        calls.append((memory_id, kwargs))
        return {"ok": True, "body": {}}

    monkeypatch.setattr(ho, "update_memory", fake_update)
    result = ho.import_memories(subdir="Hindsight")

    assert result["updated"] == 1
    assert calls
    assert calls[0][0] == memory["id"]
    assert calls[0][1]["text"] == "??????????????"


def test_observation_edit_is_skipped(tmp_path, monkeypatch):
    vault, _ = _setup(tmp_path, monkeypatch)
    memory = _memory("55555555-5555-5555-5555-555555555555", "?????", "valid", "observation")
    monkeypatch.setattr(ho, "list_memories", lambda **kwargs: {"ok": True, "items": [memory], "total": 1})
    ho.export_memories(subdir="Hindsight")
    path = next((vault / "Hindsight" / "Observations").rglob("*.md"))
    path.write_text(path.read_text(encoding="utf-8").replace("?????", "??????"), encoding="utf-8")

    monkeypatch.setattr(ho, "update_memory", lambda *a, **k: {"ok": True})
    result = ho.import_memories(subdir="Hindsight")
    assert result["read_only_skipped"] == 1
    assert result["updated"] == 0


def test_inbox_creates_memory_once(tmp_path, monkeypatch):
    vault, _ = _setup(tmp_path, monkeypatch)
    inbox = vault / "Hindsight Inbox"
    inbox.mkdir(parents=True)
    (inbox / "new.md").write_text("---\ntags: [finance, preference]\n---\n\n???????????????\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(ho, "retain", lambda *a, **k: calls.append((a, k)) or {"ok": True})
    first = ho.import_inbox(inbox="Hindsight Inbox")
    second = ho.import_inbox(inbox="Hindsight Inbox")
    assert first["created"] == 1
    assert second["unchanged"] == 1
    assert len(calls) == 1
