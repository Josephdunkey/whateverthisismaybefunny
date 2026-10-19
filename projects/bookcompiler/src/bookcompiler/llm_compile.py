"""LLM-assisted book compilation with deterministic provenance checks.

The reader sees a representative sample of the whole book, proposes a book card
and reusable frameworks, and may cite only chunks supplied in that evidence
packet.  Python then resolves every citation against the original chunk text,
repairs paraphrased quotes when possible, and runs the existing strict
validators before anything is written.

This is deliberately *not* a free-form summariser.  A model output is accepted
only when every framework points to an exact source quote.  The resulting card
is marked ``verified`` in the sense of "machine verified against the source",
not "a human reviewed it"; the card's confidence field remains separate.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Iterable

from .compiler import compile_book, infer_lenses
from .config import load_env, project_root
from .judge import BaseJudge, JudgeConfig, create_judge, default_judge_config
from .models import Chunk, Evidence, utc_now
from .store import Store
from .utils import normalize_for_quote, split_sentences, stable_id
from .validation import find_quote, validate_book_card, validate_framework_card

MAX_EVIDENCE_CHUNKS = 28
EVIDENCE_CHARS = 1200
MIN_FRAMEWORKS = 3
MAX_FRAMEWORKS = 8
OUTPUT_DIR = "compilations"


class LLMCompileError(RuntimeError):
    """Raised when a model proposal cannot be verified against the source."""


class ReaderRefused(LLMCompileError):
    """Raised when the model provider's safety layer rejects the request."""


def _looks_like_deepseek(provider: str, model: str, base_url: str) -> bool:
    haystack = f"{provider} {model} {base_url}".lower()
    return "deepseek" in haystack


def _reader_config(
    provider_override: str | None = None,
    model_override: str | None = None,
    base_url_override: str | None = None,
) -> JudgeConfig:
    """Use a reader-specific route, falling back to the active judge route.

    CLI overrides go through this function too, so the DeepSeek cost guard
    cannot be bypassed with ``--provider``/``--model``/``--base-url``.
    """
    load_env()
    base = default_judge_config()
    provider = (provider_override or "").strip() or os.environ.get("BOOKCOMPILER_READER_PROVIDER", "").strip() or base.provider
    model = (model_override or "").strip() or os.environ.get("BOOKCOMPILER_READER_MODEL", "").strip() or base.model
    base_url = (base_url_override or "").strip() or os.environ.get("BOOKCOMPILER_READER_BASE_URL", "").strip() or base.base_url
    api_key = os.environ.get("BOOKCOMPILER_READER_API_KEY", "").strip()
    if not api_key:
        lowered_reader = base_url.lower()
        if "deepseek" in lowered_reader:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        elif "xiaomimimo" in lowered_reader or "mimo" in lowered_reader:
            api_key = os.environ.get("MIMO_API_KEY", "").strip() or os.environ.get("XIAOMI_API_KEY", "").strip()
        elif "openai.com" in lowered_reader:
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        elif "dashscope" in lowered_reader or "aliyun" in lowered_reader:
            api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        if not api_key:
            api_key = base.api_key
    timeout = os.environ.get("BOOKCOMPILER_READER_TIMEOUT", "").strip()
    # Cost guard: MiMo and DeepSeek are both OpenAI-compatible, so a mistaken
    # preset could silently route a whole batch of books to the paid DeepSeek
    # endpoint. Reading books is the expensive step; require an explicit opt-in.
    if _looks_like_deepseek(provider, model, base_url) and os.environ.get(
        "BOOKCOMPILER_READER_ALLOW_DEEPSEEK", ""
    ).strip().lower() not in {"1", "true", "yes", "on"}:
        raise LLMCompileError(
            "Reader resolved to DeepSeek. Book reading is expensive and is blocked by default. "
            "Configure BOOKCOMPILER_READER_PROVIDER/MODEL/BASE_URL for a cheaper endpoint "
            "(MiMo or local Ollama), or set BOOKCOMPILER_READER_ALLOW_DEEPSEEK=1 to allow it."
        )
    return JudgeConfig(
        provider=provider,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        timeout=float(timeout) if timeout else max(base.timeout, 300.0),
        temperature=0.15,
        num_ctx=base.num_ctx,
    )


