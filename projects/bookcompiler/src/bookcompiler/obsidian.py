from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .models import utc_now
from .render import render_memo
from .store import Store
from .utils import stable_id


_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize(name: str, fallback: str = "untitled", limit: int = 90) -> str:
    value = _ILLEGAL.sub("-", str(name or "")).strip().strip(".")
    value = re.sub(r"\s+", " ", value)
    if len(value) > limit:
        value = value[:limit].rstrip()
    return value or fallback


def _yaml(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if value is None:
            continue
        lines.append(f"{key}: {_yaml(value)}")
    lines.append("---")
    return "\n".join(lines)


def _quote(text: str, indent: str = "") -> list[str]:
    clean = str(text or "").strip()
    if not clean:
        return [f"{indent}> _No quote recorded._"]
    return [f"{indent}> {line}" for line in clean.splitlines()]


def _citation_lines(
    citations: list[dict[str, Any]],
    names: "_Names",
    store: Store,
    default_book_id: str = "",
) -> list[str]:
    lines: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        book_id = str(citation.get("book_id", "") or default_book_id)
        book = store.get_book(book_id) if book_id else None
        title = book["title"] if book else book_id
        chapter = str(citation.get("chapter", "") or citation.get("chapter_title", "")).strip()
        page = citation.get("page", citation.get("page_start"))
        if book_id:
            source = f"[[Books/{names.book(book_id, title)}|{title}]]"
        else:
            source = "_source not recorded_"
        if chapter:
            source += f" · {chapter}"
        if page not in (None, ""):
            source += f" · p.{page}"
        lines.extend(_quote(str(citation.get("quote", ""))))
        lines.append(f"  - {source}")
        lines.append("")
    return lines


class _Names:
    def __init__(self) -> None:
        self._used: dict[str, set[str]] = {"book": set(), "framework": set(), "entity": set(), "claim": set(), "analysis": set()}
        self._maps: dict[str, dict[str, str]] = {"book": {}, "framework": {}, "entity": {}, "claim": {}, "analysis": {}}

    def _allocate(self, kind: str, ident: str, base: str, fallback: str) -> str:
        if ident in self._maps[kind]:
            return self._maps[kind][ident]
        name = _sanitize(base, fallback)
        if name in self._used[kind]:
            name = f"{name} - {ident[:8]}"
        self._used[kind].add(name)
        self._maps[kind][ident] = name
        return name

    def book(self, ident: str, title: str = "") -> str:
        return self._allocate("book", ident, title or ident, f"book-{ident[:8]}")

    def framework(self, ident: str, name: str = "") -> str:
        return self._allocate("framework", ident, name or ident, f"framework-{ident[:8]}")

    def entity(self, ident: str, name: str = "") -> str:
        return self._allocate("entity", ident, name or ident, f"entity-{ident[:8]}")

    def claim(self, ident: str) -> str:
        return self._allocate("claim", ident, f"claim-{ident[:8]}", f"claim-{ident[:8]}")

    def analysis(self, ident: str) -> str:
        return self._allocate("analysis", ident, f"analysis-{ident[:8]}", f"analysis-{ident[:8]}")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def _content_hash(text: str) -> str:
    return hashlib.sha256((text.rstrip() + "\n").encode("utf-8")).hexdigest()


def _learned(store: Store, book: dict[str, Any], frameworks: list[dict[str, Any]]) -> bool:
    card = store.get_book_card(book["book_id"]) or {}
    return (
        book.get("status") == "compiled"
        and str(card.get("status", "")).lower() in {"verified", "complete"}
        and bool(frameworks)
    )


def export_vault(
    store: Store,
    vault_path: str | Path,
    subdir: str = "BookCompiler",
    book_ids: list[str] | None = None,
    include_claims: bool = True,
    include_entities: bool = True,
    include_analyses: bool = True,
    overwrite: bool = True,
    preserve_edits: bool = True,
) -> dict[str, Any]:
    """Export the library as an Obsidian-friendly Markdown vault.

    Everything is written under ``<vault>/<subdir>`` so the exporter cannot
    overwrite a user's existing notes outside its own folder.  Wikilinks use
    folder-qualified names (``[[Books/Title]]``) and YAML frontmatter is kept
    intentionally simple so Dataview can query it without custom scripts.
    """
    root = Path(vault_path).expanduser().resolve() / _sanitize(subdir, "BookCompiler")
    selected = set(book_ids or [])
    books = [book for book in store.list_books() if not selected or book["book_id"] in selected]
    if not books:
        raise ValueError("no books matched the requested export scope")

    all_frameworks = store.list_frameworks()
    frameworks_by_book: dict[str, list[dict[str, Any]]] = {}
    for framework in all_frameworks:
        frameworks_by_book.setdefault(framework.get("book_id", ""), []).append(framework)

    claims = store.list_claims(limit=100000) if include_claims else []
    if selected:
        claims = [claim for claim in claims if claim.get("book_id") in selected]
    claims_by_book: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        claims_by_book.setdefault(claim.get("book_id", ""), []).append(claim)

    entities = store.list_entities(limit=100000) if include_entities else []
    entity_details: dict[str, dict[str, Any]] = {}
    entities_by_book: dict[str, set[str]] = {}
    if include_entities:
        for entity in entities:
            detail = store.get_entity(entity["entity_id"]) or entity
            entity_details[entity["entity_id"]] = detail
            for mention in detail.get("mentions", []):
                entities_by_book.setdefault(mention.get("book_id", ""), set()).add(entity["entity_id"])
        if selected:
            # Keep entities that actually occur in one of the selected books.
            entities = [
                entity for entity in entities
                if any(entity["entity_id"] in entities_by_book.get(book_id, set()) for book_id in selected)
            ]
        entity_details = {entity["entity_id"]: entity_details.get(entity["entity_id"], entity) for entity in entities}

    analyses = store.list_analyses() if include_analyses else []
    if selected:
        analyses = [
            analysis for analysis in analyses
            if selected.intersection(
                {book.get("book_id", "") for book in (analysis.get("selection", {}) or {}).get("books", []) if isinstance(book, dict)}
            )
        ]

    names = _Names()
    for book in store.list_books():
        names.book(book["book_id"], book["title"])
    for framework in all_frameworks:
        names.framework(framework.get("framework_id", ""), framework.get("name", ""))
    for entity in store.list_entities(limit=100000):
        names.entity(entity["entity_id"], entity.get("canonical_name", ""))
    for claim in store.list_claims(limit=100000):
        names.claim(claim.get("claim_id", ""))
    for analysis in store.list_analyses():
        names.analysis(analysis.get("analysis_id", ""))

    written: list[str] = []
    skipped: list[str] = []
    preserved: list[str] = []
    conflicts: list[str] = []
    hashes: dict[str, str] = {}
    previous_hashes: dict[str, str] = {}
    previous_manifest = root / ".bookcompiler-export.json"
    if previous_manifest.is_file():
        try:
            previous = json.loads(previous_manifest.read_text(encoding="utf-8"))
            raw_hashes = previous.get("hashes") if isinstance(previous, dict) else None
            if isinstance(raw_hashes, dict):
                previous_hashes = {str(key): str(value) for key, value in raw_hashes.items()}
        except (OSError, ValueError, json.JSONDecodeError):
            previous_hashes = {}

    def emit(relative: str, text: str) -> None:
        path = root / relative
        if path.exists() and not overwrite:
            skipped.append(relative)
            return
        if path.exists() and preserve_edits:
            old_hash = previous_hashes.get(relative)
            if old_hash:
                try:
                    current_hash = _content_hash(path.read_text(encoding="utf-8"))
                except OSError:
                    current_hash = ""
                if current_hash and current_hash != old_hash:
                    # The user edited a generated note.  Keep their file and
                    # put the freshly generated version beside it instead of
                    # silently destroying their work.
                    preserved.append(relative)
                    new_text = text.rstrip() + "\n"
                    if _content_hash(new_text) != current_hash:
                        conflict = path.with_name(path.stem + ".generated" + path.suffix)
                        conflict.write_text(new_text, encoding="utf-8", newline="\n")
                        conflicts.append(str(conflict.relative_to(root)))
                    return
        _write(path, text)
        written.append(relative)
        hashes[relative] = _content_hash(text)

    for book in books:
        book_id = book["book_id"]
        card = store.get_book_card(book_id) or {}
        fs = frameworks_by_book.get(book_id, [])
        learned = _learned(store, book, fs)
        entity_ids = sorted(entities_by_book.get(book_id, set()))
        lines = [
            _frontmatter(
                {
                    "generator": "bookcompiler",
                    "type": "book",
                    "book_id": book_id,
                    "title": book.get("title", ""),
                    "author": book.get("author", ""),
                    "status": book.get("status", ""),
                    "learned": learned,
                    "disciplines": book.get("disciplines", []),
                    "frameworks": len(fs),
                    "claims": len(claims_by_book.get(book_id, [])),
                    "tags": ["bookcompiler/book"] + [f"discipline/{item}" for item in book.get("disciplines", [])],
                    "updated_at": utc_now(),
                }
            ),
            "",
            f"# {book.get('title', 'Untitled')}",
            "",
            f"> {book.get('author', 'Unknown author')} · `{book.get('status', '')}` · "
            + ("**learned**" if learned else "**not learned yet**"),
            "",
        ]
        if card:
            lines.extend(["## One-line thesis", "", str(card.get("one_line_thesis", "")), ""])
            for title, key in [
                ("Core questions", "core_questions"),
                ("Key concepts", "key_concepts"),
                ("Assumptions", "assumptions"),
                ("Limitations", "limitations"),
                ("Best for", "best_for"),
                ("Not for", "not_for"),
            ]:
                values = card.get(key) or []
                if values:
                    lines.extend([f"## {title}", ""])
                    lines.extend(f"- {value}" for value in values)
                    lines.append("")
            lines.extend([f"**Card confidence:** {card.get('confidence', '')} · **status:** {card.get('status', '')}", ""])
        else:
            lines.extend(["## Book card", "", "_Not compiled yet._", ""])
        if fs:
            lines.extend(["## Frameworks", ""])
            for framework in fs:
                lines.append(
                    f"- [[Frameworks/{names.framework(framework.get('framework_id', ''), framework.get('name', ''))}"
                    f"|{framework.get('name', 'Untitled framework')}]] · {framework.get('one_liner', '')}"
                )
            lines.append("")
        book_claims = claims_by_book.get(book_id, [])
        if book_claims:
            lines.extend(["## Claims", ""])
            for claim in book_claims[:80]:
                claim_name = names.claim(claim.get("claim_id", ""))
                lines.append(
                    f"- [[Claims/{claim_name}]] · {claim.get('subject', '')} "
                    f"{claim.get('predicate', '')} {claim.get('object', '')} `[{claim.get('status', '')}]`"
                )
            if len(book_claims) > 80:
                lines.append(f"- _… {len(book_claims) - 80} more claims omitted from this note._")
            lines.append("")
        if entity_ids:
            lines.extend(["## Entities", ""])
            for entity_id in entity_ids:
                detail = entity_details.get(entity_id, {})
                lines.append(
                    f"- [[Entities/{names.entity(entity_id, detail.get('canonical_name', ''))}"
                    f"|{detail.get('canonical_name', entity_id)}]]"
                )
            lines.append("")
        chapter_coverage = card.get("chapter_coverage") or []
        if chapter_coverage:
            lines.extend(["## Chapter coverage", ""])
            for chapter in chapter_coverage:
                lines.append(f"### {chapter.get('chapter', chapter.get('title', ''))}")
                lines.append("")
                lines.extend(_citation_lines([chapter], names, store, default_book_id=book_id))
        lines.extend(["## Backlinks", "", "- [[BookCompiler MOC]]", ""])
        emit(f"Books/{names.book(book_id, book.get('title', ''))}.md", "\n".join(lines))

    for framework in all_frameworks:
        if selected and framework.get("book_id") not in selected:
            continue
        fw_id = framework.get("framework_id", "")
        book_id = framework.get("book_id", "")
        book = store.get_book(book_id) or {}
        lines = [
            _frontmatter(
                {
                    "generator": "bookcompiler",
                    "type": "framework",
                    "framework_id": fw_id,
                    "book_id": book_id,
                    "name": framework.get("name", ""),
                    "lenses": framework.get("lenses", []),
                    "confidence": framework.get("confidence", ""),
                    "status": framework.get("status", ""),
                    "tags": ["bookcompiler/framework"] + [f"lens/{item}" for item in framework.get("lenses", [])],
                    "updated_at": utc_now(),
                }
            ),
            "",
            f"# {framework.get('name', 'Untitled framework')}",
            "",
            f"> {framework.get('one_liner', '')}",
            "",
            f"Source: [[Books/{names.book(book_id, book.get('title', ''))}|{book.get('title', book_id)}]]",
            "",
        ]
        for title, key in [
            ("Applicable when", "applicable_when"),
            ("Inputs", "inputs"),
            ("Steps", "steps"),
            ("Outputs", "outputs"),
            ("Failure modes", "failure_modes"),
            ("Counterexamples", "counterexamples"),
        ]:
            values = framework.get(key) or []
            if values:
                lines.extend([f"## {title}", ""])
                lines.extend(f"- {value}" for value in values)
                lines.append("")
        related = framework.get("related_frameworks") or []
        if related:
            lines.extend(["## Related frameworks", ""])
            for related_id in related:
                related_fw = store.get_framework(str(related_id)) or {}
                lines.append(
                    f"- [[Frameworks/{names.framework(str(related_id), related_fw.get('name', str(related_id)))}"
                    f"|{related_fw.get('name', related_id)}]]"
                )
            lines.append("")
        citations = framework.get("citations") or []
        if citations:
            lines.extend(["## Source citations", ""])
            lines.extend(_citation_lines(citations, names, store, default_book_id=book_id))
        lines.extend(["## Backlinks", "", "- [[BookCompiler MOC]]", ""])
        emit(f"Frameworks/{names.framework(fw_id, framework.get('name', ''))}.md", "\n".join(lines))

    for claim in claims:
        claim_id = claim.get("claim_id", "")
        book_id = claim.get("book_id", "")
        detail = store.get_claim(claim_id) or claim
        subject_entity_id = str(claim.get("subject_entity_id", ""))
        lines = [
            _frontmatter(
                {
                    "generator": "bookcompiler",
                    "type": "claim",
                    "claim_id": claim_id,
                    "book_id": book_id,
                    "status": claim.get("status", ""),
                    "confidence": claim.get("confidence", 0),
                    "polarity": claim.get("polarity", 1),
                    "tags": ["bookcompiler/claim", f"claim-status/{claim.get('status', '')}"],
                    "updated_at": utc_now(),
                }
            ),
            "",
            f"# {claim.get('subject', '')} {claim.get('predicate', '')} {claim.get('object', '')}",
            "",
            f"**Status:** `{claim.get('status', '')}` · **Confidence:** {claim.get('confidence', '')} · "
            f"**Polarity:** {claim.get('polarity', 1)}",
            "",
        ]
        conditions = claim.get("conditions") or []
        if conditions:
            lines.extend(["## Conditions", ""])
            lines.extend(f"- {condition}" for condition in conditions)
            lines.append("")
        if claim.get("resolution"):
            lines.extend(["## Resolution", "", str(claim["resolution"]), ""])
        lines.extend(["## Exact quote", ""])
        lines.extend(_quote(claim.get("quote", "")))
        lines.extend(
            [
                "",
                f"Source: [[Books/{names.book(book_id, (store.get_book(book_id) or {}).get('title', book_id))}"
                f"|{(store.get_book(book_id) or {}).get('title', book_id)}]]"
                + (f" · {claim.get('chapter_title', '')}" if claim.get("chapter_title") else "")
                + (f" · p.{claim.get('page')}" if claim.get("page") not in (None, "") else ""),
                "",
            ]
        )
        if subject_entity_id:
            entity = store.get_entity(subject_entity_id) or {}
            lines.append(
                f"Subject entity: [[Entities/{names.entity(subject_entity_id, entity.get('canonical_name', subject_entity_id))}"
                f"|{entity.get('canonical_name', subject_entity_id)}]]"
            )
            lines.append("")
        relations = detail.get("relations") or []
        if relations:
            lines.extend(["## Relations", ""])
            for relation in relations:
                other_id = (
                    relation.get("dst_claim_id")
                    if relation.get("src_claim_id") == claim_id
                    else relation.get("src_claim_id")
                )
                other = store.get_claim(str(other_id)) or {}
                lines.append(
                    f"- `{relation.get('relation', '')}` · [[Claims/{names.claim(str(other_id))}]] "
                    f"({other.get('subject', '')} {other.get('predicate', '')} {other.get('object', '')})"
                )
            lines.append("")
        lines.extend(["## Backlinks", "", "- [[BookCompiler MOC]]", ""])
        emit(f"Claims/{names.claim(claim_id)}.md", "\n".join(lines))

    for entity in entities:
        entity_id = entity["entity_id"]
        detail = entity_details.get(entity_id, store.get_entity(entity_id) or entity)
        mentions = detail.get("mentions") or []
        book_ids = sorted({mention.get("book_id", "") for mention in mentions if mention.get("book_id")})
        lines = [
            _frontmatter(
                {
                    "generator": "bookcompiler",
                    "type": "entity",
                    "entity_id": entity_id,
                    "canonical_name": detail.get("canonical_name", ""),
                    "entity_type": detail.get("entity_type", ""),
                    "aliases": detail.get("aliases", []),
                    "book_count": len(book_ids),
                    "mentions": len(mentions),
                    "tags": ["bookcompiler/entity", f"entity-type/{detail.get('entity_type', 'concept')}"],
                    "updated_at": utc_now(),
                }
            ),
            "",
            f"# {detail.get('canonical_name', entity_id)}",
            "",
            f"> {detail.get('summary', '') or 'No summary recorded.'}",
            "",
        ]
        if book_ids:
            lines.extend(["## Books", ""])
            for book_id in book_ids:
                book = store.get_book(book_id) or {}
                lines.append(f"- [[Books/{names.book(book_id, book.get('title', book_id))}|{book.get('title', book_id)}]]")
            lines.append("")
        relations = detail.get("relations") or []
        if relations:
            lines.extend(["## Relations", ""])
            for relation in relations:
                other_id = (
                    relation.get("dst_entity_id")
                    if relation.get("src_entity_id") == entity_id
                    else relation.get("src_entity_id")
                )
                other = store.get_entity(str(other_id)) or {}
                lines.append(
                    f"- `{relation.get('relation', '')}` · [[Entities/{names.entity(str(other_id), other.get('canonical_name', str(other_id)))}"
                    f"|{other.get('canonical_name', other_id)}]] (weight {relation.get('weight', '')})"
                )
            lines.append("")
        if mentions:
            lines.extend(["## Mentions", ""])
            for mention in mentions[:30]:
                lines.append(
                    f"- [[Books/{names.book(mention.get('book_id', ''), mention.get('book_title', ''))}"
                    f"|{mention.get('book_title', '')}]] · {mention.get('chapter_title', '')}"
                    + (f" · p.{mention.get('page_start')}" if mention.get("page_start") not in (None, "") else "")
                )
            if len(mentions) > 30:
                lines.append(f"- _… {len(mentions) - 30} more mentions omitted._")
            lines.append("")
        lines.extend(["## Backlinks", "", "- [[BookCompiler MOC]]", ""])
        emit(f"Entities/{names.entity(entity_id, detail.get('canonical_name', ''))}.md", "\n".join(lines))

    for analysis in analyses:
        analysis_id = analysis.get("analysis_id", "")
        packet = store.get_analysis(analysis_id) or analysis
        evaluations = store.list_reading_evaluations(analysis_id=analysis_id, limit=1)
        lines = [
            _frontmatter(
                {
                    "generator": "bookcompiler",
                    "type": "analysis",
                    "analysis_id": analysis_id,
                    "question": packet.get("question", ""),
                    "lenses": packet.get("lenses", []),
                    "status": packet.get("status", ""),
                    "reading_score": evaluations[0].get("total") if evaluations else None,
                    "tags": ["bookcompiler/analysis"],
                    "updated_at": utc_now(),
                }
            ),
            "",
            render_memo(packet),
            "",
        ]
        if evaluations:
            evaluation = evaluations[0]
            lines.extend(
                [
                    "## Reading evaluation",
                    "",
                    f"- Total: **{evaluation.get('total', 0)}/100**",
                    f"- Evaluator: `{evaluation.get('evaluator', '')}`",
                    f"- Rubric: `{evaluation.get('rubric_version', '')}`",
                    "",
                ]
            )
            for key, score in (evaluation.get("scores") or {}).items():
                lines.append(f"- `{key}`: {score}/10")
            lines.append("")
        lines.extend(["## Backlinks", "", "- [[BookCompiler MOC]]", ""])
        emit(f"Analyses/{names.analysis(analysis_id)}.md", "\n".join(lines))

    moc = [
        _frontmatter({"generator": "bookcompiler", "type": "moc", "updated_at": utc_now(), "tags": ["bookcompiler/moc"]}),
        "",
        "# BookCompiler MOC",
        "",
        "This folder is generated by BookCompiler. Notes are safe to read and link; "
        "edit the source library rather than hand-editing generated notes if you want changes to persist.",
        "",
        "## Counts",
        "",
        f"- Books: {len(books)}",
        f"- Frameworks: {len(all_frameworks) if not selected else sum(len(frameworks_by_book.get(book['book_id'], [])) for book in books)}",
        f"- Claims: {len(claims)}",
        f"- Entities: {len(entities)}",
        f"- Analyses: {len(analyses)}",
        "",
        "## Books",
        "",
    ]
    for book in books:
        moc.append(f"- [[Books/{names.book(book['book_id'], book.get('title', ''))}|{book.get('title', '')}]]")
    moc.extend(["", "## Analyses", ""])
    for analysis in analyses:
        moc.append(f"- [[Analyses/{names.analysis(analysis.get('analysis_id', ''))}|{analysis.get('question', '')}]]")
    moc.extend(
        [
            "",
            "## Optional Dataview",
            "",
            "```dataview",
            'TABLE status, learned, frameworks, claims',
            'FROM "BookCompiler/Books"',
            "SORT title ASC",
            "```",
            "",
        ]
    )
    emit("BookCompiler MOC.md", "\n".join(moc))

    counts = {
        "books": len(books),
        "frameworks": sum(len(frameworks_by_book.get(book["book_id"], [])) for book in books),
        "claims": len(claims),
        "entities": len(entities),
        "analyses": len(analyses),
    }
    manifest = {
        "generator": "bookcompiler",
        "generated_at": utc_now(),
        "root": str(root),
        "counts": counts,
        "written": sorted(written),
        "skipped": sorted(skipped),
        "preserved_user_edits": sorted(preserved),
        "conflicts": sorted(conflicts),
        "hashes": hashes,
    }
    _write(root / ".bookcompiler-export.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest
