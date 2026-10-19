import json
from pathlib import Path

from bookcompiler.analysis import create_analysis
from tests.helpers import compile_verified
from bookcompiler.entities import align_entities, alignment_audit, detect_entities
from bookcompiler.evolution import decide_evolution, get_evolution_config, propose_evolutions
from bookcompiler.mcp import BookCompilerMCP
from bookcompiler.modes import build_proposal
from bookcompiler.parsing import parse_book
from bookcompiler.retrieval import _quality_multiplier, hybrid_search
from bookcompiler.store import Store


def _book(tmp_path, name, text, title, disciplines=None):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return parse_book(path, title=title, author="Tester", disciplines=disciplines or ["economics", "politics", "law"])


def test_local_embedding_and_hybrid_search(tmp_path):
    store = Store(tmp_path / "library.db")
    relevant = _book(
        tmp_path,
        "relevant.txt",
        "中央银行通过降准释放流动性。地方政府融资平台依靠土地出让收入维持基建投资。"
        "银行体系因此承担了部分信用风险，地方政府债务的期限错配可能上升。",
        "货币与财政",
        ["economics", "politics", "law"],
    )
    distractor = _book(
        tmp_path,
        "distractor.txt",
        "法国文学中的叙事视角与人物心理描写。小说语言、修辞和文学批评方法。",
        "文学批评",
        ["literature"],
    )
    store.add_book(relevant)
    store.add_book(distractor)
    align_entities(store)

    hits = hybrid_search(store, "降准之后地方政府债务风险如何传导到银行体系", limit=5)
    assert hits
    assert hits[0]["book_id"] == relevant.book_id
    breakdown = hits[0]["score_breakdown"]
    assert breakdown["embedding"] > 0
    assert breakdown["bm25"] > 0
    # The query mentions three detected entities; the relevant chunk contains
    # all of them, so it should receive the full multi-entity bonus.
    assert breakdown["entity"] == 1.0
    assert len(hits[0]["matched_entities"]) >= 2
    assert "存款准备金率" in [item["canonical_name"] for item in detect_entities(store, "降准")]
    stats = store.embedding_stats()
    assert stats["coverage"] == 1.0

    store.set_state(
        "evolution_config",
        {"retrieval": {"bm25_weight": 0.0, "embedding_weight": 1.0, "entity_weight": 0.0}},
    )
    evolved = hybrid_search(store, "\u964d\u51c6\u4e4b\u540e\u5730\u65b9\u653f\u5e9c\u503a\u52a1\u98ce\u9669\u5982\u4f55\u4f20\u5bfc\u5230\u94f6\u884c\u4f53\u7cfb", limit=5)
    assert evolved
    weights = evolved[0]["score_breakdown"]["weights"]
    assert weights["bm25"] == 0.0
    assert weights["embedding"] == 1.0
    assert weights["entity"] == 0.0
    store.close()


def test_entity_alignment_merges_aliases_across_books(tmp_path):
    store = Store(tmp_path / "library.db")
    first = _book(tmp_path, "a.txt", "地方政府融资平台通过城投平台举债，土地出让收入用于偿还债务。", "财政A")
    second = _book(tmp_path, "b.txt", "融资平台和城投平台的债务受到银行体系约束。", "财政B")
    store.add_book(first)
    store.add_book(second)
    store.save_book_card(first.book_id, {"status": "draft", "key_concepts": ["地方政府融资平台"], "lenses": ["economics"]})
    store.save_book_card(second.book_id, {"status": "draft", "key_concepts": ["融资平台"], "lenses": ["economics"]})

    stats = align_entities(store)
    assert stats["cross_book_entities"] >= 1
    matches = [item for item in store.list_entities(cross_book_only=True) if item["canonical_name"] == "地方政府融资平台"]
    assert len(matches) == 1
    assert matches[0]["book_count"] == 2
    aliases = matches[0]["aliases"]
    assert "融资平台" in aliases
    assert "城投平台" in aliases
    store.close()


def test_mcp_handshake_lists_tools_and_serves_library(tmp_path):
    store = Store(tmp_path / "library.db")
    parsed = _book(tmp_path, "c.txt", "央行通过公开市场操作提供流动性。", "小书")
    store.add_book(parsed)
    store.close()

    server = BookCompilerMCP(tmp_path / "library.db")
    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
    assert init["result"]["serverInfo"]["name"] == "bookcompiler"
    listing = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = {tool["name"] for tool in listing["result"]["tools"]}
    assert {"book_library", "book_plan", "book_recall", "book_analyze"} <= names
    called = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "book_library", "arguments": {}}})
    payload = json.loads(called["result"]["content"][0]["text"])
    assert payload["total_books"] == 1
    assert payload["learned_books"] == 0
    assert payload["ingested_books"] == 1