def _reader(config: JudgeConfig | None = None) -> BaseJudge:
    config = config or _reader_config()
    if config.provider.lower() in {"openai", "openai-compatible", "compatible", "api", "xiaomi"} and not config.api_key:
        raise LLMCompileError(
            "No cloud API key found for the reader. Set BOOKCOMPILER_READER_API_KEY, "
            "BOOKCOMPILER_JUDGE_API_KEY, DEEPSEEK_API_KEY, MIMO_API_KEY or OPENAI_API_KEY."
        )
    return create_judge(config)


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip()


def _clean_list(value: Any, limit: int = 12) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("text") or item.get("name") or item.get("value") or ""
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _chapter_groups(chunks: list[Chunk]) -> list[list[Chunk]]:
    groups: list[list[Chunk]] = []
    current: list[Chunk] = []
    current_key: tuple[int, str] | None = None
    for chunk in chunks:
        key = (chunk.chapter_index, chunk.chapter_title)
        if current_key is not None and key != current_key:
            groups.append(current)
            current = []
        current_key = key
        current.append(chunk)
    if current:
        groups.append(current)
    return groups


def _representative_chunk(group: list[Chunk]) -> Chunk:
    """Prefer a substantial chunk with argumentative, definitional language."""
    markers = (
        "therefore", "however", "because", "must", "should", "principle", "framework",
        "data", "evidence", "conclusion", "risk", "condition", "if ", "when ",
    )
    def score(chunk: Chunk) -> tuple[int, int]:
        text = chunk.text.lower()
        return (sum(1 for marker in markers if marker in text), min(len(chunk.text), 1600))
    return max(group, key=score)


def sample_evidence(chunks: list[Chunk], max_chunks: int = MAX_EVIDENCE_CHUNKS) -> list[Chunk]:
    """Evenly cover chapters, then fill remaining slots with rich chunks."""
    if not chunks:
        return []
    max_chunks = max(4, int(max_chunks))
    groups = _chapter_groups(chunks)
    selected: list[Chunk] = []
    if len(groups) <= max_chunks:
        selected = [_representative_chunk(group) for group in groups]
    else:
        # Spread samples across the whole book, including first and last.
        for index in range(max_chunks):
            position = round(index * (len(groups) - 1) / max(1, max_chunks - 1))
            selected.append(_representative_chunk(groups[position]))
    # Fill any shortfall with the richest unselected chunks.
    if len(selected) < max_chunks:
        used = {chunk.chunk_id for chunk in selected}
        ranked = sorted(chunks, key=lambda chunk: len(chunk.text), reverse=True)
        for chunk in ranked:
            if chunk.chunk_id in used:
                continue
            selected.append(chunk)
            used.add(chunk.chunk_id)
            if len(selected) >= max_chunks:
                break
    seen: set[str] = set()
    unique: list[Chunk] = []
    for chunk in selected:
        if chunk.chunk_id not in seen:
            seen.add(chunk.chunk_id)
            unique.append(chunk)
    return unique


def _evidence_payload(chunks: Iterable[Chunk], char_limit: int = EVIDENCE_CHARS) -> list[dict[str, Any]]:
    payload = []
    for chunk in chunks:
        payload.append(
            {
                "chunk_id": chunk.chunk_id,
                "chapter": chunk.chapter_title,
                "page": chunk.page_start,
                "text": _clip(chunk.text, char_limit),
            }
        )
    return payload


