from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .config import load_env

LOCAL_MODEL = "local-hash-ngram-v1"
DEFAULT_DIM = 768
DEFAULT_NEURAL_MODEL = "BAAI/bge-small-zh-v1.5"

_ASCII_WORD = re.compile(r"[a-z0-9_]{2,}")
_CJK_BLOCK = re.compile(r"[\u4e00-\u9fff]+")


def _tokens(text: str) -> list[tuple[str, float]]:
    """Tokenize without third-party NLP dependencies.

    English words are kept whole. Chinese text is represented by character
    bigrams/trigrams plus short whole blocks, which makes the vector robust to
    OCR line breaks and punctuation differences.
    """
    lowered = (text or "").lower()
    result: list[tuple[str, float]] = []
    for word in _ASCII_WORD.findall(lowered):
        result.append((f"w:{word}", 1.2))
    for block in _CJK_BLOCK.findall(lowered):
        if len(block) <= 6:
            result.append((f"c:{block}", 1.0))
        for n, weight in ((2, 0.55), (3, 1.0), (4, 0.7)):
            if len(block) < n:
                continue
            for index in range(len(block) - n + 1):
                result.append((f"c{n}:{block[index:index + n]}", weight))
    return result


def _normalize(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        return [0.0] * len(values)
    return [value / norm for value in values]


def local_embed(text: str, dim: int = DEFAULT_DIM) -> list[float]:
    if dim < 32:
        raise ValueError("embedding dimension must be >= 32")
    vector = [0.0] * dim
    counts: dict[str, float] = {}
    for token, weight in _tokens(text):
        counts[token] = counts.get(token, 0.0) + weight
    for token, weight in counts.items():
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        index = value % dim
        sign = 1.0 if (value >> 63) & 1 else -1.0
        # Sublinear term frequency keeps repeated OCR boilerplate from dominating.
        vector[index] += sign * (1.0 + math.log1p(weight))
    return _normalize(vector)


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    # Vectors are stored normalized; guard against tiny drift.
    dot = sum(a * b for a, b in zip(left, right))
    return max(0.0, min(1.0, dot))


def pack_vector(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack_vector(blob: bytes) -> list[float]:
    if not blob:
        return []
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob[: count * 4]))


@dataclass
class EmbeddingBackend:
    model: str
    dim: int
    kind: str = "local"

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [local_embed(text, self.dim) for text in texts]


class NeuralEmbedder(EmbeddingBackend):
    """Lazy local neural embedder using transformers (no sentence-transformers).

    The anaconda environment currently ships NumPy 2.x while its scipy/sklearn
    wheels were compiled against NumPy 1.x, so importing sentence-transformers
    crashes.  Using ``AutoModel``/``AutoTokenizer`` directly avoids that
    dependency chain and keeps the backend available on this machine.

    Configuration:
      BOOKCOMPILER_EMBED_BACKEND=neural
      BOOKCOMPILER_EMBED_MODEL=D:\\models\\bge-small-zh-v1.5
      BOOKCOMPILER_EMBED_DEVICE=auto|cuda|cpu
    """

    def __init__(self, model: str, device: str = "auto", max_length: int = 512) -> None:
        super().__init__(model=model, dim=0, kind="neural")
        self.requested_device = device
        self.max_length = max_length
        self._tokenizer = None
        self._model = None
        self._torch = None
        self.device = ""

    def _resolve_device(self, torch_module) -> str:
        if self.requested_device in {"cpu", "cuda"}:
            if self.requested_device == "cuda" and not torch_module.cuda.is_available():
                return "cpu"
            return self.requested_device
        return "cuda" if torch_module.cuda.is_available() else "cpu"

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModel, AutoTokenizer

        self._torch = torch
        self.device = self._resolve_device(torch)
        # A local directory avoids a network round-trip once the model has been
        # downloaded.  HF_ENDPOINT is respected by transformers otherwise.
        self._tokenizer = AutoTokenizer.from_pretrained(self.model, trust_remote_code=False)
        self._model = AutoModel.from_pretrained(self.model, trust_remote_code=False)
        self._model.to(self.device)
        self._model.eval()
        self.dim = int(getattr(self._model.config, "hidden_size", 0) or 0)
        if self.dim <= 0:
            raise RuntimeError(f"could not determine embedding dimension for {self.model}")

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        self._load()
        torch = self._torch
        assert torch is not None and self._tokenizer is not None and self._model is not None
        vectors: list[list[float]] = []
        batch_size = max(1, int(os.environ.get("BOOKCOMPILER_EMBED_BATCH", "16")))
        use_cls = "bge" in self.model.lower() and "m3" not in self.model.lower()
        for start in range(0, len(texts), batch_size):
            batch = [str(text or "") for text in texts[start:start + batch_size]]
            encoded = self._tokenizer(
                batch,
                padding=True,
                truncation=True,
                max_length=self.max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(self.device) for key, value in encoded.items()}
            with torch.inference_mode():
                output = self._model(**encoded).last_hidden_state
                if use_cls:
                    pooled = output[:, 0]
                else:
                    mask = encoded["attention_mask"].unsqueeze(-1).to(output.dtype)
                    pooled = (output * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-6)
                pooled = torch.nn.functional.normalize(pooled, p=2, dim=1)
            vectors.extend(pooled.detach().float().cpu().tolist())
        return vectors