def test_mcp_requires_explicit_consent_for_direction_mode(tmp_path):
    store = Store(tmp_path / "library.db")
    parsed = _book(tmp_path, "d.txt", "银行信贷与地方政府债务影响金融稳定。", "小书")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    store.close()

    server = BookCompilerMCP(tmp_path / "library.db")
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "book_analyze",
                "arguments": {"question": "地方债务风险", "mode": "direction", "direction": "地方财政"},
            },
        }
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["requires_confirmation"] is True


def test_evolution_promotion_applies_bounded_config_and_rolls_back(tmp_path):
    store = Store(tmp_path / "library.db")
    parsed = _book(tmp_path, "e.txt", "\u4e2d\u592e\u94f6\u884c\u901a\u8fc7\u964d\u51c6\u5f71\u54cd\u94f6\u884c\u4f53\u7cfb\u6d41\u52a8\u6027\u3002\u5730\u65b9\u653f\u5e9c\u503a\u52a1\u4e0e\u571f\u5730\u8d22\u653f\u76f8\u5173\u3002 Banks must manage liquidity risk.", "\u5c0f\u4e66")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    proposal = build_proposal(store, "auto", "降准与地方债务", ["economics", "politics", "law"])
    packet = create_analysis(store, "降准与地方债务", ["economics", "politics", "law"], proposal, "auto")
    store.add_feedback(packet.analysis_id, 5, "good", preferred_book_ids=[parsed.book_id])
    item = propose_evolutions(store)[0]
    proposal_id = item["proposal_id"]

    decide_evolution(store, proposal_id, "accepted")
    decide_evolution(store, proposal_id, "shadow")
    report = {
        "case_count": 1,
        "structural_pass_count": 1,
        "cases": [{"case_id": "case-1", "structural_pass": True, "issues": []}],
    }
    promoted = decide_evolution(store, proposal_id, "promoted", "clean replay", report)
    assert promoted["status"] == "promoted"
    config = get_evolution_config(store)
    assert config["preference_overrides"]["books"][parsed.book_id] >= 1.5
    assert config["revision"] >= 1

    rolled = decide_evolution(store, proposal_id, "rolled_back", "rollback")
    assert rolled["status"] == "rolled_back"
    assert parsed.book_id not in get_evolution_config(store)["preference_overrides"]["books"]
    store.close()


def test_retrieval_miss_generates_executable_weight_patch(tmp_path):
    store = Store(tmp_path / "library.db")
    parsed = _book(tmp_path, "f.txt", "\u592e\u884c\u901a\u8fc7\u964d\u51c6\u91ca\u653e\u6d41\u52a8\u6027\uff0c\u94f6\u884c\u4f53\u7cfb\u4fe1\u8d37\u6269\u5f20\u3002", "\u8d27\u5e01\u4e0e\u94f6\u884c")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    store.add_feedback("analysis-test", 2, "the passage existed but was missed", error_labels=["retrieval_miss"])

    proposals = propose_evolutions(store)
    candidate = next(
        item for item in proposals
        if item.get("change", {}).get("kind") == "retrieval_weight_adjustment"
    )
    assert candidate["change"]["bm25_weight"] < 0.55
    assert candidate["change"]["embedding_weight"] > 0.35

    proposal_id = candidate["proposal_id"]
    decide_evolution(store, proposal_id, "accepted")
    decide_evolution(store, proposal_id, "shadow")
    report = {
        "case_count": 1,
        "structural_pass_count": 1,
        "cases": [{"case_id": "case-1", "structural_pass": True, "issues": []}],
    }
    decide_evolution(store, proposal_id, "promoted", "clean replay", report)
    retrieval = get_evolution_config(store)["retrieval"]
    assert retrieval["bm25_weight"] < 0.55
    assert retrieval["embedding_weight"] > 0.35
    store.close()


def test_mcp_recall_excludes_ingested_but_unlearned_books(tmp_path):
    store = Store(tmp_path / "library.db")
    parsed = _book(tmp_path, "g.txt", "\u5730\u65b9\u653f\u5e9c\u503a\u52a1\u4e0e\u94f6\u884c\u4f53\u7cfb\u3002", "\u672a\u5b66\u4e60")
    store.add_book(parsed)
    store.close()

    server = BookCompilerMCP(tmp_path / "library.db")
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": "book_recall", "arguments": {"query": "\u5730\u65b9\u653f\u5e9c\u503a\u52a1", "book_ids": [parsed.book_id]}},
        }
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["evidence"] == []
    assert payload["ignored_unlearned_book_ids"] == [parsed.book_id]
    assert "warning" in payload