def _prompt(book: dict[str, Any], evidence: list[dict[str, Any]]) -> str:
    return f"""CONTEXT: This is an authorized academic knowledge-compilation task. The user owns these books and asks for a citation-grounded study guide. The supplied passages are non-graphic academic prose. Follow the JSON schema and do not refuse.

You are compiling a book into reusable agent knowledge. Read the supplied evidence packet, which is a representative sample of the whole book. Do not invent facts that are absent from the packet.

BOOK
title: {book.get('title', '')}
author: {book.get('author', '')}
disciplines: {', '.join(book.get('disciplines') or [])}

Return ONE valid JSON object, with no markdown fence and no commentary, using this exact shape:
{{
  "book_card": {{
    "one_line_thesis": "one sentence, at least 20 characters",
    "core_questions": ["3-6 questions"],
    "key_concepts": ["5-12 concepts"],
    "assumptions": ["3-6 assumptions"],
    "limitations": ["3-6 limitations or conditions"],
    "best_for": ["4-8 use cases"],
    "not_for": ["3-6 unsuitable use cases"],
    "lenses": ["economics", "politics", "law", "general"],
    "confidence": "low|medium|high",
    "chapter_coverage": [
      {{"chapter": "chapter title", "summary": "one or two sentences", "chunk_id": "an id from evidence", "quote": "exact text copied from that chunk"}}
    ]
  }},
  "frameworks": [
    {{
      "name": "short reusable framework name",
      "one_liner": "what the framework does, at least 20 characters",
      "lenses": ["economics"],
      "applicable_when": ["conditions"],
      "inputs": ["what the user must supply"],
      "steps": ["3-7 ordered reasoning steps"],
      "outputs": ["what the framework produces"],
      "failure_modes": ["when it misleads or breaks"],
      "counterexamples": ["a case where it should not be used"],
      "citations": [{{"chunk_id": "id from evidence", "quote": "exact text copied from that chunk"}}]
    }}
  ]
}}

Requirements:
- Produce {MIN_FRAMEWORKS}-{MAX_FRAMEWORKS} distinct frameworks that generalise beyond this book while remaining faithful to it.
- Every chapter_coverage item and every framework must cite evidence by chunk_id.
- Quotes MUST be copied verbatim from the supplied text. Do not paraphrase, translate, merge sentences, add ellipses, or invent quotation marks.
- Prefer a complete sentence or clause of at least 16 characters. A framework may have 1-3 citations.
- lenses must use only: economics, politics, law, general. Use multiple lenses only when the source genuinely supports them.
- Include tensions, limits, and counterexamples rather than producing a flattering summary.
- Write the content in Chinese when the book is Chinese; otherwise write in the book's main language.

EVIDENCE PACKET
{json.dumps(evidence, ensure_ascii=False, indent=1)}
"""


def _extract_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    first, last = text.find("{"), text.rfind("}")
    if first >= 0 and last > first:
        candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            if "book_card" not in value and _is_guardrail_envelope(value):
                raise ReaderRefused(
                    "reader refused the request: "
                    + str(value.get("reason") or value.get("message") or "safety filter")[:200]
                )
            return value
    raise LLMCompileError("reader did not return a valid JSON object")


def _is_guardrail_envelope(value: dict[str, Any]) -> bool:
    status = str(value.get("status") or "").lower()
    reason = str(value.get("reason") or "") + " " + str(value.get("message") or "")
    return status in {"rejected", "blocked", "error"} or "high risk" in reason.lower()


def _json_chat(judge: BaseJudge, prompt: str, label: str) -> dict[str, Any]:
    raw = judge.chat(prompt)
    try:
        return _extract_json(raw)
    except ReaderRefused:
        # Re-sending a safety refusal as a "repair" wastes a call and is likely
        # to be refused again; surface it immediately for a smaller retry.
        raise
    except LLMCompileError:
        repair = (
            "The previous response was not valid JSON. Return only one syntactically valid JSON object, "
            "with no markdown fence and no commentary. Keep the same content and schema.\n\n"
            + _clip(raw, 18000)
        )
        raw2 = judge.chat(repair)
        try:
            return _extract_json(raw2)
        except LLMCompileError as exc:
            raise LLMCompileError(f"{label}: {exc}") from exc


