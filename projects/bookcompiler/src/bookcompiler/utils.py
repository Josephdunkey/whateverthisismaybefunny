from __future__ import annotations

import hashlib
import re
import unicodedata


_WS_RE = re.compile(r"\s+")


def stable_id(*parts: str, length: int = 16) -> str:
    raw = "\x1f".join(str(p).strip() for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def normalize_text(text: str, preserve_paragraphs: bool = False) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    replacements = {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if preserve_paragraphs:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    return _WS_RE.sub(" ", text).strip()


def normalize_for_quote(text: str) -> str:
    return normalize_text(text).lower()


def split_sentences(text: str) -> list[str]:
    text = normalize_text(text)
    if not text:
        return []
    pieces = re.split(r"(?<=[.!?。！？；;])\s+|(?<=[。！？；;])", text)
    return [p.strip() for p in pieces if p and p.strip()]


def dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = normalize_for_quote(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out