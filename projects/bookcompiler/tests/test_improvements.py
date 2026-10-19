from __future__ import annotations

from pathlib import Path

from bookcompiler.analysis import create_analysis
from bookcompiler.claims import build_claims
from bookcompiler.compiler import compile_book
from bookcompiler.embeddings import clear_embedder_cache, get_embedder
from bookcompiler.modes import build_proposal, select_books
from bookcompiler.parsing import parse_book
from bookcompiler.render import render_memo
from bookcompiler.store import Store
from bookcompiler.utils import stable_id

from tests.helpers import compile_verified, mark_verified


def _seed_book(store: Store, tmp_path: Path, name: str, title: str, disciplines: list[str], body: str):
    path = tmp_path / name
    path.write_text(f"# {title}\n\n## Chapter 1\n\n{body}\n", encoding="utf-8")
    parsed = parse_book(path, title=title, author="Tester", disciplines=disciplines)
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    return parsed


def _seed_claims_book(store: Store, tmp_path: Path):
    title = "\u8d27\u5e01\u653f\u7b56\u7b14\u8bb0"
    body = (
        "\u592e\u884c\u964d\u51c6\u5bfc\u81f4\u5546\u4e1a\u94f6\u884c\u6d41\u52a8\u6027\u660e\u663e\u589e\u52a0\u3002"
        "\u5982\u679c\u6d41\u52a8\u6027\u589e\u52a0\uff0c"
        "\u94f6\u884c\u4f1a\u6269\u5927\u4fe1\u8d37\u6295\u653e\u5e76\u63a8\u52a8"
        "\u8d44\u4ea7\u4ef7\u683c\u4e0a\u6da8\uff0c"
        "\u56e0\u6b64\u9700\u8981\u5173\u6ce8\u91d1\u878d\u98ce\u9669\u3002"
    )
    return _seed_book(store, tmp_path, "claims.md", title, ["economics"], body)


def _manual_claim(book_id: str, chunk, suffix: str, subject: str, obj: str, polarity: int = 1) -> dict:
    return {
        "claim_id": stable_id("claim", book_id, chunk.chunk_id, suffix),
        "claim_key": f"{subject}|causes|{obj}|{polarity}",
        "base_key": f"{subject}|causes",
        "subject": subject,
        "subject_entity_id": "",
        "predicate": "causes",
        "object": obj,
        "polarity": polarity,
        "conditions": [],
        "chunk_id": chunk.chunk_id,
        "page": chunk.page_start,
        "quote": chunk.text,
        "confidence": 0.8,
    }


def test_heuristic_compile_is_not_reported_as_learned(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester", disciplines=["economics"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)

    compile_book(store, parsed.book_id)

    assert store.get_book(parsed.book_id)["status"] == "ingested"
    assert store.learned_book_ids() == set()

    mark_verified(tmp_path / "library.db", parsed.book_id)
    assert store.get_book(parsed.book_id)["status"] == "compiled"
    assert parsed.book_id in store.learned_book_ids()


def test_replace_claims_keeps_superseded_and_reviewed_claims(tmp_path):
    store = Store(tmp_path / "library.db")
    parsed = _seed_claims_book(store, tmp_path)
    chunk = store.get_chunks(parsed.book_id)[0]
    old = _manual_claim(
        parsed.book_id, chunk, "old",
        "\u964d\u51c6", "\u94f6\u884c\u6d41\u52a8\u6027\u589e\u52a0",
    )
    store.replace_claims(parsed.book_id, [old])
    store.set_claim_status(old["claim_id"], "superseded", "reviewed: replaced by a newer claim")

    new = _manual_claim(
        parsed.book_id, chunk, "new",
        "\u964d\u51c6", "\u94f6\u884c\u4fe1\u8d37\u6269\u5f20",
    )
    store.replace_claims(parsed.book_id, [new])

    assert store.get_claim(old["claim_id"]) is not None
    assert store.get_claim(new["claim_id"]) is not None


def test_analysis_uses_claim_graph_and_renders_it(tmp_path):
    store = Store(tmp_path / "library.db")
    parsed = _seed_claims_book(store, tmp_path)
    result = build_claims(store, book_ids=[parsed.book_id], replace=True)
    assert result["claims"] >= 1

    question = "\u964d\u51c6\u5bf9\u94f6\u884c\u4fe1\u8d37\u6709\u4ec0\u4e48\u5f71\u54cd"
    proposal = build_proposal(store, "auto", question, ["economics"])
    packet = create_analysis(store, question, ["economics"], proposal, "auto")

    assert packet.claims
    assert any("\u964d\u51c6" in str(claim.get("quote", "")) for claim in packet.claims)
    memo = render_memo(packet.to_dict())
    assert "Claim graph" in memo


def test_select_books_uses_batched_retrieval(tmp_path, monkeypatch):
    store = Store(tmp_path / "library.db")
    for name, title, discipline, body in [
        ("econ.md", "Economics of Policy", "economics", "When prices change, incentives change and firms delay investment."),
        ("politics.md", "Politics of Reform", "politics", "A government must build a coalition. Veto players can block implementation."),
        ("law.md", "Law of Regulation", "law", "A regulator must act within statutory authority. Courts may stay a rule."),
    ]:
        _seed_book(store, tmp_path, name, title, [discipline], body)

    calls: list[tuple] = []
    original = store.search_chunks

    def counting_search(query, book_ids=None, limit=12, mode="hybrid"):
        calls.append((query, tuple(book_ids or ()), limit, mode))
        return original(query, book_ids=book_ids, limit=limit, mode=mode)

    monkeypatch.setattr(store, "search_chunks", counting_search)
    books = select_books(
        store,
        "bank lending regulation",
        ["economics", "politics", "law"],
        direction="legal regulation and statutory authority",
    )

    assert books
    assert len(calls) <= 2, calls


def test_embedder_is_cached_per_configuration():
    clear_embedder_cache()
    try:
        assert get_embedder() is get_embedder()
    finally:
        clear_embedder_cache()


def test_superseded_claim_is_not_reported_as_a_live_conflict(tmp_path):
    store = Store(tmp_path / "library.db")
    parsed = _seed_claims_book(store, tmp_path)
    chunk = store.get_chunks(parsed.book_id)[0]
    left = _manual_claim(
        parsed.book_id, chunk, "left",
        "\u592e\u884c\u964d\u51c6", "\u6d41\u52a8\u6027\u589e\u52a0", polarity=1,
    )
    right = _manual_claim(
        parsed.book_id, chunk, "right",
        "\u592e\u884c\u964d\u51c6", "\u6d41\u52a8\u6027\u51cf\u5c11", polarity=-1,
    )
    store.replace_claims(parsed.book_id, [left, right])
    store.add_claim_relation(left["claim_id"], right["claim_id"], "contradicts", 0.6)
    assert store.get_claim_conflicts(book_ids=[parsed.book_id])

    store.set_claim_status(left["claim_id"], "superseded", "reviewed: replaced by newer evidence")

    assert store.get_claim_conflicts(book_ids=[parsed.book_id]) == []


def test_embedding_scores_do_not_mix_vector_dimensions(tmp_path):
    from bookcompiler.retrieval import _embedding_values

    store = Store(tmp_path / "library.db")
    rows = [{"chunk_id": "chunk-a"}]
    values = _embedding_values(
        store,
        rows,
        {"chunk-a": [1.0, 0.0]},
        [1.0, 0.0, 0.0],
        "model-a",
        version=(1, 2, 3, 4),
    )
    assert values == [0.0]