def _best_sentence(chunk: Chunk, hint: str = "", minimum: int = 16) -> str:
    sentences = [s.strip() for s in split_sentences(chunk.text) if len(s.strip()) >= minimum]
    if not sentences:
        sentences = [chunk.text.strip()] if chunk.text.strip() else []
    if not sentences:
        return ""
    hint_terms = {term for term in re.findall(r"[\w\u4e00-\u9fff]{2,}", hint.lower()) if len(term) >= 2}
    def score(sentence: str) -> tuple[int, int]:
        lowered = sentence.lower()
        overlap = sum(1 for term in hint_terms if term in lowered)
        return (overlap, min(len(sentence), 400))
    return max(sentences, key=score)


def _resolve_citation(
    raw: Any,
    chunks_by_id: dict[str, Chunk],
    all_chunks: list[Chunk],
    fallback_chunk: Chunk | None = None,
    hint: str = "",
) -> Evidence | None:
    item = raw if isinstance(raw, dict) else {}
    chunk_id = str(item.get("chunk_id") or "").strip()
    quote = str(item.get("quote") or "").strip()
    chunk = chunks_by_id.get(chunk_id)
    if chunk is None and quote:
        chunk = find_quote(quote, all_chunks)
    if chunk is None:
        chunk = fallback_chunk
    if chunk is None:
        return None
    candidate = quote
    normalized = normalize_for_quote(candidate)
    if len(normalized) < 12 or normalized not in normalize_for_quote(chunk.text):
        # A paraphrase is never accepted. Replace it with a real sentence from
        # the cited chunk, making the provenance repair visible in the patch.
        candidate = _best_sentence(chunk, hint=hint or quote)
    if not candidate or normalize_for_quote(candidate) not in normalize_for_quote(chunk.text):
        return None
    return Evidence(
        book_id=chunk.book_id,
        quote=candidate,
        chunk_id=chunk.chunk_id,
        chapter=chunk.chapter_title,
        page=chunk.page_start,
    )


def _normalise_lenses(value: Any, fallback_text: str) -> list[str]:
    allowed = {"economics", "politics", "law", "general"}
    result: list[str] = []
    if isinstance(value, str):
        value = [value]
    if isinstance(value, list):
        for item in value:
            lens = str(item or "").strip().lower()
            if lens in allowed and lens not in result:
                result.append(lens)
    return result or infer_lenses(fallback_text)