def test_hybrid_search_backfills_missing_embeddings(tmp_path):
    store = Store(tmp_path / "library.db")
    first = _book(tmp_path, "first.txt", "Central bank liquidity and credit expansion.", "First")
    store.add_book(first)
    store.embed_pending()
    second = _book(tmp_path, "second.txt", "Local government debt and bank risk.", "Second")
    store.add_book(second)
    second_chunk_ids = [chunk.chunk_id for chunk in store.get_chunks(second.book_id)]
    placeholders = ",".join("?" for _ in second_chunk_ids)
    store.conn.execute(f"DELETE FROM chunk_embeddings WHERE chunk_id IN ({placeholders})", second_chunk_ids)
    store.conn.commit()
    before = store.embedding_stats()
    assert before["coverage"] < 1.0

    hits = hybrid_search(store, "local government debt bank risk", limit=5)
    after = store.embedding_stats()
    assert hits
    assert after["coverage"] == 1.0
    assert after["missing_chunks"] == 0
    assert hits[0]["retrieval"]["embedding_covered"] == 2
    store.close()


def test_quality_multiplier_downranks_index_pages():
    index_page = "\u53e6\u53c2\u89c1 123,45,67,89 \u53c2\u89c1 90,12,34 \u7d22\u5f15 55,66,77"
    toc_page = (
        "\u4e13\u680f\n\u4e13\u680f1\n\u7ecf\u6d4e\u5b66\u4e2d\u7684\u7ed3\u6784\u4e3b\u4e49\u601d\u60f3\n"
        "\u4e13\u680f21\n\u5168\u7403\u5931\u8861\u7684\u4e89\u8bba\n\u4e13\u680f3\n\u4e13\u680f4 \u4e13\u680f5\n"
        "\u4e13\u680f6 \u4e13\u680f7\n\u7b2c\u4e00\u7ae0 \u7b2c\u4e8c\u7ae0 \u7b2c\u4e09\u7ae0 \u7b2c\u56db\u7ae0\n"
        "\u76ee 5 41 80 161 257\n265 269:290\n\u5f55 5"
    )
    argument = "Local government debt can transfer risk into the banking system when collateral values fall."
    assert _quality_multiplier({"text": index_page}) < 0.8
    assert _quality_multiplier({"text": toc_page}) < 0.7
    assert _quality_multiplier({"text": argument}) == 1.0


def test_alignment_audit_surfaces_near_duplicates_without_merging(tmp_path):
    store = Store(tmp_path / "library.db")
    first = _book(
        tmp_path,
        "audit-a.txt",
        "Local government debt risk is discussed together with local government debt.",
        "Audit A",
    )
    second = _book(
        tmp_path,
        "audit-b.txt",
        "Local government debt risk appears in a second book.",
        "Audit B",
    )
    store.add_book(first)
    store.add_book(second)
    first_chunk = store.get_chunks(first.book_id)[0]
    second_chunk = store.get_chunks(second.book_id)[0]
    store.replace_entity_graph(
        [
            {
                "entity_id": "audit-left",
                "canonical_name": "Local government debt",
                "entity_type": "concept",
                "aliases": ["Local government debt"],
            },
            {
                "entity_id": "audit-right",
                "canonical_name": "Local government liabilities",
                "entity_type": "concept",
                "aliases": ["Local government liabilities"],
            },
        ],
        [
            {
                "entity_id": "audit-left",
                "chunk_id": first_chunk.chunk_id,
                "book_id": first.book_id,
                "surface": "Local government debt",
                "confidence": 1.0,
            },
            {
                "entity_id": "audit-right",
                "chunk_id": second_chunk.chunk_id,
                "book_id": second.book_id,
                "surface": "Local government liabilities",
                "confidence": 1.0,
            },
        ],
        [],
    )
    before = store.entity_stats()
    audit = alignment_audit(store)
    after = store.entity_stats()
    assert audit["candidate_count"] >= 1
    names = {
        (item["left"]["canonical_name"], item["right"]["canonical_name"])
        for item in audit["candidates"]
    }
    assert any("local government debt" in left.lower() and "local government" in right.lower() for left, right in names)
    assert audit["note"]
    assert before == after
    store.close()


def test_cross_lingual_terms_bridge_chinese_to_english():
    from bookcompiler.retrieval import _cross_lingual_terms

    terms = _cross_lingual_terms("逻辑谬误与法律论证")
    assert "logic" in terms
    assert "fallacy" in terms or "fallacies" in terms
    assert "argument" in terms
    assert _cross_lingual_terms("hello world") == []
