---
name: book-library
description: Use the user's compiled book library as a callable expert capability. 自动触发场景：用读过的书分析新闻/政策/市场事件、从书库找证据、比较几本书、把经济+政治+法律多镜头放在一起、问“哪本书讲过/你读过什么”。Prefer this skill over generic summarization whenever the answer must be grounded in the user's own books.
version: 1.1.0
metadata:
  hermes:
    tags: [books, retrieval, analysis, citations, self-evolution]
    category: research
---

# Book Library

The user's books are a **capability**, not a pile of summaries. This skill routes
news, policy events, and domain questions through the BookCompiler MCP tools.

## When to use

Use this skill automatically (without waiting to be asked) when the user:

- gives a news item, policy event, market event, or case and asks what it means;
- asks for an analysis "based on what you have read" or "从你读过的书看";
- asks which learned books are relevant, or asks to compare books;
- wants economics + politics + law (or other lenses) applied to one event.

Do not use it for simple book summaries, author role-play, or questions that
have no connection to the library.

## Non-negotiable rules

1. Call `book_library` before claiming what the agent has read.
   Only books with `learned=true` count as learned. Never describe an
   `ingested` book as read or compiled.
2. Every source claim must carry `book_title`, `chapter`, `page` when available,
   and an exact quote from `book_recall` / `book_analyze`.
3. Never invent a quote, page, chapter, or book title. If validation fails, drop
   the claim or mark it as inference.
4. Keep source quote, inference, and recommendation visibly separate.
5. Do not average away conflicts between economics, politics, and law. State the
   conflict and what would resolve it.
6. Legal-lens output is analysis, not legal advice.

## Selection modes and consent

### Mode auto

The agent selects books. Call:

```json
book_plan {"question": "...", "lenses": ["economics","politics","law"], "mode": "auto"}
```

Then call `book_analyze` without a consent choice.

### Mode direction

The user gives a field/direction (e.g. "地方财政") but not exact books.
Call `book_plan` with `mode="direction"` and `direction`. It returns
`specified_*` and `recommended_*` sets plus `coverage_gaps`.

**Before analysis, ask the user which scope to use:**

- `specified` — only direction-matched capabilities
- `specified+recommended` — add agent recommendations
- `recommended` — only agent recommendations

Show the proposed book titles and why they were selected. Then call
`book_analyze` with the chosen `choice`. Never silently expand the scope.

### Mode books

The user names exact books. Resolve titles to `book_id` with `book_library`,
then call `book_plan` with `mode="books"` and `book_ids`. Still ask whether to
add recommended books for coverage gaps, then pass the consent choice.

## Domain capability packs (preferred routing layer)

This skill is the **only** host-facing skill. Do not create one skill per book.
Internally, learned knowledge is organized into a few versioned domain packs under
`skills/book-library/references/packs/<domain>/`:

- `PACK.md` - when to use the pack, the reasoning protocol, coverage and gaps
- `frameworks.md` - executable procedures (read only the 1-3 relevant entries)
- `sources.md` - learned books, claims, entities, exact quotes
- `debates.md` - reviewed conflicts and candidate conflicts (they are different)
- `boundaries.md` - each book's assumptions/limitations and each framework's failure modes
- `eval.md` + `eval/golden.jsonl` - coverage evaluation and the judge rubric
- `LOCAL.md` - user-owned notes; rebuilds must never overwrite it
- `pack.json` - machine-readable source of truth for routing

### Route before you answer

For any non-trivial event, policy, market or cross-domain question:

1. Call `book_capability` with `action="route"`, the user's `query`, and any `lenses`.
2. If `requires_confirmation=false` and `selected` is non-empty, load that pack.
3. If `requires_confirmation=true` (weak match, close scores, or high stakes),
   show the top candidates with their score and reasons and ask the user which
   domain to use. Never silently pick one.
4. Load at most two packs. Read `PACK.md` first, then only the relevant
   `frameworks.md` entries, then `sources.md` / `debates.md` when citing.
   If the route result contains `secondary`, you may load it as the second pack
   when the question genuinely needs that lens; still never exceed two packs.
5. Read `LOCAL.md` as user preference, never as a citation.

`book_capability` and `book_plan` are complementary:

- `book_capability` decides *which domain capability* should think about the event.
- `book_plan` decides *which exact books/frameworks* to load inside that domain.
- If their recommendations disagree, state the disagreement instead of merging it.

### Reasoning protocol (must follow in order)

1. Decompose the event: actors, constraints, mechanisms, time horizon.
2. Choose lenses and justify why each is needed.
3. Choose 1-3 frameworks from the pack and state their applicability conditions.
4. Execute the framework steps (inputs -> steps -> outputs); do not quote only conclusions.
5. Cross-book comparison: at least one supporting and one limiting/opposing book,
   or explicitly say the library lacks an opposing source.
6. Conflict handling: present contradictions side by side; do not average them.
7. Boundaries and falsification: state when the conclusion stops holding and which
   indicators would change the judgment.
8. Citation: every factual sentence gets book, chapter/page if available, and an exact quote.
   Mark inference and recommendation separately.

### Adding or updating a pack

- Presets: `book_capability {"action":"presets"}`.
- Create: `book_capability {"action":"build","domain":"political-economy"}`.
- Custom: pass `title`, `description`, `lenses`, `direction`, `book_ids`, `max_books`.
- Only learned/verified books may enter a pack. Ingested-only books are rejected.

