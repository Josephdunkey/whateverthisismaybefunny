from __future__ import annotations

from typing import Any


def _row(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _proposal_dict(proposal: Any) -> dict[str, Any]:
    return proposal.to_dict() if hasattr(proposal, "to_dict") else dict(proposal)


def render_source_recommendations(
    recommendations: list[dict[str, Any]],
    heading_level: int = 2,
    empty_text: str = "None detected in the current library.",
) -> str:
    heading = "#" * max(1, heading_level)
    lines = [f"{heading} Suggested sources to download and ingest", ""]
    if not recommendations:
        lines.append(empty_text)
        lines.append("")
        return "\n".join(lines)
    lines.append(
        "These authoritative sources match the question but are not in the library. "
        "Download an official current version, verify it, and ingest it before treating "
        "the related lens as fully covered."
    )
    lines.append("")
    for source in recommendations:
        priority = str(source.get("priority", "medium")).upper()
        source_type = str(source.get("source_type", "source"))
        jurisdiction = str(source.get("jurisdiction", ""))
        title = source.get("title", "Untitled source")
        suffix = f", {jurisdiction}" if jurisdiction else ""
        lines.append(f"- **[{priority}] {title}** (`{source_type}`{suffix})")
        why = source.get("why") or source.get("reason")
        if why:
            lines.append(f"  - Why: {why}")
        matched_terms = source.get("matched_terms", [])
        if matched_terms:
            lines.append(f"  - Matched terms: {', '.join(str(item) for item in matched_terms)}")
        disciplines = source.get("suggested_disciplines", [])
        if disciplines:
            lines.append(f"  - Suggested disciplines: {', '.join(str(item) for item in disciplines)}")
        official_source = source.get("official_source")
        if official_source:
            lines.append(f"  - Official version: {official_source}")
        version_note = source.get("version_note")
        if version_note:
            lines.append(f"  - Version check: {version_note}")
        ingest_hint = source.get("ingest_hint")
        if ingest_hint:
            lines.append(f"  - Ingest: `{ingest_hint}`")
    lines.append("")
    return "\n".join(lines)


def render_selection_card(proposal: Any) -> str:
    data = _proposal_dict(proposal)
    lines = ["# Selection card", ""]
    lines.append(f"- Mode: {data.get('mode', '')}")
    lines.append(f"- Query: {data.get('query', '')}")
    lines.append(f"- Lenses: {', '.join(data.get('lenses', []))}")
    if data.get("direction"):
        lines.append(f"- Direction: {data.get('direction')}")
    lines.append(f"- Rationale: {data.get('rationale', '')}")
    lines.append("")
    lines.append("## Specified books")
    lines.append("")
    if not data.get("specified_books"):
        lines.append("_None._")
    for book in data.get("specified_books", []):
        lines.append(f"- {book.get('title', '')} - {book.get('reason', '')}")
    lines.append("")
    lines.append("## Recommended books")
    lines.append("")
    if not data.get("recommended_books"):
        lines.append("_None._")
    for book in data.get("recommended_books", []):
        lines.append(f"- {book.get('title', '')} - {book.get('reason', '')}")
    lines.append("")
    lines.append("## Specified frameworks")
    lines.append("")
    if not data.get("specified_frameworks"):
        lines.append("_None (the agent will choose frameworks inside the specified books)._")
    for framework in data.get("specified_frameworks", []):
        lines.append(f"- {framework.get('name', '')} - {framework.get('reason', '')}")
    lines.append("")
    lines.append("## Recommended frameworks")
    lines.append("")
    if not data.get("recommended_frameworks"):
        lines.append("_None._")
    for framework in data.get("recommended_frameworks", []):
        lines.append(f"- {framework.get('name', '')} - {framework.get('reason', '')}")
    lines.append("")
    gaps = data.get("coverage_gaps", [])
    lines.append("## Coverage gaps")
    lines.append("")
    if gaps:
        lines.append(", ".join(gaps))
    elif data.get("source_recommendations"):
        lines.append("No missing discipline labels, but authoritative-source gaps exist below.")
    else:
        lines.append("None detected in the current library.")
    lines.append("")
    lines.extend(render_source_recommendations(data.get("source_recommendations", [])).splitlines())
    lines.append("")
    if data.get("requires_confirmation"):
        lines.append("## Consent gate")
        lines.append("")
        lines.append("Choose exactly one before running the analysis:")
        lines.append("")
        lines.append("- `specified`: only your specified scope")
        lines.append("- `specified+recommended`: your scope plus the agent's additions")
        lines.append("- `recommended`: only the agent's recommendation")
        lines.append("")
    return "\n".join(lines)


def render_memo(packet: dict[str, Any]) -> str:
    lines = [f"# {packet.get('question', 'Untitled analysis')}", ""]
    lines.append(f"**Mode:** {packet.get('mode', '')}  ")
    lines.append(f"**Lenses:** {', '.join(packet.get('lenses', []))}  ")
    lines.append(f"**Status:** {packet.get('status', 'draft')}")
    lines.append("")
    selection = packet.get("selection", {})
    lines.append("## Selection card")
    lines.append("")
    lines.append(f"- Choice: {selection.get('choice', '')}")
    for book in selection.get("books", []):
        lines.append(f"- {book.get('title', '')} - {book.get('reason', '')}")
    if selection.get("coverage_gaps"):
        lines.append(f"- Coverage gaps: {', '.join(selection['coverage_gaps'])}")
    lines.append("")
    if selection.get("source_recommendations"):
        lines.extend(render_source_recommendations(selection["source_recommendations"]).splitlines())
        lines.append("")
    lines.append("## Framework cards used")
    lines.append("")
    frameworks = packet.get("frameworks", [])
    if not frameworks:
        lines.append("_No framework cards selected._")
    for framework in frameworks:
        lines.append(f"### {framework.get('name', 'Untitled framework')}")
        lines.append(f"- One-liner: {framework.get('one_liner', '')}")
        lines.append(f"- Lenses: {', '.join(framework.get('lenses', []))}")
        if framework.get("applicable_when"):
            lines.append(f"- Applies when: {'; '.join(framework['applicable_when'])}")
        if framework.get("failure_modes"):
            lines.append(f"- Failure modes: {'; '.join(framework['failure_modes'])}")
        lines.append("")
    memory_context = packet.get("memory_context", [])
    if memory_context:
        lines.append("## Memory lessons recalled")
        lines.append("")
        for lesson in memory_context:
            if lesson.get("source") == "feedback":
                labels = ", ".join(lesson.get("error_labels", [])) or "no error label"
                lines.append(
                    f"- Prior feedback ({lesson.get('rating')}/5, {labels}): {lesson.get('note', '') or 'no note'}"
                )
            else:
                lines.append(f"- Memory `{lesson.get('kind', '')}`: {lesson.get('key', '')}")
        lines.append("")
    claims = packet.get("claims", [])
    if claims:
        lines.append("## Claim graph")
        lines.append("")
        lines.append("| Book | Subject | Predicate | Object | Confidence |")
        lines.append("|---|---|---|---|---:|")
        for claim in claims[:12]:
            lines.append(
                f"| {_row(claim.get('book_title', claim.get('book_id', '')))} | "
                f"{_row(claim.get('subject', ''))} | {_row(claim.get('predicate', ''))} | "
                f"{_row(claim.get('object', ''))} | {_row(claim.get('confidence', ''))} |"
            )
        lines.append("")
    lines.append("## Evidence")
    lines.append("")
    lines.append("| Book | Chapter | Page | Quote |")
    lines.append("|---|---|---:|---|")
    for citation in packet.get("citations", [])[:12]:
        lines.append(
            f"| {_row(citation.get('book_id', ''))} | {_row(citation.get('chapter', ''))} | {_row(citation.get('page', ''))} | {_row(citation.get('quote', ''))} |"
        )
    lines.append("")
    lines.append("## Hypotheses")
    lines.append("")
    hypotheses = packet.get("hypotheses", [])
    if not hypotheses:
        lines.append("_Draft: agent synthesis required._")
    for hypothesis in hypotheses:
        lines.append(f"- **{hypothesis.get('lens', '')}**: {hypothesis.get('claim', '')}")
    lines.append("")
    lines.append("## Counterevidence")
    lines.append("")
    if not packet.get("counterevidence"):
        lines.append("_Draft: agent synthesis required._")
    for item in packet.get("counterevidence", []):
        lines.append(f"- {item.get('description', item)}")
    lines.append("")
    lines.append("## Cross-lens conflicts")
    lines.append("")
    if not packet.get("cross_lens_conflicts"):
        lines.append("_None recorded._")
    for conflict in packet.get("cross_lens_conflicts", []):
        lines.append(f"- {conflict.get('description', conflict)}")
    lines.append("")
    lines.append("## Conclusion")
    lines.append("")
    lines.append(packet.get("conclusion") or "_Draft: agent synthesis required._")
    lines.append("")
    lines.append("## Uncertainty")
    lines.append("")
    lines.append(packet.get("uncertainty") or "_Draft._")
    lines.append("")
    lines.append("## Next checks")
    lines.append("")
    for check in packet.get("next_checks", []):
        lines.append(f"- {check}")
    lines.append("")
    if packet.get("not_legal_advice"):
        lines.append("> This is analysis, not legal advice. Verify jurisdiction and applicable law.")
        lines.append("")
    return "\n".join(lines)
def render_dashboard(store: Any) -> str:
    coverage = store.coverage()
    books = store.list_books()
    lines = ["# BookCompiler dashboard", "", "## Coverage", ""]
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    for key in ["books", "compiled_books", "frameworks", "analyses", "feedback", "evolution_proposals"]:
        lines.append(f"| {key} | {coverage.get(key, 0)} |")
    lines.append("")
    lines.append("### Disciplines")
    lines.append("")
    for name, count in sorted(coverage.get("disciplines", {}).items()):
        lines.append(f"- {name}: {count}")
    lines.append("")
    lines.append("### Lenses")
    lines.append("")
    for name, count in sorted(coverage.get("lenses", {}).items()):
        lines.append(f"- {name}: {count}")
    lines.append("")
    lines.append("## Library")
    lines.append("")
    lines.append("| Book | Status | Disciplines | Frameworks |")
    lines.append("|---|---|---|---:|")
    for book in books:
        frameworks = store.list_frameworks(book_ids=[book["book_id"]])
        lines.append(
            f"| {_row(book['title'])} | {book.get('status', '')} | {_row(', '.join(book.get('disciplines', [])))} | {len(frameworks)} |"
        )
    lines.append("")
    for book in books:
        card = store.get_book_card(book["book_id"])
        frameworks = store.list_frameworks(book_ids=[book["book_id"]])
        lines.append(f"### {book['title']}")
        lines.append("")
        if card:
            lines.append(f"- Thesis: {card.get('one_line_thesis', '')}")
            lines.append(f"- Confidence: {card.get('confidence', '')} / status: {card.get('status', '')}")
            lines.append(f"- Best for: {', '.join(card.get('best_for', []))}")
            lines.append(f"- Not for: {', '.join(card.get('not_for', []))}")
            lines.append(f"- Limitations: {', '.join(card.get('limitations', []))}")
        else:
            lines.append("- Not compiled yet.")
        if frameworks:
            lines.append("- Frameworks:")
            for framework in frameworks:
                lines.append(f"  - {framework.get('name', '')} [{', '.join(framework.get('lenses', []))}]")
        lines.append("")
    lines.append("## Recent analyses")
    lines.append("")
    analyses = store.list_analyses()[:8]
    if not analyses:
        lines.append("_No analyses yet._")
    for analysis in analyses:
        lines.append(
            f"- `{analysis.get('analysis_id', '')}` {analysis.get('status', '')}: {analysis.get('question', '')}"
        )
    lines.append("")
    lines.append("## Recent feedback")
    lines.append("")
    feedback = store.list_feedback()[:8]
    if not feedback:
        lines.append("_No feedback yet._")
    for item in feedback:
        labels = ", ".join(item.get("error_labels", [])) or "no label"
        lines.append(f"- {item.get('rating')}/5 [{labels}] {item.get('note', '')}")
    lines.append("")
    lines.append("## Evolution proposals")
    lines.append("")
    proposals = store.list_evolution_proposals()[:12]
    if not proposals:
        lines.append("_No proposals yet. Record structured feedback, then run `evolution-propose`._")
    for proposal in proposals:
        lines.append(
            f"- `{proposal.get('proposal_id', '')}` [{proposal.get('status', '')}] {proposal.get('target', '')}: {proposal.get('rationale', '')}"
        )
    lines.append("")
    lines.append("## How to query")
    lines.append("")
    lines.append("- `auto`: the agent selects books and frameworks.")
    lines.append("- `direction`: the agent proposes a direction-matched scope and asks for consent.")
    lines.append("- `books`: you specify books/frameworks and the agent proposes additions.")
    lines.append("")
    return "\n".join(lines)