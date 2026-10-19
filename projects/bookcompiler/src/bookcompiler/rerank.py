"""Lazy cross-encoder reranking for retrieval results.

The reranker is optional: when disabled or unavailable, retrieval returns the
hybrid ordering unchanged and reports why.  Model loading is lazy so CLI tests
and MCP startup stay fast.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Sequence

from .config import load_env

DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-base"


def enabled() -> bool:
    load_env()
    value = os.environ.get("BOOKCOMPILER_RERANK", "0").strip().lower()
    return value in {"1", "true", "yes", "on", "auto"}


def model_name() -> str:
    load_env()
    configured = os.environ.get("BOOKCOMPILER_RERANK_MODEL", "").strip()
    if configured:
        return configured
    local = Path(r"D:\models\bge-reranker-base")
    return str(local) if local.is_dir() else DEFAULT_RERANK_MODEL


class CrossEncoderReranker:
    def __init__(self, model: str | None = None, device: str = "auto", max_length: int = 512) -> None:
        self.model_name = model or model_name()
        self.requested_device = device
        self.max_length = max_length
        self._tokenizer = None
        self._model = None
        self._torch = None
        self.device = ""

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        if self.requested_device in {"cpu", "cuda"}:
            self.device = self.requested_device if self.requested_device == "cpu" or torch.cuda.is_available() else "cpu"
        else:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=False)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name, trust_remote_code=False)
        self._model.to(self.device)
        self._model.eval()

    def scores(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        self._load()
        torch = self._torch
        assert torch is not None and self._tokenizer is not None and self._model is not None
        output: list[float] = []
        batch_size = max(1, int(os.environ.get("BOOKCOMPILER_RERANK_BATCH", "8")))
        for start in range(0, len(passages), batch_size):
            batch = [str(item or "")[:4000] for item in passages[start:start + batch_size]]
            encoded = self._tokenizer(
                [query] * len(batch),
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with torch.inference_mode():
                logits = self._model(**encoded).logits
            if logits.shape[-1] == 1:
                values = torch.sigmoid(logits[:, 0])
            else:
                values = torch.softmax(logits, dim=-1)[:, -1]
            output.extend(values.detach().float().cpu().tolist())
        return output


_RERANKER_CACHE: dict[tuple[str, str, int], "CrossEncoderReranker"] = {}


def get_reranker(model: str | None = None, device: str = "auto", max_length: int = 512) -> "CrossEncoderReranker":
    """Return a cached cross-encoder handle.

    Model loading dominates the first rerank call, and construction used to
    happen on every query.  The cache key keeps different models/devices
    isolated.
    """
    name = model or model_name()
    key = (name, device, int(max_length))
    cached = _RERANKER_CACHE.get(key)
    if cached is None:
        cached = CrossEncoderReranker(model=name, device=device, max_length=max_length)
        _RERANKER_CACHE[key] = cached
    return cached


def clear_reranker_cache() -> None:
    _RERANKER_CACHE.clear()


def rerank_items(
    query: str,
    items: list[dict[str, Any]],
    *,
    text_key: str = "text",
    top_k: int | None = None,
    model: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rerank a candidate list and attach auditable scores.

    The final score is a blend: 35% normalized hybrid score, 65% cross-encoder
    probability.  The original score is preserved in ``score_breakdown`` so a
    reranker failure or ordering change can be inspected instead of hidden.
    """
    if not items:
        return [], {"reranked": False, "reason": "no candidates"}
    try:
        reranker = get_reranker(model=model)
        raw = reranker.scores(query, [str(item.get(text_key, "")) for item in items])
    except Exception as exc:  # noqa: BLE001 - retrieval must degrade, not crash
        return items, {
            "reranked": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "model": model or model_name(),
        }
    maximum = max((float(item.get("score", 0.0)) for item in items), default=0.0) or 1.0
    reranked: list[dict[str, Any]] = []
    for item, value in zip(items, raw):
        candidate = dict(item)
        pre = float(candidate.get("score", 0.0))
        blended = 0.35 * (pre / maximum) + 0.65 * float(value)
        breakdown = dict(candidate.get("score_breakdown") or {})
        breakdown["pre_rerank_score"] = round(pre, 6)
        breakdown["rerank"] = round(float(value), 6)
        candidate["score_breakdown"] = breakdown
        candidate["score"] = round(blended, 6)
        candidate["rerank_score"] = round(float(value), 6)
        reranked.append(candidate)
    reranked.sort(key=lambda item: (-float(item["score"]), item.get("book_id", ""), item.get("chapter_index", 0), item.get("position", 0)))
    if top_k is not None:
        reranked = reranked[:top_k]
    return reranked, {
        "reranked": True,
        "model": reranker.model_name,
        "device": reranker.device,
        "candidate_count": len(items),
        "returned": len(reranked),
    }