Incremental merge, never a full rewrite:

1. `book_capability {"action":"impact","book_id":"..."}` to see affected packs.
2. `book_capability {"action":"update","domain":"...","book_ids":[...],"apply":false}`
   returns a diff and does not write.
3. Show the diff when it adds conflicts, removes items, or changes a core framework.
4. Apply with `apply=true`, then run `action="eval"` and report coverage plus gaps.
5. `LOCAL.md` is preserved; generated files are overwritten by design.

### Evaluation boundaries

- `action="eval"` is **coverage**: it checks whether expected books, frameworks,
  lenses, topics and conflicts are present. It is zero-model and not a quality score.
- `book_reading_eval action="judge"` is an independent model score.
- `book_reading_eval action="score" evaluator="llm_judge"` means the calling agent
  supplied the scores, not a blind judge.
- `auto_proxy` is triage only. Never present it as a human or blind evaluation.

## Answer shape

1. **What the event changes** — one paragraph, no citations needed for framing.
2. **What the books say** — one subsection per lens; each claim cites an exact
   quote with book/chapter/page.
3. **Where the lenses conflict** — explicit, not averaged.
4. **Conditional conclusion** — "if A, then B; if not A, then C".
5. **What would change the judgment** — concrete indicators or documents.
6. **Books used** — list learned books actually cited; distinguish them from
   books merely recommended.

## Memory and self-evolution

- `book_memory` recalls lessons from past feedback. Use it to avoid repeating
  known mistakes, not as a source of facts.
- Record feedback with `book_feedback` only when the user explicitly rates or
  corrects an answer. Do not invent ratings.
- `book_evolution` can propose bounded changes to retrieval/preference weights.
  Promotion requires a clean structural replay. Never promote without the user's
  explicit approval.

## Reading-effectiveness loop (after the final answer)

Do this after the answer is complete, not after the draft scaffolding.

1. Call `book_reading_eval` with `action="score"`, the `analysis_id`, and
   `evaluator="llm_judge"`. Score these nine dimensions from 0 to 10:
   `source_fidelity`, `retrieval_coverage`, `framework_fit`,
   `cross_book_synthesis`, `cross_lens_integration`, `conflict_handling`,
   `calibration`, `actionability`, `failure_mode_awareness`.
2. Be strict. If only one book was genuinely used, `cross_book_synthesis` must
   be 3 or lower. If the answer has no falsification condition,
   `calibration` must be 5 or lower. A polished answer with a weak evidence base
   is not a high score.
3. Put the concrete reason in `note`, and use `error_labels` such as
   `retrieval_miss`, `citation_error`, `lens_omission`, `conflict_suppression`,
   or `overconfidence`.
4. `action="report"` returns the aggregate score and weak dimensions. Use it to
   decide what to practice next, not to flatter the agent.
5. When at least three evaluations agree that a dimension is weak, call
   `action="propose"` and show the user the proposals. Promotion still requires
   replay plus explicit user approval.
6. Auto proxies are triage only. Never present an auto-proxy score as a human
   judgment or a blind benchmark.

## Ingest and compile

- `book_ingest` only accepts a local path. Never download books automatically.
- Ingestion is not learning. To make a book learned, prefer the one-call reader:
  1. `book_learn` with the `book_id` (it samples the whole book, proposes
     frameworks, and verifies every quote/chunk/page against SQLite).
  2. `book_validate` to confirm there are no provenance errors.
  3. If the user wants a hand-authored patch, fall back to
     `book_export_text` -> `book_compile` -> `book_validate`.
- `book_learn` uses the configured BookCompiler reader model (currently MiMo
  when the `mimo` preset is active). Never silently switch to a paid model.
- If the user asks "what have you learned", report only verified/compiled books
  and disclose OCR/coverage limitations.

## V3: GraphRAG, Obsidian, and independent judging

### GraphRAG

- `book_analyze` already uses hybrid + GraphRAG + RRF. The trace is in
  `analysis.retrieval.channels` and `analysis.orchestration`.
- If `book_graphrag action="status"` says the sidecar is missing or stale,
  call `action="build"` before a high-stakes analysis. The sidecar is
  `.bookcompiler\library.graph.db` and never modifies `library.db`.
- Use `action="query"` with `mode="hybrid"` when you need to inspect both
  channels. A graph failure must fall back to hybrid; do not fake graph hits.

### Obsidian

- `book_obsidian action="sync"` is controlled two-way: generated notes are
  export-only, only the Inbox is imported.
- Reader notes returned by `book_obsidian action="notes"` or embedded in
  `book_analyze` are memory context. They are **never** citations.
- Do not quote a reader note as if it were book text. Verify the factual claim
  against `book_recall` first.
- Reviews use `book_obsidian action="reviews"` and `action="grade"`.

### Independent score

- After the final answer is applied (`status=complete`), call
  `book_reading_eval action="judge"` with a local Ollama model.
- `action="score" evaluator="llm_judge"` means *you* are supplying explicit
  scores. `action="judge"` means an independent model is scoring blind.
- Never call `auto_proxy` a blind or human evaluation.
- `action="propose"` creates reading-evolution proposals only from independent
  scores (`llm_judge` / `human` / `mixed`).
- If judge fails, report the failure. Do not substitute proxy scores.