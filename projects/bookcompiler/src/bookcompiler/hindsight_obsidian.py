"""Bidirectional Obsidian mirror for Hindsight memories.

The Hindsight API remains the source of truth.  This module mirrors every
memory unit into a Markdown file whose body can be edited in Obsidian, then
pushes those edits back with the Hindsight curation endpoint.

Safety rules
------------
* Only files below ``<vault>/Hindsight`` are touched.
* Derived ``observation`` memories are exported read-only; Hindsight does not
  allow curating them.
* A user-edited file is never overwritten by a later export.  If the remote
  memory changed as well, the remote version is written as a separate
  ``.conflict-*.md`` file.
* Deleted / missing memories are reported, not silently deleted from disk.
* The API is optional: every public function returns ``ok=False`` instead of
  raising when Hindsight is unavailable.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import load_env, project_root
from .hindsight import bank_id, enabled, list_memories, retain, update_memory
from .models import utc_now
from .obsidian import _frontmatter, _sanitize
from .obsidian_sync import parse_frontmatter

DEFAULT_SUBDIR = "Hindsight"
DEFAULT_INBOX = "Hindsight Inbox"
DEFAULT_VAULT_CANDIDATE = Path.home() / "Documents" / "Obsidian Vault"
STATE_VERSION = 1
_MARKER = re.compile(
    r"<!--\s*hindsight:(?P<name>[a-z_]+):start\s*-->\s*(?P<body>.*?)\s*<!--\s*hindsight:(?P=name):end\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def vault_path(vault: str | Path = "") -> Path:
    """Return the configured Obsidian vault.

    An explicit argument wins, then ``BOOKCOMPILER_OBSIDIAN_VAULT``, then
    ``OBSIDIAN_VAULT``.  For this machine the common default is used when it
    exists.  The caller should check ``vault_path().is_dir()`` before writing.
    """
    load_env()
    if str(vault or "").strip():
        return Path(str(vault)).expanduser().resolve()
    import os

    for key in ("BOOKCOMPILER_OBSIDIAN_VAULT", "OBSIDIAN_VAULT"):
        value = os.environ.get(key, "").strip()
        if value:
            return Path(value).expanduser().resolve()
    if DEFAULT_VAULT_CANDIDATE.is_dir():
        return DEFAULT_VAULT_CANDIDATE.resolve()
    return DEFAULT_VAULT_CANDIDATE


def subdir_name() -> str:
    load_env()
    import os

    return os.environ.get("HINDSIGHT_OBSIDIAN_SUBDIR", DEFAULT_SUBDIR).strip() or DEFAULT_SUBDIR


def inbox_name() -> str:
    load_env()
    import os

    return os.environ.get("HINDSIGHT_OBSIDIAN_INBOX", DEFAULT_INBOX).strip() or DEFAULT_INBOX


def state_path() -> Path:
    load_env()
    import os

    explicit = os.environ.get("BOOKCOMPILER_HINDSIGHT_OBSIDIAN_STATE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return project_root() / ".bookcompiler" / "hindsight-obsidian-state.json"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _canonical(text: str, context: str, state: str) -> str:
    return "\n".join((_clean(text), _clean(context), _clean(state).lower()))


def _canonical_hash(text: str, context: str, state: str) -> str:
    return _hash_text(_canonical(text, context, state))


def _memory_state(item: dict[str, Any]) -> str:
    value = str(item.get("state") or "valid").strip().lower()
    return value if value in {"valid", "invalidated"} else "valid"


def _memory_fact_type(item: dict[str, Any]) -> str:
    value = str(item.get("fact_type") or "world").strip().lower()
    return value if value in {"world", "experience", "observation"} else "world"


def _memory_text(item: dict[str, Any]) -> str:
    return _clean(item.get("text") or item.get("content") or "")


def _memory_context(item: dict[str, Any]) -> str:
    return _clean(item.get("context") or "")


def _memory_tags(item: dict[str, Any]) -> list[str]:
    raw = item.get("tags") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in re.split(r"[,?]", raw) if part.strip()]
    if not isinstance(raw, list):
        return []
    return [str(tag).strip() for tag in raw if str(tag).strip()]


def _memory_entities(item: dict[str, Any]) -> list[str]:
    raw = item.get("entities") or []
    if not isinstance(raw, list):
        return []
    result: list[str] = []
    for entity in raw:
        if isinstance(entity, dict):
            name = entity.get("name") or entity.get("canonical_name") or entity.get("text") or ""
        else:
            name = str(entity)
        name = str(name).strip()
        if name and name not in result:
            result.append(name)
    return result


def _relative_path(item: dict[str, Any], state_entry: dict[str, Any] | None = None) -> str:
    if state_entry and state_entry.get("path"):
        return str(state_entry["path"])
    memory_id = str(item.get("id") or "").strip()
    fact_type = _memory_fact_type(item)
    text = _memory_text(item)
    slug = _sanitize(text.splitlines()[0] if text else "memory", "memory", 55)
    folder = "Observations" if fact_type == "observation" else "Memories"
    return f"{folder}/{fact_type}/{memory_id[:8]}-{slug}.md"


def _render_file(item: dict[str, Any], *, exported_at: str | None = None) -> str:
    memory_id = str(item.get("id") or "")
    fact_type = _memory_fact_type(item)
    state = _memory_state(item)
    text = _memory_text(item)
    context = _memory_context(item)
    readonly = fact_type == "observation"
    fields: dict[str, Any] = {
        "generator": "bookcompiler-hindsight",
        "managed": True,
        "source": "hindsight",
        "bank": bank_id(),
        "hindsight_id": memory_id,
        "fact_type": fact_type,
        "state": state,
        "document_id": item.get("document_id") or "",
        "event_date": item.get("date") or "",
        "tags": _memory_tags(item),
        "entities": _memory_entities(item),
        "read_only": readonly,
        "exported_at": exported_at or utc_now(),
        "content_hash": _canonical_hash(text, context, state),
    }
    lines = [
        _frontmatter(fields),
        "",
        "# Hindsight Memory",
        "",
        "> 本文件由 Hindsight 记忆同步生成。可直接修改正文、Context 和 state。",
        "> observation 是派生记忆，只读；world / experience 可编辑并回写。",
        "",
        "<!-- hindsight:text:start -->",
        text,
        "<!-- hindsight:text:end -->",
        "",
        "## Context",
        "",
        "<!-- hindsight:context:start -->",
        context,
        "<!-- hindsight:context:end -->",
        "",
        "## Curation",
        "",
        "<!-- hindsight:state:start -->",
        state,
        "<!-- hindsight:state:end -->",
        "",
        "改 state 为 `invalidated` 可软失效；改回 `valid` 可恢复。",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _block(body: str, name: str) -> str | None:
    match = _MARKER.search(body)
    if match and match.group("name").lower() == name:
        return match.group("body").strip()
    for candidate in _MARKER.finditer(body):
        if candidate.group("name").lower() == name:
            return candidate.group("body").strip()
    return None


def _parse_memory_file(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    fields, body = parse_frontmatter(raw)
    memory_id = str(fields.get("hindsight_id") or "").strip()
    if not memory_id:
        return None
    text = _block(body, "text")
    context = _block(body, "context")
    state = _block(body, "state")
    if text is None:
        # A hand-written file may omit markers.  Treat the body as the memory.
        text = body.strip()
    if context is None:
        context = str(fields.get("context") or "")
    if state is None:
        state = str(fields.get("state") or "valid")
    return {
        "memory_id": memory_id,
        "fact_type": str(fields.get("fact_type") or "world").strip().lower(),
        "text": _clean(text),
        "context": _clean(context),
        "state": _clean(state).lower() or "valid",
        "tags": _memory_tags({"tags": fields.get("tags", [])}),
    }


def _load_state() -> dict[str, Any]:
    path = state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("version", STATE_VERSION)
    data.setdefault("bank", bank_id())
    data.setdefault("memories", {})
    data.setdefault("inbox", {})
    return data


def _save_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _fetch_all(limit: int = 1000) -> dict[str, Any]:
    """Fetch both live and invalidated memories.

    Hindsight keeps invalidated facts in an archive table and lists them only
    when ``state=invalidated`` is explicit.  The mirror must show both so the
    user can restore a memory by changing the state block in Obsidian.
    """
    merged: dict[str, dict[str, Any]] = {}
    totals = 0
    for state in ("valid", "invalidated"):
        first = list_memories(limit=limit, offset=0, state=state)
        if not first.get("ok"):
            # A server that predates the state parameter may reject it.  Fall
            # back to the live view rather than failing the whole mirror.
            if state == "invalidated":
                break
            return first
        items = list(first.get("items") or [])
        total = int(first.get("total") or len(items))
        totals += total
        offset = len(items)
        while offset < total and offset < 10000:
            page = list_memories(limit=limit, offset=offset, state=state)
            if not page.get("ok"):
                return page
            chunk = list(page.get("items") or [])
            if not chunk:
                break
            items.extend(chunk)
            offset += len(chunk)
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                merged[str(item["id"])] = item
    return {"ok": True, "items": list(merged.values()), "total": len(merged)}


def export_memories(vault: str | Path = "", *, subdir: str = "", limit: int = 1000) -> dict[str, Any]:
    if not enabled():
        return {"ok": False, "error": "Hindsight is disabled"}
    remote = _fetch_all(limit=limit)
    if not remote.get("ok"):
        return remote
    vault_root = vault_path(vault)
    root = vault_root / (subdir or subdir_name())
    root.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    entries: dict[str, Any] = state.setdefault("memories", {})
    written: list[str] = []
    preserved: list[str] = []
    conflicts: list[str] = []
    orphaned: list[str] = []
    now = utc_now()

    remote_ids: set[str] = set()
    for item in remote.get("items") or []:
        if not isinstance(item, dict):
            continue
        memory_id = str(item.get("id") or "").strip()
        if not memory_id:
            continue
        remote_ids.add(memory_id)
        entry = entries.get(memory_id) if isinstance(entries.get(memory_id), dict) else {}
        relative = _relative_path(item, entry)
        path = root / relative
        remote_text = _memory_text(item)
        remote_context = _memory_context(item)
        remote_state = _memory_state(item)
        remote_hash = _canonical_hash(remote_text, remote_context, remote_state)
        exported_hash = str(entry.get("last_export_hash") or "")
        remote_before = str(entry.get("remote_hash") or "")

        if path.is_file():
            local = _parse_memory_file(path)
            if local is not None:
                local_hash = _canonical_hash(local["text"], local["context"], local["state"])
                user_changed = bool(exported_hash) and local_hash != exported_hash
                remote_changed = bool(remote_before) and remote_hash != remote_before
                if user_changed:
                    preserved.append(relative)
                    if remote_changed:
                        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                        conflict = path.with_name(path.stem + f".conflict-{stamp}.md")
                        conflict.write_text(_render_file(item, exported_at=now), encoding="utf-8")
                        conflicts.append(str(conflict.relative_to(root)))
                    continue

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_file(item, exported_at=now), encoding="utf-8")
        written.append(relative)
        entries[memory_id] = {
            "path": relative,
            "last_export_hash": remote_hash,
            "remote_hash": remote_hash,
            "last_import_hash": entry.get("last_import_hash", ""),
            "updated_at": now,
        }

    for memory_id, entry in list(entries.items()):
        if memory_id not in remote_ids and isinstance(entry, dict):
            relative = str(entry.get("path") or "")
            if relative and (root / relative).is_file():
                orphaned.append(relative)

    readme = root / "_README.md"
    readme.write_text(
        "# Hindsight Memories\n\n"
        "This folder is a two-way mirror of the Hindsight bank `" + bank_id() + "`.\n\n"
        "- `Memories/` contains editable `world` and `experience` memories.\n"
        "- `Observations/` contains derived memories that Hindsight does not allow editing.\n"
        "- Edit the text between `<!-- hindsight:text:start -->` and `<!-- hindsight:text:end -->`.\n"
        "- Change the state block to `invalidated` or `valid` to soft-delete / restore a memory.\n"
        "- Run `sync-obsidian.bat` or `bookcompiler hindsight-obsidian-sync` after editing.\n"
        "- A `.conflict-*.md` file is created if both the local note and remote memory changed.\n",
        encoding="utf-8",
    )
    manifest = {
        "generator": "bookcompiler-hindsight",
        "generated_at": now,
        "bank": bank_id(),
        "root": str(root),
        "counts": {
            "remote": len(remote_ids),
            "written": len(written),
            "preserved_user_edits": len(preserved),
            "conflicts": len(conflicts),
            "orphaned": len(orphaned),
        },
        "written": sorted(written),
        "preserved": sorted(preserved),
        "conflicts": sorted(conflicts),
        "orphaned": sorted(orphaned),
    }
    (root / ".hindsight-export.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _save_state(state)
    return {"ok": True, **manifest}


def import_memories(vault: str | Path = "", *, subdir: str = "", limit: int = 1000) -> dict[str, Any]:
    if not enabled():
        return {"ok": False, "error": "Hindsight is disabled"}
    remote = _fetch_all(limit=limit)
    if not remote.get("ok"):
        return remote
    remote_by_id = {
        str(item.get("id")): item
        for item in (remote.get("items") or [])
        if isinstance(item, dict) and item.get("id")
    }
    vault_root = vault_path(vault)
    root = vault_root / (subdir or subdir_name())
    if not root.is_dir():
        return {"ok": True, "root": str(root), "updated": 0, "message": "Hindsight mirror folder does not exist yet"}
    state = _load_state()
    entries: dict[str, Any] = state.setdefault("memories", {})
    updated = 0
    skipped = 0
    read_only = 0
    missing = 0
    failed: list[dict[str, str]] = []
    now = utc_now()
    for path in sorted(root.rglob("*.md")):
        if path.name.startswith("_") or ".conflict-" in path.name:
            continue
        local = _parse_memory_file(path)
        if local is None:
            continue
        memory_id = local["memory_id"]
        remote_item = remote_by_id.get(memory_id)
        if remote_item is None:
            missing += 1
            continue
        remote_text = _memory_text(remote_item)
        remote_context = _memory_context(remote_item)
        remote_state = _memory_state(remote_item)
        remote_hash = _canonical_hash(remote_text, remote_context, remote_state)
        local_hash = _canonical_hash(local["text"], local["context"], local["state"])
        if local_hash == remote_hash:
            entries[memory_id] = {
                **(entries.get(memory_id) or {}),
                "path": str(path.relative_to(root)),
                "last_export_hash": local_hash,
                "remote_hash": remote_hash,
                "updated_at": now,
            }
            skipped += 1
            continue
        fact_type = _memory_fact_type(remote_item)
        if fact_type == "observation":
            read_only += 1
            continue
        if remote_state == "invalidated":
            # While a memory is archived, restore state first.  Some Hindsight
            # versions reject text/context in the same PATCH as state.  After
            # restoration, apply the user's text and context edits in a second
            # call so an Obsidian edit is never silently lost.
            if local["state"] != "valid":
                skipped += 1
                continue
            restored = update_memory(memory_id, state="valid", reason="Restored from Obsidian")
            if not restored.get("ok"):
                failed.append({"id": memory_id, "error": str(restored.get("error") or "restore failed")})
                continue
            follow_up: dict[str, Any] = {}
            if local["text"] != remote_text:
                follow_up["text"] = local["text"]
            if local["context"] != remote_context:
                follow_up["context"] = local["context"]
            if follow_up:
                result = update_memory(memory_id, reason="Edited in Obsidian after restore", **follow_up)
                if not result.get("ok"):
                    failed.append({"id": memory_id, "error": str(result.get("error") or "update failed")})
                    continue
            entries[memory_id] = {
                **(entries.get(memory_id) or {}),
                "path": str(path.relative_to(root)),
                "last_export_hash": local_hash,
                "remote_hash": remote_hash,
                "last_import_hash": local_hash,
                "updated_at": now,
            }
            updated += 1
            continue
        fields: dict[str, Any] = {}
        if local["text"] != remote_text:
            fields["text"] = local["text"]
        if local["context"] != remote_context:
            fields["context"] = local["context"]
        if local["state"] != remote_state:
            fields["state"] = local["state"]
        if not fields:
            skipped += 1
            continue
        result = update_memory(memory_id, reason="Edited in Obsidian", **fields)
        if result.get("ok"):
            entries[memory_id] = {
                **(entries.get(memory_id) or {}),
                "path": str(path.relative_to(root)),
                "last_export_hash": local_hash,
                "remote_hash": remote_hash,
                "last_import_hash": local_hash,
                "updated_at": now,
            }
            updated += 1
        else:
            failed.append({"id": memory_id, "error": str(result.get("error") or "update failed")})
    _save_state(state)
    return {
        "ok": True,
        "root": str(root),
        "updated": updated,
        "unchanged": skipped,
        "read_only_skipped": read_only,
        "missing": missing,
        "failed": failed,
    }


def import_inbox(vault: str | Path = "", *, inbox: str = "", limit: int = 1000) -> dict[str, Any]:
    """Create new Hindsight memories from Markdown notes in the Inbox.

    A note with no ``hindsight_id`` is treated as a new memory.  The file is
    remembered by content hash so later syncs do not create duplicates.
    """
    if not enabled():
        return {"ok": False, "error": "Hindsight is disabled"}
    vault_root = vault_path(vault)
    root = vault_root / (inbox or inbox_name())
    if not root.is_dir():
        return {"ok": True, "created": 0, "root": str(root)}
    state = _load_state()
    memo: dict[str, Any] = state.setdefault("inbox", {})
    created = 0
    unchanged = 0
    failed: list[dict[str, str]] = []
    now = utc_now()
    for path in sorted(root.rglob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except OSError:
            continue
        fields, body = parse_frontmatter(raw)
        if str(fields.get("hindsight_id") or "").strip():
            continue
        text = _block(body, "text") or body
        text = _clean(text)
        if not text:
            continue
        digest = _hash_text(text + "\n" + str(fields.get("context") or ""))
        key = str(path.relative_to(root))
        if memo.get(key, {}).get("hash") == digest:
            unchanged += 1
            continue
        context = _clean(fields.get("context") or "Obsidian Inbox")
        tags = _memory_tags({"tags": fields.get("tags", [])}) or ["obsidian-inbox"]
        result = retain(
            text,
            context=context,
            tags=tags,
            metadata={"source": "obsidian", "path": key},
            asynchronous=True,
        )
        if result.get("ok"):
            memo[key] = {"hash": digest, "imported_at": now}
            created += 1
        else:
            failed.append({"path": key, "error": str(result.get("error") or "retain failed")})
    _save_state(state)
    return {"ok": True, "created": created, "unchanged": unchanged, "failed": failed, "root": str(root)}


def sync_memories(
    vault: str | Path = "",
    *,
    subdir: str = "",
    inbox: str = "",
    direction: str = "both",
) -> dict[str, Any]:
    direction = (direction or "both").lower()
    if direction not in {"export", "import", "both"}:
        raise ValueError("direction must be export, import, or both")
    result: dict[str, Any] = {"ok": True, "direction": direction, "vault": str(vault_path(vault))}
    if direction in {"export", "both"}:
        exported = export_memories(vault, subdir=subdir)
        result["export"] = exported
        result["ok"] = bool(exported.get("ok"))
    if direction in {"import", "both"}:
        imported = import_memories(vault, subdir=subdir)
        result["import"] = imported
        result["ok"] = bool(result["ok"] and imported.get("ok"))
        inbox_result = import_inbox(vault, inbox=inbox)
        result["inbox"] = inbox_result
        result["ok"] = bool(result["ok"] and inbox_result.get("ok"))
    return result


def hindsight_obsidian_status(vault: str | Path = "") -> dict[str, Any]:
    root = vault_path(vault) / subdir_name()
    state = _load_state()
    return {
        "vault": str(vault_path(vault)),
        "root": str(root),
        "exists": root.is_dir(),
        "state_file": str(state_path()),
        "memory_files": len(list(root.rglob("*.md"))) if root.is_dir() else 0,
        "tracked_memories": len(state.get("memories") or {}),
        "tracked_inbox": len(state.get("inbox") or {}),
        "enabled": enabled(),
        "write_policy": "editable world/experience memories; observations are read-only; conflicts are preserved",
    }
