---
name: book-compiler
description: Compile books into cited judgment frameworks and use them to analyze new events. Use when the user wants an agent to "read" a library, build a domain expert from books, compare multiple books on a new event, or produce a cited analysis memo. Not for simple book summaries, role-playing an author, or unsourced chat.
---

# BookCompiler

Turn a local book library into a **cited judgment system**.

A book is not a memory. A book is compiled into:

- a **book card** (what the book argues, assumes, and cannot do),
- **framework cards** (when to use a method, how, and when it fails),
- **evidence chunks** (exact quotes with chapter/page provenance).

Memory is separate: it stores the user's preferences, feedback, and past judgments.

## Non-negotiable truth contract

Every factual claim in a book card, framework card, or analysis must have:

- `book_id`
- `chapter`
- `page` when available
- exact `quote`
- a clear distinction between **source quote** and **inference**

If a quote cannot be found in the exported chapter text, do not store it. Mark the claim `unverified` or remove it.

Never invent a citation. Never average away a conflict between lenses. Legal-lens output must say it is analysis, not legal advice.

## Workflow

### 1. Initialize and ingest

```bash
bookcompiler init
bookcompiler ingest <path> --title "<title>" --author "<author>" --discipline economics --discipline politics --discipline law
```

Supported formats: `.txt`, `.md`, `.pdf`, `.epub`. The library is local SQLite.

### 2. Export the book for close reading

```bash
bookcompiler export-text <book_id> --out .bookcompiler/books/<book_id>
```

Read `structure.md` and the chapter files. Do not compile from memory or from the title alone.

### 3. Write a compilation patch

Create `compilation.json` following `references/compilation-patch.schema.json`.

A book card must state:

- one-line thesis,
- core questions,
- key concepts,
- assumptions,
- limitations,
- best-for and not-for,
- chapter coverage with a citation for each chapter,
- lenses,
- confidence.

A framework card must state:

- name and one-liner,
- lenses,
- applicable-when conditions,
- inputs,
- steps,
- outputs,
- failure modes,
- counterexamples,
- citations,
- related frameworks,
- confidence.

Prefer 3-8 high-value frameworks over a summary of every paragraph. A framework must be actionable: a reader should be able to apply it to a new event.

### 4. Compile and validate

```bash
bookcompiler compile <book_id> --patch compilation.json
bookcompiler validate --book <book_id>
```

If validation reports an unsupported quote, fix the quote or remove the claim. Do not bypass validation.

### 5. Choose the selection mode

There are three modes:

1. `auto` — the agent selects books and frameworks from the library.
2. `direction` — the user specifies a direction, not exact books.
3. `books` — the user specifies exact books.

For modes 2 and 3, always show the selection card first:

```bash
bookcompiler plan --mode direction --query "<event>" --direction "<direction>" --lenses economics politics law
```

Present:

- specified books/frameworks,
- recommended books/frameworks,
- reasons,
- coverage gaps.

Then ask the user to choose exactly one:

- `specified` — only what the user specified,
- `specified+recommended` — user scope plus agent recommendations,
- `recommended` — only the agent's recommendation.

Do not run the analysis before the user chooses in modes 2 and 3.

### 6. Create the analysis packet

```bash
bookcompiler analyze --mode <mode> --query "<event>" --lenses economics politics law --confirm <choice>
```

This creates a draft `AnalysisPacket`. The draft contains selected frameworks, evidence, and draft hypotheses.

Now reason over the packet. Fill:

- `hypotheses`: competing explanations, each tied to a lens and framework,
- `counterevidence`: evidence that weakens each hypothesis,
- `cross_lens_conflicts`: where economics, politics, and law disagree; do not average them,
- `conclusion`: a conditional judgment, not a confident prediction,
- `uncertainty`: what would change the conclusion,
- `next_checks`: observable checks,
- `citations`: only quotes that exist in the source,
- `jurisdiction`: required for legal analysis.

Save the patch as `analysis-patch.json` following `references/analysis-patch.schema.json`.

```bash
bookcompiler analysis-apply <analysis_id> --patch analysis-patch.json
bookcompiler validate --analysis <analysis_id>
bookcompiler render <analysis_id> --out analysis.md
```

### 7. Record feedback for V2

```bash
bookcompiler feedback --analysis <analysis_id> --rating 1-5 --note "<what was wrong or missing>"
```

V1 records feedback only; V2 adds memory recall and controlled evolution. It still does not auto-modify the library.

## Cross-disciplinary rules

Use lenses as questions, not as three separate essays:

