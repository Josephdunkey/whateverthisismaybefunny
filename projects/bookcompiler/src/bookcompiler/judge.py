"""Independent blind judge for BookCompiler reading evaluations.

The deterministic ``auto_scores`` path is a triage signal.  This module adds a
separate, explicitly-labelled judge that reads a final analysis and scores it
without seeing the proxy scores or any previous evaluation.  It never pretends
that a failed or unavailable judge produced a human-like judgment.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import load_env
from .reading_eval import (
    DIMENSION_BY_KEY,
    READING_DIMENSIONS,
    RUBRIC_VERSION,
    evaluate_reading,
)
from .store import Store
from .utils import stable_id
from .validation import validate_analysis_packet


class JudgeError(RuntimeError):
    """Raised when an independent judge cannot produce a valid evaluation."""


@dataclass
class JudgeConfig:
    provider: str = "ollama"
    model: str = "qwen2.5:7b-instruct-q4_K_M"
    base_url: str = "http://127.0.0.1:11434"
    api_key: str = ""
    timeout: float = 240.0
    temperature: float = 0.1
    num_ctx: int = 24576


def default_judge_config() -> JudgeConfig:
    load_env()
    provider = os.environ.get("BOOKCOMPILER_JUDGE_PROVIDER", "ollama").strip() or "ollama"
    model = os.environ.get("BOOKCOMPILER_JUDGE_MODEL", "").strip()
    if not model:
        model = "qwen2.5:7b-instruct-q4_K_M" if provider == "ollama" else "gpt-4o-mini"
    if provider == "ollama":
        base_url = os.environ.get("BOOKCOMPILER_JUDGE_BASE_URL", "http://127.0.0.1:11434")
    else:
        base_url = os.environ.get("BOOKCOMPILER_JUDGE_BASE_URL", "https://api.openai.com/v1")
    api_key = os.environ.get("BOOKCOMPILER_JUDGE_API_KEY", "").strip()
    if not api_key:
        lowered = base_url.lower()
        if "deepseek" in lowered:
            api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        elif "openai.com" in lowered:
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        elif "dashscope" in lowered or "aliyun" in lowered:
            api_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
        elif "xiaomimimo" in lowered or "mimo" in lowered:
            api_key = os.environ.get("MIMO_API_KEY", "").strip() or os.environ.get("XIAOMI_API_KEY", "").strip()
    return JudgeConfig(
        provider=provider,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        timeout=float(os.environ.get("BOOKCOMPILER_JUDGE_TIMEOUT", "240")),
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clip(text: Any, limit: int) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _citation_audit(packet: dict[str, Any], store: Store) -> dict[str, Any]:
    book_ids = {
        str(item.get("book_id"))
        for item in (packet.get("citations") or [])
        if isinstance(item, dict) and item.get("book_id")
    }
    selection = packet.get("selection") or {}
    for book in selection.get("books", []) if isinstance(selection, dict) else []:
        if isinstance(book, dict) and book.get("book_id"):
            book_ids.add(str(book["book_id"]))
    chunks = {book_id: store.get_chunks(book_id) for book_id in sorted(book_ids) if book_id}
    try:
        issues = validate_analysis_packet(packet, chunks)
    except Exception as exc:  # noqa: BLE001 - the judge prompt should still be usable
        return {"checked": False, "error": f"{type(exc).__name__}: {exc}"}
    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    return {
        "checked": True,
        "citation_count": len(packet.get("citations") or []),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": [issue.to_dict() for issue in errors[:12]],
        "warnings": [issue.to_dict() for issue in warnings[:12]],
    }


def build_blind_prompt(
    store: Store,
    packet: dict[str, Any],
    max_citations: int = 24,
    max_quote_chars: int = 420,
) -> str:
    """Build a judge prompt that deliberately omits proxy and prior scores."""
    question = str(packet.get("question", "")).strip()
    lenses = [str(item) for item in packet.get("lenses", []) if str(item)]
    selection = packet.get("selection") or {}
    books = selection.get("books", []) if isinstance(selection, dict) else []
    frameworks = [item for item in (packet.get("frameworks") or []) if isinstance(item, dict)]
    citations = [item for item in (packet.get("citations") or []) if isinstance(item, dict)]
    audit = _citation_audit(packet, store)

    lines: list[str] = []
    lines.append("You are an independent, skeptical reviewer. You did not write this answer and you do not know its author.")
    lines.append("Score how effectively the answer uses the learned books. Do not reward length, confidence, or rhetorical polish.")
    lines.append("You must judge the answer as it stands. If evidence is missing or a lens is merely named but not integrated, say so in the scores.")
    lines.append("")
    lines.append(f"RUBRIC VERSION: {RUBRIC_VERSION}")
    lines.append("")
    lines.append("## Question")
    lines.append(question or "(empty)")
    lines.append("")
    lines.append(f"## Lenses requested: {', '.join(lenses) or '(none)'}")
    lines.append("")
    lines.append("## Selected books")
    if books:
        for book in books:
            title = book.get("title") or book.get("book_id") or ""
            disciplines = ", ".join(book.get("disciplines", []) or [])
            lines.append(f"- {title}" + (f" ({disciplines})" if disciplines else ""))
    else:
        lines.append("- (none recorded)")
    lines.append("")
    lines.append("## Frameworks used")
    if frameworks:
        for framework in frameworks[:16]:
            lines.append(f"- {framework.get('name', '')}: {_clip(framework.get('one_liner', ''), 260)}")
            applicable = [str(item) for item in framework.get("applicable_when", []) or []]
            failures = [str(item) for item in framework.get("failure_modes", []) or []]
            if applicable:
                lines.append(f"  - Applicable when: {'; '.join(applicable[:4])}")
            if failures:
                lines.append(f"  - Failure modes: {'; '.join(failures[:4])}")
    else:
        lines.append("- (none recorded)")
    lines.append("")
    lines.append("## Answer under review")
    lines.append("### Conclusion")
    lines.append(str(packet.get("conclusion", "")).strip() or "(empty)")
    lines.append("")
    lines.append("### Uncertainty / what would change the conclusion")
    lines.append(str(packet.get("uncertainty", "")).strip() or "(empty)")
    lines.append("")
    lines.append("### Counterevidence")
    counterevidence = packet.get("counterevidence") or []
    if counterevidence:
        for item in counterevidence[:10]:
            if isinstance(item, dict):
                lines.append(f"- {_clip(item.get('claim') or item.get('description') or item, 320)}")
            else:
                lines.append(f"- {_clip(item, 320)}")
    else:
        lines.append("- (none recorded)")
    lines.append("")
    lines.append("### Cross-lens conflicts")
    conflicts = packet.get("cross_lens_conflicts") or []
    if conflicts:
        for item in conflicts[:10]:
            if isinstance(item, dict):
                lines.append(f"- {_clip(item.get('description') or item, 320)}")
            else:
                lines.append(f"- {_clip(item, 320)}")
    else:
        lines.append("- (none recorded)")
    lines.append("")
    lines.append("### Claim-level summary")
    claims = [item for item in (packet.get("claims") or []) if isinstance(item, dict)]
    if claims:
        for claim in claims[:12]:
            lines.append(
                f"- [{_clip(claim.get('book_id', ''), 40)}] {_clip(claim.get('subject', ''), 80)} "
                f"{_clip(claim.get('predicate', ''), 40)} {_clip(claim.get('object', ''), 160)} "
                f"(confidence {claim.get('confidence', '')})"
            )
    else:
        lines.append("- (none recorded)")
    lines.append("")
    lines.append("## Exact-quote evidence supplied by the answer")
    if citations:
        for index, citation in enumerate(citations[:max_citations], start=1):
            lines.append(
                f"{index}. book={citation.get('book_id', '')} chapter={_clip(citation.get('chapter', ''), 90)} "
                f"page={citation.get('page', citation.get('page_start', ''))}"
            )
            lines.append(f"   quote: {_clip(citation.get('quote', ''), max_quote_chars)}")
    else:
        lines.append("(no citations)")
    if len(citations) > max_citations:
        lines.append(f"... {len(citations) - max_citations} additional citations omitted from this prompt.")
    lines.append("")
    lines.append("## Deterministic citation audit (not a quality score)")
    if audit.get("checked"):
        lines.append(
            f"- citations checked: {audit.get('citation_count', 0)}; validation errors: {audit.get('error_count', 0)}; "
            f"warnings: {audit.get('warning_count', 0)}"
        )
        for issue in audit.get("errors", [])[:8]:
            lines.append(f"- ERROR {issue.get('code', '')}: {issue.get('message', '')}")
    else:
        lines.append(f"- citation audit unavailable: {audit.get('error', 'unknown error')}")
    lines.append("")
    lines.append("## Nine dimensions to score (0-10)")
    for item in READING_DIMENSIONS:
        lines.append(f"- `{item['key']}` (weight {item['weight']}): {item['question']}")
    lines.append("")
    lines.append("## Output contract")
    lines.append("Return ONE JSON object only. Every dimension is required. Scores must be numbers from 0 to 10.")
    lines.append("Use this shape:")
    lines.append('{"scores": {')
    lines.append('  "source_fidelity": 0, "retrieval_coverage": 0, "framework_fit": 0,')
    lines.append('  "cross_book_synthesis": 0, "cross_lens_integration": 0, "conflict_handling": 0,')
    lines.append('  "calibration": 0, "actionability": 0, "failure_mode_awareness": 0')
    lines.append('}, "error_labels": ["..."], "note": "2-4 sentence overall judgment",')
    lines.append(' "strongest_part": "...", "weakest_part": "..."}')
    lines.append("Error labels should be short snake_case tags such as retrieval_miss, citation_error, lens_omission, conflict_suppression, overconfidence, framework_misapplication.")
    return "\n".join(lines)


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first complete JSON object from a model response."""
    if not text:
        raise JudgeError("judge returned an empty response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    if start < 0:
        raise JudgeError("judge response contains no JSON object")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : index + 1]
                try:
                    payload = json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise JudgeError(f"judge returned invalid JSON: {exc}") from exc
                if not isinstance(payload, dict):
                    raise JudgeError("judge JSON root must be an object")
                return payload
    raise JudgeError("judge response contains an incomplete JSON object")


