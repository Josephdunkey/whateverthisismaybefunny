# Validation rules

1. Every citation quote must exist verbatim in the exported chapter text.
2. A framework card must include applicability conditions and failure modes.
3. A complete analysis must include a conclusion.
4. A cross-lens analysis must record at least one conflict or explicitly state that none was found.
5. Legal-lens output must be marked `not_legal_advice: true`.
6. Never silently drop a missing lens. Record it as a coverage gap.
7. Never average conflicting lens conclusions. State the conflict and the conditions under which one lens dominates.
8. `heuristic` compilation is a demo fallback. Use an agent-written compilation patch for real books.
## V2 additional rules

9. Book-card chapter coverage citations must also pass exact-quote validation.
10. Analysis citations are collected from top-level citations, hypothesis supporting evidence, and counterevidence citations. All are checked.
11. A complete legal-lens analysis must set `not_legal_advice: true`; otherwise the patch is rejected before saving.
12. A complete cross-lens analysis should record a conflict or explicitly state that none was found.
13. A self-evolution proposal must cite feedback IDs, state a risk, state a rollback, and pass through an explicit decision state.
14. Preference weighting may change ranking, but it must never change source text, exact quotes, or validation rules.
15. Memory recall is context, not evidence. Never cite a memory lesson as if it were a book passage.