---
name: book-learning-loop
description: Use when the user asks to read/learn a book, evaluate how well a book was learned, give reading feedback, or let the book capability evolve. 自动触发场景：把书入库、读一本书、检查读得怎么样、打分、进化/自我改进、下一本该读什么。This is the closed loop around book_learn; it does not replace book-library for answering domain questions.
version: 1.0.0
metadata:
  hermes:
    tags: [books, learning-loop, evaluation, evolution, self-improvement]
    category: research
---

# Book Learning Loop

A book becomes a capability only after **read → verified → evaluated → measured**.
This skill enforces that loop. Never skip a gate and never describe a proposal as
an improvement.

## The loop

1. **Locate** — `book_library` to confirm the `book_id`, current status and
   whether the book is already compiled. Do not re-ingest an existing book.
2. **Read** — `book_learn {"book_id": "..."}`. It samples the whole book,
   proposes a BookCard + 3–8 frameworks, verifies every quote verbatim against
   the source chunks, and writes only if validation passes.
3. **Verify** — `book_validate {"book_id": "..."}`. Any `error` means the book
   is not learned, regardless of what the reader model claimed.
4. **Evaluate** — `book_reading_eval` with a real judge model. Report the nine
   dimensions and label the result `judge` or `auto_proxy`.
   - `auto_proxy` is triage only. It is **not** a blind human-style review.
   - Never present a proxy score as a judge score.
5. **Collect feedback** — `book_feedback` only when the user actually rates
   something, or when an answer was checked against a cited passage. Never
   invent user ratings.
6. **Evolve** — `book_evolution` proposes bounded changes. Promotion requires
   replay + shadow comparison. Report the proposal id, the metric delta, and
   whether it was promoted, rejected, or rolled back.

## Model routing (cost rule)

- Reading / judging: the configured `BOOKCOMPILER_READER_*` or judge route,
  currently MiMo. Reading with DeepSeek is blocked unless
  `BOOKCOMPILER_READER_ALLOW_DEEPSEEK=1`.
- Memory extraction / Hindsight: local Ollama.
- Never silently switch a reading job to a paid endpoint.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `ingested` | text chunked, not read |
| `compiled` | BookCard + frameworks written |
| `verified` | every citation resolved verbatim to a source chunk (machine check, not human review) |
| `learned` | verified card with at least one framework and no validation errors |

## What to report back

- book title and `book_id`
- number of frameworks and evidence chunks
- validation result (`[]` or the errors)
- evaluation mode (`judge` / `auto_proxy`) and score
- one sentence on what the book can now be used for, and one on its limits