def parse_judge_response(text: str) -> dict[str, Any]:
    payload = extract_json_object(text)
    scores = payload.get("scores")
    if not isinstance(scores, dict):
        raise JudgeError("judge response is missing a scores object")
    missing = [item["key"] for item in READING_DIMENSIONS if item["key"] not in scores]
    if missing:
        raise JudgeError("judge did not score these dimensions: " + ", ".join(missing))
    normalized: dict[str, float] = {}
    for item in READING_DIMENSIONS:
        key = item["key"]
        try:
            value = float(scores[key])
        except (TypeError, ValueError) as exc:
            raise JudgeError(f"judge score for {key} is not a number") from exc
        if not 0 <= value <= 10:
            raise JudgeError(f"judge score for {key} is outside 0..10")
        normalized[key] = round(value, 1)
    labels = payload.get("error_labels", [])
    if isinstance(labels, str):
        labels = [labels]
    if not isinstance(labels, list):
        raise JudgeError("judge error_labels must be a list")
    note_parts = [
        str(payload.get("note", "")).strip(),
        f"Strongest: {str(payload.get('strongest_part', '')).strip()}" if payload.get("strongest_part") else "",
        f"Weakest: {str(payload.get('weakest_part', '')).strip()}" if payload.get("weakest_part") else "",
    ]
    return {
        "scores": normalized,
        "error_labels": [str(item).strip() for item in labels if str(item).strip()],
        "note": " ".join(part for part in note_parts if part),
        "strongest_part": str(payload.get("strongest_part", "")).strip(),
        "weakest_part": str(payload.get("weakest_part", "")).strip(),
        "raw": payload,
    }