class OpenAICompatibleEmbedder(EmbeddingBackend):
    """Small OpenAI-compatible /embeddings client using only urllib.

    Configure with BOOKCOMPILER_EMBED_BASE_URL, BOOKCOMPILER_EMBED_MODEL and
    optionally BOOKCOMPILER_EMBED_API_KEY. No request is made unless configured.
    """

    def __init__(self, base_url: str, model: str, api_key: str = "", dim: int = DEFAULT_DIM, timeout: float = 30.0) -> None:
        super().__init__(model=model, dim=dim, kind="openai-compatible")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = json.dumps({"model": self.model, "input": list(texts)}, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/embeddings",
            data=payload,
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        items = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
        vectors = [_normalize([float(value) for value in item["embedding"]]) for item in items]
        if len(vectors) != len(texts):
            raise RuntimeError(f"embedding backend returned {len(vectors)} vectors for {len(texts)} inputs")
        return vectors


def _default_neural_model() -> str:
    configured = os.environ.get("BOOKCOMPILER_EMBED_MODEL", "").strip()
    if configured:
        return configured
    local = Path(r"D:\models\bge-small-zh-v1.5")
    return str(local) if local.is_dir() else DEFAULT_NEURAL_MODEL


_EMBEDDER_CACHE: dict[tuple[object, ...], EmbeddingBackend] = {}


def clear_embedder_cache() -> None:
    """Drop cached model handles (used by tests and diagnostics)."""
    _EMBEDDER_CACHE.clear()


def get_embedder(allow_remote: bool = True) -> EmbeddingBackend:
    """Return a process-wide embedding backend.

    Loading a neural model is expensive (seconds and hundreds of MB).  A new
    backend used to be constructed for every retrieval call, which reloaded BGE
    each time.  The cache key includes every environment value that changes the
    vector space, so switching models or falling back to the local backend can
    never reuse a stale object.
    """
    load_env()
    backend_name = os.environ.get("BOOKCOMPILER_EMBED_BACKEND", "local").strip().lower()
    base_url = os.environ.get("BOOKCOMPILER_EMBED_BASE_URL", "").strip()
    model = os.environ.get("BOOKCOMPILER_EMBED_MODEL", "").strip()
    device = os.environ.get("BOOKCOMPILER_EMBED_DEVICE", "auto").strip() or "auto"
    local_dim = int(os.environ.get("BOOKCOMPILER_LOCAL_EMBED_DIM", str(DEFAULT_DIM)))
    remote_dim = int(os.environ.get("BOOKCOMPILER_EMBED_DIM", str(DEFAULT_DIM)))
    key = (allow_remote, backend_name, base_url, model, device, local_dim, remote_dim)
    cached = _EMBEDDER_CACHE.get(key)
    if cached is not None:
        return cached

    if not allow_remote:
        backend: EmbeddingBackend = EmbeddingBackend(
            model=LOCAL_MODEL,
            dim=local_dim,
            kind="local",
        )
    elif backend_name in {"neural", "transformers", "sentence-transformers", "st"}:
        backend = NeuralEmbedder(
            model=_default_neural_model(),
            device=device,
        )
    elif backend_name in {"openai", "remote", "openai-compatible"} and base_url and model:
        backend = OpenAICompatibleEmbedder(
            base_url=base_url,
            model=model,
            api_key=os.environ.get("BOOKCOMPILER_EMBED_API_KEY", "").strip(),
            dim=remote_dim,
        )
    else:
        backend = EmbeddingBackend(
            model=LOCAL_MODEL,
            dim=local_dim,
            kind="local",
        )
    _EMBEDDER_CACHE[key] = backend
    return backend


def embed_texts(texts: Iterable[str], backend: EmbeddingBackend | None = None, batch_size: int = 32) -> list[list[float]]:
    backend = backend or get_embedder()
    values = list(texts)
    output: list[list[float]] = []
    for start in range(0, len(values), batch_size):
        batch = values[start:start + batch_size]
        # Do not silently mix local hash vectors into a remote model's index.
        # Store.embed_pending() catches a backend failure and retries with the
        # local backend so the persisted model name matches the vector space.
        output.extend(backend.embed(batch))
    return output