- **Economics**: incentives, constraints, prices, externalities, distribution, second-order effects.
- **Politics**: power, coalitions, veto players, legitimacy, implementation capacity.
- **Law**: authority, jurisdiction, procedure, rights, liability, precedent, enforceability.

If the lenses disagree, write the disagreement explicitly and state which lens dominates under what conditions.

## Selection and coverage

The agent may recommend books outside the current library, but must not silently ingest them. Present a candidate list and wait for approval.

Show the user:

- which books were used,
- which frameworks were used,
- why they were selected,
- what lenses are covered,
- what gaps remain.

## References

- `references/compilation-patch.schema.json`
- `references/book-card.schema.json`
- `references/framework-card.schema.json`
- `references/analysis-packet.schema.json`
- `references/analysis-patch.schema.json`
- `references/validation-rules.md`
- `references/self-evolution-v2.md`
## V2: controlled self-evolution

V2 separates five layers:

1. source evidence (RAG over exact chunks),
2. book/framework cards,
3. structured feedback and memory,
4. analysis packets,
5. versioned evolution proposals.

### Structured feedback

```bash
bookcompiler feedback --analysis <analysis_id> --rating 2 \
  --error lens_omission --error overconfidence \
  --prefer-book <book_id> --prefer-framework <framework_id> \
  --missing-evidence "<what was missing>" \
  --outcome "<what the user did next>" \
  --note "<short diagnosis>"
```

Error labels:

- `retrieval_miss`
- `compilation_error`
- `framework_misapplication`
- `citation_error`
- `lens_omission`
- `conflict_suppression`
- `overconfidence`
- `taste_mismatch`

### Memory recall

```bash
bookcompiler memory --query "<new event>" --lenses economics politics law
```

This is Hindsight-style recall over feedback and memory. It does not store whole books. Source claims still require citations from the library.

### Evolution proposals

```bash
bookcompiler evolution-propose
bookcompiler evolution-list
bookcompiler evolution-decide <proposal_id> --status accepted --note "reviewed"
bookcompiler evolution-decide <proposal_id> --status shadow --note "run in shadow"
bookcompiler evolution-decide <proposal_id> --status promoted --replay-report replay-report.json --note "clean structural replay"
```

Allowed statuses: `accepted`, `rejected`, `shadow`, `promoted`, `rolled_back`.

Rules:

- A proposal must cite specific feedback IDs.
- A proposal must state risk and rollback.
- Status change is not automatic application.
- No proposal may weaken exact-quote validation, legal disclaimers, or conflict handling.
- Promotion is gated by the CLI: `proposed -> accepted -> shadow -> promoted`, and `promoted` requires a clean `replay` report via `--replay-report`. Any promoted proposal can be `rolled_back`.

### Replay

```bash
bookcompiler replay cases.json --out replay-report.json
```

The current replay is a structural regression harness. It checks selection, citation validity, lens coverage, and structural errors. It is not a substitute for blind quality evaluation.

### Reading-effectiveness scoring

```bash
bookcompiler reading-eval --analysis <analysis_id> \
  --evaluator llm_judge \
  --score source_fidelity=8 \
  --score retrieval_coverage=7 \
  --score cross_book_synthesis=4 \
  --note "only one book was genuinely used"

bookcompiler reading-report --format markdown
bookcompiler reading-eval-list --analysis <analysis_id>
bookcompiler reading-propose --min-support 3
```

The rubric has nine weighted dimensions (total 100): source fidelity,
retrieval coverage, framework fit, cross-book synthesis, cross-lens integration,
conflict handling, calibration, actionability, and failure-mode awareness.
Scores are 0-10 per dimension. Unspecified dimensions keep deterministic
auto-proxies, which are triage signals only. A weak dimension becomes an advisory
evolution proposal; it does not silently rewrite cards or prompts.

### Obsidian export

```bash
bookcompiler obsidian-export --vault "D:\\MyVault"
```

This writes only inside `<vault>/BookCompiler/` by default: one note per book,
framework, claim, entity, and analysis, plus a MOC and YAML frontmatter. It never
touches notes outside that folder. Use `--no-claims`, `--no-entities`,
`--no-analyses`, or `--book <book_id>` to narrow the export.

### Observability

```bash
bookcompiler dashboard --out dashboard.md
bookcompiler graph --node <analysis_id>
bookcompiler coverage
```

The dashboard shows the learned library, book cards, frameworks, analyses, feedback, and evolution proposals.

### Two-level selection

Books and FrameworkCards are both selectable:

```bash
bookcompiler plan --mode books --query "<event>" \
  --books <book_id> --frameworks <framework_id> \
  --lenses economics politics law --format text
```

The selection card must show specified vs recommended books/frameworks, reasons, coverage gaps, and the three consent choices.