class BaseJudge:
    provider = "base"
    model = "base"

    def chat(self, prompt: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class OllamaJudge(BaseJudge):
    provider = "ollama"

    def __init__(self, config: JudgeConfig) -> None:
        self.config = config
        self.model = config.model

    def chat(self, prompt: str) -> str:
        body = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a strict independent evaluator. Return only valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": self.config.num_ctx,
            },
        }
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + "/api/chat",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
            raise JudgeError(f"Ollama judge HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise JudgeError(f"Ollama judge unavailable at {self.config.base_url}: {exc}") from exc
        message = payload.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else ""
        if not content:
            raise JudgeError("Ollama judge returned no message content")
        return str(content)


class OpenAICompatibleJudge(BaseJudge):
    provider = "openai-compatible"

    def __init__(self, config: JudgeConfig) -> None:
        self.config = config
        self.model = config.model

    def chat(self, prompt: str) -> str:
        if not self.config.api_key:
            raise JudgeError(
                "openai-compatible judge requires BOOKCOMPILER_JUDGE_API_KEY (or pass --api-key-env pointing to a set variable)"
            )
        body = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": "You are a strict independent evaluator. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.config.temperature,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            self.config.base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
            raise JudgeError(f"judge HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise JudgeError(f"judge unavailable at {self.config.base_url}: {exc}") from exc
        choices = payload.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise JudgeError("judge returned no choices")
        content = (choices[0].get("message") or {}).get("content", "")
        if not content:
            raise JudgeError("judge returned no message content")
        return str(content)


def create_judge(config: JudgeConfig | None = None) -> BaseJudge:
    config = config or default_judge_config()
    provider = config.provider.lower()
    if provider in {"ollama", "local"}:
        return OllamaJudge(config)
    if provider in {"openai", "openai-compatible", "compatible", "api"}:
        return OpenAICompatibleJudge(config)
    raise JudgeError(f"unknown judge provider: {config.provider}")


def judge_analysis(
    store: Store,
    analysis_id: str,
    config: JudgeConfig | None = None,
    judge: BaseJudge | None = None,
    dry_run: bool = False,
    allow_draft: bool = False,
    note: str = "",
    max_citations: int = 24,
    save_prompt: str = "",
) -> dict[str, Any]:
    """Score one analysis with an independent judge and persist the result.

    A failed judge raises ``JudgeError`` and writes nothing.  The caller must
    never substitute ``auto_proxy`` scores for a failed judge.
    """
    packet = store.get_analysis(analysis_id)
    if not packet:
        raise JudgeError(f"unknown analysis_id: {analysis_id}")
    if str(packet.get("status", "draft")) != "complete" and not allow_draft:
        raise JudgeError(
            "refusing to judge a draft; finish the analysis (status=complete) first, or pass allow_draft=True explicitly"
        )
    prompt = build_blind_prompt(store, packet, max_citations=max_citations)
    if save_prompt:
        from pathlib import Path

        Path(save_prompt).write_text(prompt, encoding="utf-8")
    if dry_run:
        return {
            "dry_run": True,
            "analysis_id": analysis_id,
            "prompt": prompt,
            "prompt_chars": len(prompt),
            "prompt_sha256": _sha256(prompt),
            "rubric_version": RUBRIC_VERSION,
        }

    judge = judge or create_judge(config)
    started = time.time()
    raw = judge.chat(prompt)
    elapsed = round(time.time() - started, 2)
    parsed = parse_judge_response(raw)
    metadata = {
        "rubric_version": RUBRIC_VERSION,
        "judge": {
            "provider": getattr(judge, "provider", "unknown"),
            "model": getattr(judge, "model", "unknown"),
            "base_url": getattr(getattr(judge, "config", None), "base_url", ""),
            "elapsed_seconds": elapsed,
            "prompt_sha256": _sha256(prompt),
            "prompt_chars": len(prompt),
            "response_sha256": _sha256(raw),
            "response_chars": len(raw),
            "strongest_part": parsed.get("strongest_part", ""),
            "weakest_part": parsed.get("weakest_part", ""),
            "raw_response": raw,
        },
        "blind": True,
        "proxy_scores_hidden": True,
    }
    evaluation = evaluate_reading(
        store,
        analysis_id,
        scores=parsed["scores"],
        evaluator=f"llm_judge:{getattr(judge, 'model', 'unknown')}",
        note=note or parsed.get("note", ""),
        error_labels=parsed.get("error_labels", []),
        metadata=metadata,
    )
    evaluation["judge"] = metadata["judge"]
    evaluation["proxy_calibration"] = {
        key: round(float(evaluation["scores"][key]) - float(evaluation["auto_proxy"].get(key, 0.0)), 1)
        for key in DIMENSION_BY_KEY
    }
    return evaluation


def judge_status() -> dict[str, Any]:
    config = default_judge_config()
    return {
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "api_key_configured": bool(config.api_key),
        "timeout_seconds": config.timeout,
        "note": "Judge scores are independent only when a real model returns valid JSON; auto_proxy is never relabelled as a judge.",
    }
