from pathlib import Path

import pytest

from bookcompiler import llm_compile as lc
from bookcompiler.llm_compile import ReaderRefused
from bookcompiler.parsing import parse_book


def _book(tmp_path):
    parsed = parse_book(
        Path("examples/sample_book.md"),
        title="Policy Shocks",
        author="Tester",
        disciplines=["economics", "politics", "law"],
    )
    return parsed


def test_frameworks_nested_inside_book_card_are_accepted(tmp_path):
    parsed = _book(tmp_path)
    chunks = parsed.chunks
    quote = chunks[0].text[:60]
    frames = []
    for index in range(3):
        frames.append(
            {
                "name": f"Nested framework {index}",
                "one_liner": "Trace how a policy changes incentives and who can block it.",
                "lenses": ["economics"],
                "citations": [{"chunk_id": chunks[index % len(chunks)].chunk_id, "quote": quote}],
            }
        )
    raw = {
        "book_card": {
            "one_line_thesis": "Policy shocks change prices, coalitions, and legal authority.",
            "key_concepts": ["incentives", "coalition", "jurisdiction"],
            "chapter_coverage": [],
            "frameworks": frames,
        }
    }
    patch = lc.normalise_patch(
        {"book_id": parsed.book_id, "title": parsed.title, "author": parsed.author},
        raw,
        chunks,
        chunks,
    )
    assert len(patch["frameworks"]) == 3
    assert all(framework["citations"] for framework in patch["frameworks"])


def test_deepseek_reader_is_blocked_without_opt_in(monkeypatch):
    monkeypatch.setenv("BOOKCOMPILER_READER_PROVIDER", "openai-compatible")
    monkeypatch.setenv("BOOKCOMPILER_READER_MODEL", "deepseek-chat")
    monkeypatch.setenv("BOOKCOMPILER_READER_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("BOOKCOMPILER_READER_API_KEY", "test-key")
    monkeypatch.delenv("BOOKCOMPILER_READER_ALLOW_DEEPSEEK", raising=False)
    with pytest.raises(lc.LLMCompileError, match="DeepSeek"):
        lc._reader_config()


def test_non_deepseek_reader_is_allowed(monkeypatch):
    monkeypatch.setenv("BOOKCOMPILER_READER_PROVIDER", "openai-compatible")
    monkeypatch.setenv("BOOKCOMPILER_READER_MODEL", "mimo-v2.6-flash")
    monkeypatch.setenv("BOOKCOMPILER_READER_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
    monkeypatch.setenv("BOOKCOMPILER_READER_API_KEY", "test-key")
    config = lc._reader_config()
    assert config.model == "mimo-v2.6-flash"


def test_guardrail_envelope_is_reported_as_refusal():
    raw = '{"status":"rejected","reason":"The request was considered high risk"}'
    with pytest.raises(ReaderRefused, match="high risk"):
        lc._extract_json(raw)


def test_valid_card_is_not_mistaken_for_a_refusal():
    raw = '{"book_card":{"one_line_thesis":"A long enough thesis sentence."}}'
    assert lc._extract_json(raw)["book_card"]["one_line_thesis"].startswith("A long")


def test_cli_overrides_still_hit_the_deepseek_guard(monkeypatch):
    monkeypatch.setenv("BOOKCOMPILER_READER_PROVIDER", "openai-compatible")
    monkeypatch.setenv("BOOKCOMPILER_READER_MODEL", "mimo-v2.6-flash")
    monkeypatch.setenv("BOOKCOMPILER_READER_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
    monkeypatch.setenv("BOOKCOMPILER_READER_API_KEY", "test-key")
    monkeypatch.delenv("BOOKCOMPILER_READER_ALLOW_DEEPSEEK", raising=False)
    with pytest.raises(lc.LLMCompileError, match="DeepSeek"):
        lc._reader_config(model_override="deepseek-chat", base_url_override="https://api.deepseek.com/v1")


def test_reader_timeout_env_is_honoured(monkeypatch):
    monkeypatch.setenv("BOOKCOMPILER_READER_PROVIDER", "openai-compatible")
    monkeypatch.setenv("BOOKCOMPILER_READER_MODEL", "mimo-v2.6-flash")
    monkeypatch.setenv("BOOKCOMPILER_READER_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
    monkeypatch.setenv("BOOKCOMPILER_READER_API_KEY", "test-key")
    monkeypatch.setenv("BOOKCOMPILER_READER_TIMEOUT", "1800")
    assert lc._reader_config().timeout == 1800.0
