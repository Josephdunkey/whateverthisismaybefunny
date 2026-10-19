"""Two-way Obsidian bridge: generated notes out, reader notes and review state in.

The generated ``<vault>/<subdir>`` folder is a protected export owned by
BookCompiler; later exports do not silently overwrite user edits.  User annotations live in a separate inbox folder and are
imported into SQLite as *reader notes*.  They can influence analysis as memory
context, but they are never treated as source citations.  Import is idempotent
by content hash, never overwrites a generated note, and marks deleted inbox
notes as ``missing`` instead of deleting their history.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import load_env, project_root
from .models import utc_now
from .obsidian import export_vault
from .store import Store, query_terms
from .utils import stable_id

_DEFAULT_VAULT = Path.home() / "Documents" / "Obsidian Vault"


def configured_vault(vault: str | Path = "") -> Path:
    """Resolve the Obsidian vault from an argument or environment.

    Keeping this in one place makes the GUI, CLI and .bat launchers behave the
    same.  The path is not created here; callers decide whether writing is safe.
    """
    load_env()
    if str(vault or "").strip():
        return Path(str(vault)).expanduser().resolve()
    import os

    for key in ("BOOKCOMPILER_OBSIDIAN_VAULT", "OBSIDIAN_VAULT"):
        value = os.environ.get(key, "").strip()
        if value:
            return Path(value).expanduser().resolve()
    return _DEFAULT_VAULT.resolve()


def configured_subdir() -> str:
    load_env()
    import os

    return os.environ.get("BOOKCOMPILER_OBSIDIAN_SUBDIR", "BookCompiler").strip() or "BookCompiler"


def configured_inbox() -> str:
    load_env()
    import os

    return os.environ.get("BOOKCOMPILER_OBSIDIAN_INBOX", "BookCompiler Inbox").strip() or "BookCompiler Inbox"


ALLOWED_TARGETS = {"book", "framework", "claim", "entity", "analysis"}
TARGET_FOLDERS = {
    "book": "Books",
    "framework": "Frameworks",
    "claim": "Claims",
    "entity": "Entities",
    "analysis": "Analyses",
}
_ID_FIELDS = {
    "book": "book_id",
    "framework": "framework_id",
    "claim": "claim_id",
    "entity": "entity_id",
    "analysis": "analysis_id",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS obsidian_notes (
    note_id TEXT PRIMARY KEY,
    vault TEXT NOT NULL,
    path TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '[]',
    rating REAL,
    mastery REAL,
    review_due TEXT NOT NULL DEFAULT '',
    frontmatter TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE(vault, path)
);
CREATE INDEX IF NOT EXISTS idx_obsidian_notes_target ON obsidian_notes(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_obsidian_notes_status ON obsidian_notes(status);
CREATE TABLE IF NOT EXISTS review_queue (
    item_id TEXT PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    note_id TEXT NOT NULL DEFAULT '',
    due_at TEXT NOT NULL,
    mastery REAL NOT NULL DEFAULT 0,
    interval_days INTEGER NOT NULL DEFAULT 1,
    reps INTEGER NOT NULL DEFAULT 0,
    last_grade INTEGER,
    last_reviewed_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'due',
    updated_at TEXT NOT NULL,
    UNIQUE(target_type, target_id, note_id)
);
CREATE INDEX IF NOT EXISTS idx_review_queue_due ON review_queue(due_at, status);
CREATE TABLE IF NOT EXISTS obsidian_sync_runs (
    run_id TEXT PRIMARY KEY,
    vault TEXT NOT NULL,
    inbox TEXT NOT NULL,
    direction TEXT NOT NULL,
    stats TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""


def ensure_schema(store: Store) -> None:
    store.conn.executescript(_SCHEMA)
    store.conn.commit()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _loads(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _clip(value: Any, limit: int = 600) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value[0:1] in {"[", "{"}:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            if value.startswith("[") and value.endswith("]"):
                return [
                    item.strip().strip('"').strip("'")
                    for item in value[1:-1].split(",")
                    if item.strip()
                ]
            return value
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse the small YAML subset written by BookCompiler and humans.

    This intentionally does not implement full YAML.  It handles scalar values,
    JSON arrays/objects, booleans, and null, which is enough for note metadata.
    Nested YAML mappings are preserved as raw strings rather than guessed.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, text
    fields: dict[str, Any] = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            continue
        fields[key] = _parse_scalar(value)
    body = "\n".join(lines[end + 1 :])
    return fields, body


def _extract_tags(frontmatter: dict[str, Any], body: str) -> list[str]:
    raw = frontmatter.get("tags", [])
    tags: list[str] = []
    if isinstance(raw, str):
        tags.extend(item.strip() for item in re.split(r"[,，]", raw) if item.strip())
    elif isinstance(raw, list):
        tags.extend(str(item).strip() for item in raw if str(item).strip())
    scan = re.sub(r"^#{1,6}\s.*$", "", body, flags=re.MULTILINE)
    tags.extend(re.findall(r"(?<![\w/])#([\w\u4e00-\u9fff/-]{2,})", scan))
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        tag = tag.lstrip("#").strip()
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_link_index(generated_root: Path) -> dict[str, tuple[str, str]]:
    """Map ``[[Books/Title]]`` and bare stems to stable target ids."""
    index: dict[str, tuple[str, str]] = {}
    if not generated_root.exists():
        return index
    for path in sorted(generated_root.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fields, _body = parse_frontmatter(text)
        for target_type, folder in TARGET_FOLDERS.items():
            ident = str(fields.get(_ID_FIELDS[target_type], "") or "").strip()
            if not ident:
                continue
            stem = path.stem
            index[f"{folder}/{stem}"] = (target_type, ident)
            index[stem] = (target_type, ident)
            title = str(fields.get("title", "") or "").strip()
            if title:
                index[title] = (target_type, ident)
    return index


def _infer_target(
    frontmatter: dict[str, Any],
    body: str,
    link_index: dict[str, tuple[str, str]],
) -> tuple[str, str, str]:
    target_type = str(frontmatter.get("target_type", "") or "").strip().lower()
    target_id = str(frontmatter.get("target_id", "") or "").strip()
    if target_type in ALLOWED_TARGETS and target_id:
        return target_type, target_id, "frontmatter"
    for kind, field in _ID_FIELDS.items():
        value = frontmatter.get(field)
        if value:
            return kind, str(value).strip(), f"frontmatter:{field}"
    target = frontmatter.get("target")
    if isinstance(target, str) and target.strip():
        value = target.strip().strip("[]")
        if ":" in value and value.split(":", 1)[0] in ALLOWED_TARGETS:
            kind, ident = value.split(":", 1)
            return kind, ident.strip(), "frontmatter:target"
        if value in link_index:
            kind, ident = link_index[value]
            return kind, ident, "frontmatter:target-link"
    for match in re.findall(r"\[\[([^\]|#]+)", body):
        key = match.strip()
        if key in link_index:
            kind, ident = link_index[key]
            return kind, ident, "wikilink"
    return "", "", "missing"


def _target_exists(store: Store, target_type: str, target_id: str) -> bool:
    if not target_type or not target_id:
        return False
    if target_type == "book":
        return store.get_book(target_id) is not None
    if target_type == "framework":
        return store.get_framework(target_id) is not None
    if target_type == "claim":
        return store.get_claim(target_id) is not None
    if target_type == "entity":
        return store.get_entity(target_id) is not None
    if target_type == "analysis":
        return store.get_analysis(target_id) is not None
    return False


def _upsert_note(store: Store, note: dict[str, Any]) -> str:
    existing = store.conn.execute(
        "SELECT * FROM obsidian_notes WHERE note_id = ? OR (vault = ? AND path = ?)",
        (note["note_id"], note["vault"], note["path"]),
    ).fetchone()
    if existing:
        note_id = existing["note_id"]
        note["note_id"] = note_id
        note["created_at"] = existing["created_at"]
        if existing["content_hash"] == note["content_hash"] and existing["status"] == note["status"]:
            store.conn.execute(
                "UPDATE obsidian_notes SET last_seen_at = ?, updated_at = ? WHERE note_id = ?",
                (note["last_seen_at"], note["updated_at"], note_id),
            )
            store.conn.commit()
            return "unchanged"
        action = "updated"
    else:
        action = "created"
    store.conn.execute(
        """
        INSERT INTO obsidian_notes
        (note_id, vault, path, target_type, target_id, title, body, tags, rating, mastery,
         review_due, frontmatter, content_hash, status, notes, created_at, updated_at, last_seen_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(note_id) DO UPDATE SET
          vault=excluded.vault, path=excluded.path, target_type=excluded.target_type,
          target_id=excluded.target_id, title=excluded.title, body=excluded.body,
          tags=excluded.tags, rating=excluded.rating, mastery=excluded.mastery,
          review_due=excluded.review_due, frontmatter=excluded.frontmatter,
          content_hash=excluded.content_hash, status=excluded.status, notes=excluded.notes,
          updated_at=excluded.updated_at, last_seen_at=excluded.last_seen_at
        """,
        (
            note["note_id"],
            note["vault"],
            note["path"],
            note["target_type"],
            note["target_id"],
            note["title"],
            note["body"],
            json.dumps(note["tags"], ensure_ascii=False),
            note["rating"],
            note["mastery"],
            note["review_due"],
            json.dumps(note["frontmatter"], ensure_ascii=False),
            note["content_hash"],
            note["status"],
            note["notes"],
            note["created_at"],
            note["updated_at"],
            note["last_seen_at"],
        ),
    )
    store.conn.commit()
    return action


def _upsert_review_item(
    store: Store,
    target_type: str,
    target_id: str,
    note_id: str,
    due_at: str,
    mastery: float | None,
) -> str:
    item_id = stable_id("review", target_type, target_id, note_id)
    existing = store.conn.execute("SELECT * FROM review_queue WHERE item_id = ?", (item_id,)).fetchone()
    store.conn.execute(
        """
        INSERT INTO review_queue
        (item_id, target_type, target_id, note_id, due_at, mastery, interval_days, reps,
         last_grade, last_reviewed_at, status, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'due', ?)
        ON CONFLICT(item_id) DO UPDATE SET
          due_at=excluded.due_at, mastery=excluded.mastery, status='due', updated_at=excluded.updated_at
        """,
        (
            item_id,
            target_type,
            target_id,
            note_id,
            due_at,
            float(mastery or 0.0),
            int(existing["interval_days"]) if existing else 1,
            int(existing["reps"]) if existing else 0,
            existing["last_grade"] if existing else None,
            existing["last_reviewed_at"] if existing else "",
            utc_now(),
        ),
    )
    store.conn.commit()
    return item_id


def import_notes(
    store: Store,
    vault: str | Path = "",
    inbox: str = "",
    subdir: str = "",
    prune: bool = False,
) -> dict[str, Any]:
    ensure_schema(store)
    inbox = inbox or configured_inbox()
    subdir = subdir or configured_subdir()
    vault_path = configured_vault(vault)
    inbox_root = vault_path / inbox
    if not inbox_root.exists():
        return {
            "vault": str(vault_path),
            "inbox": str(inbox_root),
            "inbox_exists": False,
            "created": 0,
            "updated": 0,
            "unchanged": 0,
            "missing": 0,
            "orphaned": 0,
            "review_items": 0,
        }
    link_index = _build_link_index(vault_path / subdir)
    stats = {
        "vault": str(vault_path),
        "inbox": str(inbox_root),
        "inbox_exists": True,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "missing": 0,
        "orphaned": 0,
        "review_items": 0,
        "skipped": 0,
    }
    seen_paths: set[str] = set()
    for path in sorted(inbox_root.rglob("*.md")):
        rel = path.relative_to(vault_path).as_posix()
        if path.name.startswith("_"):
            stats["skipped"] += 1
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            stats["skipped"] += 1
            continue
        frontmatter, body = parse_frontmatter(text)
        target_type, target_id, target_source = _infer_target(frontmatter, body, link_index)
        valid_target = _target_exists(store, target_type, target_id)
        status = "active" if valid_target else "orphaned"
        title = str(frontmatter.get("title", "") or path.stem).strip()
        note_id = str(frontmatter.get("note_id", "") or "").strip() or stable_id(
            "obsidian-note", str(vault_path), rel
        )
        now = utc_now()
        review_due = str(frontmatter.get("review_due", "") or "").strip()
        mastery = _coerce_float(frontmatter.get("mastery"))
        note = {
            "note_id": note_id,
            "vault": str(vault_path),
            "path": rel,
            "target_type": target_type,
            "target_id": target_id,
            "title": title,
            "body": body.strip(),
            "tags": _extract_tags(frontmatter, body),
            "rating": _coerce_float(frontmatter.get("rating")),
            "mastery": mastery,
            "review_due": review_due,
            "frontmatter": frontmatter,
            "content_hash": _hash(text),
            "status": status,
            "notes": target_source if not valid_target else "",
            "created_at": now,
            "updated_at": now,
            "last_seen_at": now,
        }
        action = _upsert_note(store, note)
        stats[action] = stats.get(action, 0) + 1
        if status == "orphaned":
            stats["orphaned"] += 1
        seen_paths.add(rel)
        if review_due and valid_target:
            _upsert_review_item(store, target_type, target_id, note_id, review_due, mastery)
            stats["review_items"] += 1

    prefix = Path(inbox).as_posix().rstrip("/") + "/"
    rows = store.conn.execute(
        "SELECT note_id, path, status FROM obsidian_notes WHERE vault = ?", (str(vault_path),)
    ).fetchall()
    missing_ids: list[str] = []
    for row in rows:
        if row["path"].startswith(prefix) and row["path"] not in seen_paths and row["status"] != "missing":
            store.conn.execute(
                "UPDATE obsidian_notes SET status = 'missing', updated_at = ? WHERE note_id = ?",
                (utc_now(), row["note_id"]),
            )
            missing_ids.append(row["note_id"])
            stats["missing"] += 1
    if prune and missing_ids:
        placeholders = ",".join("?" for _ in missing_ids)
        store.conn.execute(f"DELETE FROM review_queue WHERE note_id IN ({placeholders})", missing_ids)
        store.conn.execute(f"DELETE FROM obsidian_notes WHERE note_id IN ({placeholders})", missing_ids)
    store.conn.commit()
    run_id = stable_id("obsidian-sync", str(vault_path), inbox, utc_now())
    store.conn.execute(
        "INSERT INTO obsidian_sync_runs (run_id, vault, inbox, direction, stats, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, str(vault_path), inbox, "import", json.dumps(stats, ensure_ascii=False), utc_now()),
    )
    store.conn.commit()
    stats["run_id"] = run_id
    return stats


def init_inbox(vault: str | Path = "", inbox: str = "") -> dict[str, Any]:
    inbox = inbox or configured_inbox()
    root = configured_vault(vault) / inbox
    root.mkdir(parents=True, exist_ok=True)
    readme = root / "_README.md"
    if not readme.exists():
        readme.write_text(
            """# BookCompiler Inbox

Write your own notes here. BookCompiler imports this folder; it never edits it.

Use frontmatter so the note can be linked to a book, framework, claim, entity, or analysis:

```yaml
---
note_id: my-note-001
target_type: book
target_id: <book_id>
title: My reading note
tags: [monetary-policy, doubt]
rating: 4
mastery: 0.4
review_due: 2026-10-25
---

Your note. [[Books/中央银行与货币供给]] also works as a target link.
```

Imported notes are memory context, not source citations. Re-import is idempotent.
If a note is deleted from this folder, its database record becomes `missing` rather than being destroyed.
""",
            encoding="utf-8",
        )
    return {"inbox": str(root), "readme": str(readme), "created": True}


def export_notes(
    store: Store,
    vault: str | Path = "",
    subdir: str = "",
    book_ids: list[str] | None = None,
    overwrite: bool = True,
    preserve_edits: bool = True,
) -> dict[str, Any]:
    return export_vault(
        store,
        configured_vault(vault),
        subdir=subdir or configured_subdir(),
        book_ids=book_ids,
        overwrite=overwrite,
        preserve_edits=preserve_edits,
    )


def sync_obsidian(
    store: Store,
    vault: str | Path = "",
    subdir: str = "",
    inbox: str = "",
    direction: str = "both",
    book_ids: list[str] | None = None,
    overwrite: bool = True,
    prune: bool = False,
    init: bool = True,
    preserve_edits: bool = True,
) -> dict[str, Any]:
    direction = (direction or "both").lower()
    if direction not in {"export", "import", "both"}:
        raise ValueError("direction must be export, import, or both")
    subdir = subdir or configured_subdir()
    inbox = inbox or configured_inbox()
    vault_path = configured_vault(vault)
    result: dict[str, Any] = {"direction": direction, "vault": str(vault_path), "subdir": subdir, "inbox": inbox}
    if init and direction in {"import", "both"}:
        result["inbox_init"] = init_inbox(vault_path, inbox)
    if direction in {"export", "both"}:
        result["export"] = export_notes(
            store, vault_path, subdir=subdir, book_ids=book_ids, overwrite=overwrite, preserve_edits=preserve_edits
        )
    if direction in {"import", "both"}:
        result["import"] = import_notes(store, vault_path, inbox=inbox, subdir=subdir, prune=prune)
    ensure_schema(store)
    store.conn.execute(
        "INSERT INTO obsidian_sync_runs (run_id, vault, inbox, direction, stats, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            stable_id("obsidian-sync", str(vault_path), inbox, direction, utc_now()),
            str(vault_path),
            inbox,
            direction,
            json.dumps(result, ensure_ascii=False, default=str),
            utc_now(),
        ),
    )
    store.conn.commit()
    return result


def list_reader_notes(
    store: Store,
    query: str = "",
    target_type: str = "",
    target_id: str = "",
    status: str = "active",
    limit: int = 50,
) -> list[dict[str, Any]]:
    ensure_schema(store)
    params: list[Any] = []
    where: list[str] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if target_type:
        where.append("target_type = ?")
        params.append(target_type)
    if target_id:
        where.append("target_id = ?")
        params.append(target_id)
    sql = "SELECT * FROM obsidian_notes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, int(limit)))
    rows = store.conn.execute(sql, params).fetchall()
    terms = set(query_terms(query)) if query else set()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["tags"] = _loads(item.get("tags"), [])
        item["frontmatter"] = _loads(item.get("frontmatter"), {})
        item["relevance"] = 0.0
        if terms:
            haystack = " ".join(
                [str(item.get("title", "")), str(item.get("body", "")), " ".join(item.get("tags", []))]
            )
            overlap = len(terms.intersection(set(query_terms(haystack))))
            item["relevance"] = round(float(overlap), 3)
            if overlap == 0:
                continue
        result.append(item)
    result.sort(
        key=lambda item: (
            -float(item.get("relevance", 0.0)),
            -float(item.get("rating") or 0.0),
            -float(item.get("mastery") or 0.0),
            str(item.get("title", "")),
        )
    )
    return result[:limit]


def reader_notes_for_analysis(
    store: Store,
    query: str,
    lenses: list[str],
    book_ids: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return reader notes as memory context, never as citations."""
    notes = list_reader_notes(store, query="", status="active", limit=500)
    selected = set(book_ids or [])
    terms = set(query_terms(query))
    ranked: list[tuple[float, dict[str, Any]]] = []
    for note in notes:
        haystack = " ".join(
            [str(note.get("title", "")), str(note.get("body", "")), " ".join(note.get("tags", []))]
        )
        score = float(len(terms.intersection(set(query_terms(haystack))))) if terms else 0.0
        if selected and note.get("target_type") == "book" and note.get("target_id") in selected:
            score += 1.5
        score += 0.2 * float(note.get("rating") or 0.0)
        score += 0.3 * float(note.get("mastery") or 0.0)
        if score <= 0 and selected:
            continue
        ranked.append((score, note))
    ranked.sort(key=lambda pair: (-pair[0], str(pair[1].get("title", ""))))
    result: list[dict[str, Any]] = []
    for score, note in ranked[: max(0, int(limit))]:
        result.append(
            {
                "source": "obsidian_note",
                "kind": "reader_note",
                "note_id": note.get("note_id"),
                "path": note.get("path"),
                "title": note.get("title"),
                "target_type": note.get("target_type"),
                "target_id": note.get("target_id"),
                "tags": note.get("tags", []),
                "rating": note.get("rating"),
                "mastery": note.get("mastery"),
                "review_due": note.get("review_due"),
                "body": _clip(note.get("body", ""), 700),
                "relevance": round(score, 3),
                "warning": "Reader note, not a source citation. Verify any factual claim against the book text.",
            }
        )
    return result


def list_due_reviews(store: Store, due_before: str = "", limit: int = 50) -> list[dict[str, Any]]:
    ensure_schema(store)
    cutoff = due_before or utc_now()
    rows = store.conn.execute(
        "SELECT r.*, n.title AS note_title, n.path AS note_path "
        "FROM review_queue r LEFT JOIN obsidian_notes n ON n.note_id = r.note_id "
        "WHERE r.due_at <= ? AND r.status = 'due' ORDER BY r.due_at ASC LIMIT ?",
        (cutoff, max(1, int(limit))),
    ).fetchall()
    return [dict(row) for row in rows]


def grade_review(store: Store, item_id: str, grade: int, note: str = "") -> dict[str, Any]:
    ensure_schema(store)
    grade = int(grade)
    if not 0 <= grade <= 5:
        raise ValueError("grade must be between 0 and 5")
    row = store.conn.execute("SELECT * FROM review_queue WHERE item_id = ?", (item_id,)).fetchone()
    if not row:
        raise ValueError(f"unknown review item: {item_id}")
    item = dict(row)
    mastery = float(item.get("mastery") or 0.0)
    reps = int(item.get("reps") or 0)
    interval = int(item.get("interval_days") or 1)
    if grade < 3:
        mastery = max(0.0, mastery - 0.2)
        interval = 1
    else:
        mastery = min(1.0, mastery + 0.15)
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 3
        else:
            factor = 1.4 if grade == 3 else 1.8 if grade == 4 else 2.2
            interval = max(1, round(interval * factor))
    due_at = (datetime.now(timezone.utc) + timedelta(days=interval)).isoformat()
    store.conn.execute(
        "UPDATE review_queue SET mastery = ?, interval_days = ?, reps = ?, last_grade = ?, "
        "last_reviewed_at = ?, due_at = ?, status = 'due', updated_at = ? WHERE item_id = ?",
        (round(mastery, 3), interval, reps + 1, grade, utc_now(), due_at, utc_now(), item_id),
    )
    if item.get("note_id"):
        store.conn.execute(
            "UPDATE obsidian_notes SET mastery = ?, updated_at = ? WHERE note_id = ?",
            (round(mastery, 3), utc_now(), item["note_id"]),
        )
    store.conn.commit()
    return {
        "item_id": item_id,
        "grade": grade,
        "mastery": round(mastery, 3),
        "interval_days": interval,
        "reps": reps + 1,
        "due_at": due_at,
        "note": note,
    }


def obsidian_status(store: Store, vault: str = "") -> dict[str, Any]:
    ensure_schema(store)
    params: list[Any] = []
    where = ""
    if vault:
        where = " WHERE vault = ?"
        params.append(str(Path(vault).expanduser().resolve()))
    rows = store.conn.execute(
        "SELECT status, COUNT(*) AS n FROM obsidian_notes" + where + " GROUP BY status", params
    ).fetchall()
    counts = {row["status"]: row["n"] for row in rows}
    due = store.conn.execute(
        "SELECT COUNT(*) FROM review_queue WHERE status = 'due' AND due_at <= ?", (utc_now(),)
    ).fetchone()[0]
    last_run = store.conn.execute(
        "SELECT * FROM obsidian_sync_runs ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    return {
        "vault": vault,
        "notes": {
            "total": sum(counts.values()),
            "active": counts.get("active", 0),
            "orphaned": counts.get("orphaned", 0),
            "missing": counts.get("missing", 0),
        },
        "due_reviews": due,
        "last_run": (
            {
                "run_id": last_run["run_id"],
                "vault": last_run["vault"],
                "inbox": last_run["inbox"],
                "direction": last_run["direction"],
                "created_at": last_run["created_at"],
            }
            if last_run
            else None
        ),
        "bidirectional": True,
        "write_policy": "generated notes are protected exports (user edits preserved); inbox notes are imported into SQLite as reader notes",
    }