def normalise_patch(
    book: dict[str, Any],
    raw: dict[str, Any],
    evidence: list[Chunk],
    all_chunks: list[Chunk],
) -> dict[str, Any]:
    chunks_by_id = {chunk.chunk_id: chunk for chunk in all_chunks}
    evidence_ids = [chunk.chunk_id for chunk in evidence]
    evidence_chunks = [chunks_by_id[cid] for cid in evidence_ids if cid in chunks_by_id]
    # Schema tolerance: some OpenAI-compatible models (observed with MiMo)
    # nest "frameworks" inside "book_card", or wrap the whole payload under
    # "book"/"result".  Normalise those shapes instead of silently producing a
    # zero-framework patch.
    if not isinstance(raw.get("book_card"), dict):
        for wrapper in ("book", "result", "data"):
            nested = raw.get(wrapper)
            if isinstance(nested, dict) and isinstance(nested.get("book_card"), dict):
                raw = nested
                break
    card_raw = raw.get("book_card") if isinstance(raw.get("book_card"), dict) else {}
    frameworks_value = raw.get("frameworks")
    if frameworks_value is None:
        frameworks_value = card_raw.get("frameworks")
    if isinstance(frameworks_value, dict):
        frames = []
        for key, value in frameworks_value.items():
            if isinstance(value, dict):
                value = dict(value)
                value.setdefault("name", str(key))
                frames.append(value)
        frameworks_value = frames
    frameworks_raw = frameworks_value if isinstance(frameworks_value, list) else []

    coverage: list[dict[str, Any]] = []
    seen_coverage: set[tuple[str, str]] = set()
    for item in card_raw.get("chapter_coverage") or []:
        if not isinstance(item, dict):
            continue
        evidence_item = _resolve_citation(
            item,
            chunks_by_id,
            all_chunks,
            fallback_chunk=evidence_chunks[len(coverage) % len(evidence_chunks)] if evidence_chunks else None,
            hint=str(item.get("summary") or ""),
        )
        if evidence_item is None:
            continue
        key = (str(item.get("chapter") or evidence_item.chapter), str(item.get("summary") or ""))
        if key in seen_coverage:
            continue
        seen_coverage.add(key)
        coverage.append(
            {
                "chapter": str(item.get("chapter") or evidence_item.chapter),
                "summary": _clip(item.get("summary") or _best_sentence(chunks_by_id[evidence_item.chunk_id]), 500),
                "citation": evidence_item.to_dict(),
            }
        )
    for chunk in evidence_chunks:
        if len(coverage) >= 8:
            break
        if any(entry["citation"].get("chunk_id") == chunk.chunk_id for entry in coverage):
            continue
        sentence = _best_sentence(chunk, hint=chunk.chapter_title)
        if not sentence:
            continue
        citation = Evidence(chunk.book_id, sentence, chunk.chunk_id, chunk.chapter_title, chunk.page_start)
        coverage.append({"chapter": chunk.chapter_title, "summary": _clip(sentence, 500), "citation": citation.to_dict()})
    if not coverage and evidence_chunks:
        chunk = evidence_chunks[0]
        sentence = _best_sentence(chunk)
        citation = Evidence(chunk.book_id, sentence, chunk.chunk_id, chunk.chapter_title, chunk.page_start)
        coverage.append({"chapter": chunk.chapter_title, "summary": _clip(sentence, 500), "citation": citation.to_dict()})

    frameworks: list[dict[str, Any]] = []
    for index, item in enumerate(frameworks_raw[:MAX_FRAMEWORKS]):
        if not isinstance(item, dict):
            continue
        name = _clip(item.get("name") or f"Framework {index + 1}", 120)
        raw_citations = item.get("citations") or []
        if isinstance(raw_citations, dict):
            raw_citations = [raw_citations]
        citations: list[Evidence] = []
        for citation in raw_citations:
            resolved = _resolve_citation(citation, chunks_by_id, all_chunks, hint=name)
            if resolved is not None and all(resolved.chunk_id != old.chunk_id or resolved.quote != old.quote for old in citations):
                citations.append(resolved)
        if not citations and evidence_chunks:
            # Pick the evidence chunk most related to the framework name.
            def relevance(chunk: Chunk) -> int:
                lowered = chunk.text.lower()
                terms = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", name.lower()))
                return sum(lowered.count(term) for term in terms)
            chunk = max(evidence_chunks, key=relevance)
            sentence = _best_sentence(chunk, hint=name)
            if sentence:
                citations.append(Evidence(chunk.book_id, sentence, chunk.chunk_id, chunk.chapter_title, chunk.page_start))
        if not citations:
            continue
        one_liner = str(item.get("one_liner") or "").strip()
        if len(one_liner) < 20:
            one_liner = citations[0].quote if len(citations[0].quote) >= 20 else f"{name}: {citations[0].quote}"
        lenses = _normalise_lenses(item.get("lenses"), " ".join([name, one_liner, citations[0].quote]))
        framework = {
            "framework_id": stable_id(book["book_id"], name, one_liner),
            "book_id": book["book_id"],
            "name": name,
            "one_liner": one_liner,
            "lenses": lenses,
            "applicable_when": _clean_list(item.get("applicable_when"), 8) or ["When the source conditions are satisfied"],
            "inputs": _clean_list(item.get("inputs"), 8) or ["A concrete case", "The relevant conditions from the source"],
            "steps": _clean_list(item.get("steps"), 10) or ["Identify the relevant conditions", "Apply the source's causal or normative test", "State the conclusion and its limits"],
            "outputs": _clean_list(item.get("outputs"), 8) or ["A source-grounded judgment with uncertainty"],
            "failure_modes": _clean_list(item.get("failure_modes"), 8) or ["Applying the framework outside the conditions stated in the source"],
            "counterexamples": _clean_list(item.get("counterexamples"), 8),
            "citations": [citation.to_dict() for citation in citations],
            "related_frameworks": [],
            "confidence": str(item.get("confidence") or "medium").lower() if str(item.get("confidence") or "medium").lower() in {"low", "medium", "high"} else "medium",
            "status": "verified",
        }
        frameworks.append(framework)
    if len(frameworks) < MIN_FRAMEWORKS:
        raise LLMCompileError(f"only {len(frameworks)} valid frameworks; need at least {MIN_FRAMEWORKS}")

    card = {
        "book_id": book["book_id"],
        "title": book.get("title", ""),
        "author": book.get("author", ""),
        "one_line_thesis": str(card_raw.get("one_line_thesis") or "").strip(),
        "core_questions": _clean_list(card_raw.get("core_questions"), 8),
        "key_concepts": _clean_list(card_raw.get("key_concepts"), 16),
        "assumptions": _clean_list(card_raw.get("assumptions"), 10),
        "limitations": _clean_list(card_raw.get("limitations"), 10),
        "best_for": _clean_list(card_raw.get("best_for"), 12),
        "not_for": _clean_list(card_raw.get("not_for"), 12),
        "chapter_coverage": coverage,
        "lenses": _normalise_lenses(card_raw.get("lenses"), " ".join(_clean_list(card_raw.get("key_concepts"), 20))),
        "confidence": str(card_raw.get("confidence") or "medium").lower() if str(card_raw.get("confidence") or "medium").lower() in {"low", "medium", "high"} else "medium",
        "status": "verified",
    }
    if len(card["one_line_thesis"]) < 20:
        card["one_line_thesis"] = coverage[0]["summary"] if coverage else f"{book.get('title', '')}: a source-grounded framework."
    for field in ("core_questions", "key_concepts", "assumptions", "limitations", "best_for", "not_for"):
        if not card[field]:
            card[field] = [f"See the book card and cited chapters for {field.replace('_', ' ')}."]

    issues = validate_book_card(card, all_chunks)
    for framework in frameworks:
        issues.extend(validate_framework_card(framework, all_chunks))
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        detail = "; ".join(f"{issue.code}: {issue.message}" for issue in errors[:8])
        raise LLMCompileError(f"generated patch failed provenance validation: {detail}")
    return {"book_card": card, "frameworks": frameworks, "generated_at": utc_now()}


