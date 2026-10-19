import json
from pathlib import Path

from bookcompiler.analysis import create_analysis
from bookcompiler.cli import main
from bookcompiler.mcp import BookCompilerMCP
from bookcompiler.modes import build_proposal
from bookcompiler.parsing import parse_book
from bookcompiler.render import render_memo, render_selection_card
from bookcompiler.source_gaps import recommend_sources
from bookcompiler.store import Store
from tests.helpers import compile_verified

QUERY = (
    "如果中国央行降准，银行信贷是否必然扩张？"
    "请同时从货币政策传导、地方政府财政激励和金融监管约束三个角度分析。"
)
LENSES = ["economics", "politics", "law"]


def _seed_learned_sample(store: Store) -> None:
    parsed = parse_book(
        Path("examples/sample_book.md"),
        title="Policy Shocks",
        author="Tester",
        disciplines=LENSES,
    )
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)


def test_bank_policy_question_recommends_missing_authoritative_laws(tmp_path):
    store = Store(tmp_path / "library.db")

    recommendations = recommend_sources(store, QUERY, LENSES)
    titles = [item["title"] for item in recommendations]

    assert "中华人民共和国中国人民银行法" in titles
    assert "中华人民共和国商业银行法" in titles
    assert "中华人民共和国银行业监督管理法" in titles
    assert recommendations[0]["title"] == "中华人民共和国中国人民银行法"
    assert recommendations[0]["action"] == "download_and_ingest"
    assert "bookcompiler ingest" in recommendations[0]["ingest_hint"]
    assert recommendations[0]["official_source"]
    store.close()


def test_existing_law_title_is_not_recommended_for_download(tmp_path):
    store = Store(tmp_path / "library.db")
    path = tmp_path / "pboc.md"
    path.write_text("# 中国人民银行法\n\n## 第一章\n\n中国人民银行依法制定和执行货币政策。\n", encoding="utf-8")
    parsed = parse_book(
        path,
        title="中华人民共和国中国人民银行法（2022修正）",
        author="全国人民代表大会",
        disciplines=["law", "finance"],
    )
    store.add_book(parsed)

    recommendations = recommend_sources(store, QUERY, LENSES)
    titles = [item["title"] for item in recommendations]

    assert "中华人民共和国中国人民银行法" not in titles
    assert "中华人民共和国商业银行法" in titles
    store.close()


def test_proposal_and_analysis_carry_source_gaps_and_next_checks(tmp_path):
    store = Store(tmp_path / "library.db")
    _seed_learned_sample(store)

    proposal = build_proposal(store, "auto", QUERY, LENSES)
    assert proposal.source_recommendations
    assert "中华人民共和国中国人民银行法" in {
        item["title"] for item in proposal.source_recommendations
    }

    packet = create_analysis(store, QUERY, LENSES, proposal, "auto")
    stored_gaps = packet.selection["source_recommendations"]
    assert stored_gaps
    assert any("中国人民银行法" in check for check in packet.next_checks)
    assert any("bookcompiler ingest" in item["ingest_hint"] for item in stored_gaps)
    store.close()


def test_selection_card_and_memo_surface_download_instruction(tmp_path):
    store = Store(tmp_path / "library.db")
    _seed_learned_sample(store)
    proposal = build_proposal(store, "auto", QUERY, LENSES)

    card = render_selection_card(proposal)
    assert "Suggested sources to download and ingest" in card
    assert "中华人民共和国中国人民银行法" in card
    assert "bookcompiler ingest" in card

    packet = create_analysis(store, QUERY, LENSES, proposal, "auto")
    memo = render_memo(packet.to_dict())
    assert "Suggested sources to download and ingest" in memo
    assert "中华人民共和国商业银行法" in memo
    store.close()


def test_mcp_book_plan_returns_source_recommendations(tmp_path):
    db = tmp_path / "library.db"
    Store(db).close()
    server = BookCompilerMCP(db)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {
                "name": "book_plan",
                "arguments": {"question": QUERY, "lenses": LENSES, "mode": "auto"},
            },
        }
    )
    payload = json.loads(response["result"]["content"][0]["text"])

    assert payload["source_recommendations"]
    assert payload["source_recommendations"][0]["title"] == "中华人民共和国中国人民银行法"


def test_mcp_book_analyze_surfaces_source_recommendations(tmp_path):
    db = tmp_path / "library.db"
    store = Store(db)
    _seed_learned_sample(store)
    store.close()
    server = BookCompilerMCP(db)
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {
                "name": "book_analyze",
                "arguments": {"question": QUERY, "lenses": LENSES, "mode": "auto"},
            },
        }
    )
    payload = json.loads(response["result"]["content"][0]["text"])

    assert payload["source_recommendations"]
    assert payload["source_recommendations"][0]["title"] == "中华人民共和国中国人民银行法"
    assert "Suggested sources to download and ingest" in payload["memo_markdown"]
    assert "download and ingest" in payload["instruction"]


def test_cli_source_gaps_prints_actionable_text(tmp_path, capsys):
    db = tmp_path / "library.db"
    code = main(
        [
            "--db",
            str(db),
            "source-gaps",
            "--query",
            QUERY,
            "--lenses",
            "economics",
            "politics",
            "law",
            "--format",
            "text",
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert "Source gap report" in output
    assert "Suggested sources to download and ingest" in output
    assert "中华人民共和国中国人民银行法" in output
    assert "bookcompiler ingest" in output


def test_unrelated_question_does_not_recommend_financial_laws(tmp_path):
    store = Store(tmp_path / "library.db")

    recommendations = recommend_sources(
        store,
        "如何评价一部法国小说的叙事视角与人物心理？",
        ["literature", "law"],
    )

    assert recommendations == []
    store.close()