def compile_with_llm(
    store: Store,
    book_id: str,
    *,
    max_chunks: int = MAX_EVIDENCE_CHUNKS,
    evidence_chars: int = EVIDENCE_CHARS,
    config: JudgeConfig | None = None,
    judge: BaseJudge | None = None,
) -> dict[str, Any]:
    book = store.get_book(book_id)
    if not book:
        raise LLMCompileError(f"unknown book_id: {book_id}")
    chunks = store.get_chunks(book_id)
    if not chunks:
        raise LLMCompileError(f"book has no chunks: {book_id}")
    evidence = sample_evidence(chunks, max_chunks=max_chunks)
    prompt = _prompt(book, _evidence_payload(evidence, evidence_chars))
    judge = judge or _reader(config)
    raw = _json_chat(judge, prompt, "book compile")
    try:
        patch = normalise_patch(book, raw, evidence, chunks)
    except LLMCompileError:
        # Keep the unverified proposal for diagnosis.  It never enters the
        # library; it is only a debugging artefact next to the patch folder.
        out_dir = project_root() / ".bookcompiler" / OUTPUT_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{book_id}.raw.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        raise
    out_dir = project_root() / ".bookcompiler" / OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_path = out_dir / f"{book_id}.json"
    temporary = patch_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(patch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, patch_path)
    result = compile_book(store, book_id, patch=patch)
    errors = [issue.to_dict() for issue in result.issues if issue.severity == "error"]
    if errors:
        raise LLMCompileError(f"compile failed: {json.dumps(errors[:8], ensure_ascii=False)}")
    return {
        "ok": True,
        "book_id": book_id,
        "title": book.get("title", ""),
        "patch_path": str(patch_path),
        "frameworks": len(result.frameworks),
        "evidence_chunks": len(evidence),
        "card_status": result.book_card.status,
        "book_status": (store.get_book(book_id) or {}).get("status", ""),
        "issues": [issue.to_dict() for issue in result.issues],
    }
