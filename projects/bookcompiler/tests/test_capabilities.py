import copy
import json
from pathlib import Path

from tests.helpers import compile_verified
from bookcompiler.capabilities import (
    _content_signature,
    _keywords,
    _trigger_keywords,
    build_capability,
    evaluate_capability,
    list_capabilities,
    route_capability,
    update_capability,
)
from bookcompiler.mcp import TOOLS, BookCompilerMCP
from bookcompiler.parsing import parse_book
from bookcompiler.store import Store


def _seed(store: Store, tmp_path: Path) -> list[str]:
    specs = [
        (
            "Alpha Economics",
            ["economics"],
            "# Alpha Economics\n\n## Chapter 1\n\nWhen credit expands, banks lower lending standards and asset prices rise. A central bank can tighten liquidity, but the timing and transmission are uncertain.\n",
        ),
        (
            "Beta Politics",
            ["politics"],
            "# Beta Politics\n\n## Chapter 1\n\nLocal governments bargain with the center over fiscal resources. Implementation depends on coalitions, veto players and administrative capacity.\n",
        ),
        (
            "Gamma Finance",
            ["finance"],
            "# Gamma Finance\n\n## Chapter 1\n\nLeverage accumulates during booms. A debt cycle ends when income cannot service debt, forcing deleveraging or restructuring.\n",
        ),
    ]
    ids: list[str] = []
    for index, (title, disciplines, body) in enumerate(specs):
        path = tmp_path / f"book-{index}.md"
        path.write_text(body, encoding="utf-8")
        parsed = parse_book(path, title=title, author="Tester", disciplines=disciplines)
        store.add_book(parsed)
        compile_verified(store, parsed.book_id)
        card = store.get_book_card(parsed.book_id) or {}
        card.update({
            "status": "verified",
            "confidence": "high",
            "assumptions": [f"assumption-{title}"],
            "limitations": [f"limitation-{title}"],
            "not_for": [f"not-for-{title}"],
        })
        store.save_book_card(parsed.book_id, card)
        if not store.list_frameworks(book_ids=[parsed.book_id]):
            store.replace_frameworks(parsed.book_id, [{
                "framework_id": f"fw-{parsed.book_id}",
                "book_id": parsed.book_id,
                "name": f"{title} Framework",
                "lenses": disciplines,
                "status": "verified",
                "confidence": "high",
                "one_liner": f"A test framework from {title}.",
                "applicable_when": ["credit or fiscal conditions change"],
                "inputs": ["conditions"],
                "steps": ["identify the constraint", "trace the transmission channel"],
                "outputs": ["a bounded judgment"],
                "failure_modes": ["ignoring implementation capacity"],
                "counterexamples": [],
                "citations": [],
            }])
        ids.append(parsed.book_id)
    return ids


def _write_pack(root: Path, domain: str, title: str, triggers: list[str], lenses: list[str]) -> None:
    directory = root / domain
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "domain": domain,
        "title": title,
        "version": "1.0.0",
        "status": "active",
        "lenses": lenses,
        "books": [{"book_id": f"{domain}-book", "title": f"{title} Book"}],
        "frameworks": [],
        "claims": [],
        "entities": [],
        "debates": [],
        "routing": {"triggers": triggers},
    }
    (directory / "pack.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_build_capability_creates_files_and_uses_book_cards(tmp_path):
    store = Store(tmp_path / "library.db")
    ids = _seed(store, tmp_path)
    root = tmp_path / "packs"

    result = build_capability(
        store, "political-economy", book_ids=ids[:2], lenses=["economics", "politics"],
        root=root, title="Custom PE",
    )

    directory = root / "political-economy"
    for name in ("pack.json", "PACK.md", "sources.md", "frameworks.md", "debates.md", "boundaries.md", "eval.md", "LOCAL.md", "CHANGELOG.md"):
        assert (directory / name).is_file(), name
    assert (directory / "eval" / "golden.jsonl").is_file()
    assert (root / "index.json").is_file()
    assert result["version"] == "1.0.0"
    assert result["books"] == 2

    boundaries = (directory / "boundaries.md").read_text(encoding="utf-8")
    assert "limitation-Alpha Economics" in boundaries
    assert "assumption-Alpha Economics" in boundaries
    assert "not-for-Beta Politics" in boundaries


def test_build_is_idempotent_and_local_is_preserved(tmp_path):
    store = Store(tmp_path / "library.db")
    ids = _seed(store, tmp_path)
    root = tmp_path / "packs"

    first = build_capability(store, "political-economy", book_ids=ids[:1], root=root)
    local = root / "political-economy" / "LOCAL.md"
    local.write_text("# my notes\n\nkeep me\n", encoding="utf-8")

    second = build_capability(store, "political-economy", book_ids=ids[:1], root=root)

    assert first["version"] == second["version"] == "1.0.0"
    assert local.read_text(encoding="utf-8") == "# my notes\n\nkeep me\n"


def test_update_adds_book_preserves_metadata_and_local(tmp_path):
    store = Store(tmp_path / "library.db")
    ids = _seed(store, tmp_path)
    root = tmp_path / "packs"

    build_capability(
        store, "political-economy", book_ids=ids[:1], root=root,
        title="Custom title", description="Custom description",
        lenses=["economics", "politics"], direction="credit and fiscal",
    )
    local = root / "political-economy" / "LOCAL.md"
    local.write_text("local text\n", encoding="utf-8")

    proposal = update_capability(store, "political-economy", book_ids=[ids[1]], apply=False, root=root)
    assert proposal["applied"] is False
    assert proposal["added_books"] == [ids[1]]

    applied = update_capability(store, "political-economy", book_ids=[ids[0], ids[1]], apply=True, root=root)
    assert applied["applied"] is True
    assert applied["new_version"] == "1.1.0"
    assert applied["result"]["title"] == "Custom title"

    pack = json.loads((root / "political-economy" / "pack.json").read_text(encoding="utf-8"))
    assert pack["title"] == "Custom title"
    assert pack["description"] == "Custom description"
    assert pack["direction"] == "credit and fiscal"
    assert {item["book_id"] for item in pack["books"]} == {ids[0], ids[1]}
    assert local.read_text(encoding="utf-8") == "local text\n"


def test_domain_golden_sets_are_domain_specific(tmp_path):
    store = Store(tmp_path / "library.db")
    ids = _seed(store, tmp_path)
    root = tmp_path / "packs"

    build_capability(store, "macro-finance", book_ids=ids[:1], root=root)
    build_capability(store, "legal-reasoning", book_ids=ids[:1], root=root)

    macro = (root / "macro-finance" / "eval" / "golden.jsonl").read_text(encoding="utf-8")
    legal = (root / "legal-reasoning" / "eval" / "golden.jsonl").read_text(encoding="utf-8")
    assert '"mf-001"' in macro
    assert '"lg-001"' in legal
    assert '"pe-001"' not in macro
    assert '"pe-001"' not in legal


def test_route_clear_winner_is_automatic(tmp_path):
    store = Store(tmp_path / "library.db")
    root = tmp_path / "packs"
    _write_pack(root, "alpha", "Alpha", ["widget", "crisis", "supply"], ["economics"])
    _write_pack(root, "beta", "Beta", ["gadget"], ["law"])

    result = route_capability(store, "widget crisis supply shock", root=root)

    assert result["requires_confirmation"] is False
    assert result["selected"] == "alpha"
    assert len(result["candidates"]) <= 3


def test_route_close_scores_requires_confirmation(tmp_path):
    store = Store(tmp_path / "library.db")
    root = tmp_path / "packs"
    _write_pack(root, "alpha", "Alpha", ["widget", "crisis", "supply"], ["economics"])
    _write_pack(root, "beta", "Beta", ["widget", "crisis", "supply"], ["economics"])

    result = route_capability(store, "widget crisis supply shock", lenses=["economics"], root=root)

    assert result["requires_confirmation"] is True
    assert result["selected"] is None
    assert result["confirmation_reason"].startswith("close scores")
    assert result["margin"] == 0


def test_evaluate_capability_reports_coverage(tmp_path):
    store = Store(tmp_path / "library.db")
    ids = _seed(store, tmp_path)
    root = tmp_path / "packs"
    build_capability(store, "political-economy", book_ids=ids, root=root)

    result = evaluate_capability(store, "political-economy", limit=2, root=root)

    assert result["ok"] is True
    assert result["mode"] == "coverage"
    assert result["cases"] == 2
    assert 0.0 <= result["overall"] <= 1.0
    assert (root / "political-economy" / "eval" / "last-run.json").is_file()


def test_mcp_exposes_and_routes_book_capability(tmp_path):
    assert "book_capability" in {tool["name"] for tool in TOOLS}
    root = tmp_path / "packs"
    _write_pack(root, "alpha", "Alpha", ["widget", "crisis", "supply"], ["economics"])

    server = BookCompilerMCP(tmp_path / "library.db")
    result = server.call_tool(
        "book_capability",
        {"action": "route", "query": "widget crisis supply shock", "root": str(root)},
    )

    assert result["ok"] is True
    assert result["selected"] == "alpha"


def test_content_signature_changes_when_claim_text_changes():
    payload = {
        "domain": "alpha",
        "title": "Alpha",
        "claims": [{"claim_id": "claim-1", "quote": "old quote"}],
    }
    changed = copy.deepcopy(payload)
    changed["claims"][0]["quote"] = "new quote"

    assert _content_signature(payload) != _content_signature(changed)


def test_keyword_extraction_handles_chinese_punctuation_and_english_phrases():
    chinese = "\u4ee5\u5229\u4e3a\u5229\uff1a\u8d22\u653f\u5173\u7cfb\u4e0e\u5730\u65b9\u653f\u5e9c\u884c\u4e3a"
    assert _keywords([chinese]) == [
        "\u4ee5\u5229\u4e3a\u5229",
        "\u8d22\u653f\u5173\u7cfb\u4e0e\u5730\u65b9\u653f\u5e9c\u884c\u4e3a",
    ]
    assert _trigger_keywords("Deductive Validity Test") == ["deductive validity test"]
    mixed = "IB-EB \u5185\u5916\u5747\u8861\u7684\u653f\u7b56\u642d\u914d"
    assert "ib" not in _trigger_keywords(mixed)
    assert "eb" not in _trigger_keywords(mixed)


def test_coverage_requires_all_expected_topics(tmp_path):
    store = Store(tmp_path / "library.db")
    ids = _seed(store, tmp_path)
    root = tmp_path / "packs"
    build_capability(store, "political-economy", book_ids=ids[:1], root=root)

    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps({
        "id": "strict-1",
        "event": "credit conditions changed",
        "lenses": ["economics"],
        "expected_books": ["Alpha Economics"],
        "expected_frameworks": ["Alpha Economics Framework"],
        "expected_topics": ["missing-topic"],
        "expected_conflicts": False,
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    result = evaluate_capability(
        store, "political-economy", cases_path=cases, root=root
    )

    assert result["scores"]["topic_coverage"] == 0.0
    assert result["failures"][0]["missing_topics"] == ["missing-topic"]


def test_build_bumps_patch_when_framework_content_changes(tmp_path):
    store = Store(tmp_path / "library.db")
    ids = _seed(store, tmp_path)
    root = tmp_path / "packs"

    first = build_capability(store, "political-economy", book_ids=ids[:1], root=root)
    frameworks = store.list_frameworks(book_ids=[ids[0]])
    frameworks[0]["one_liner"] = "Changed framework content."
    store.replace_frameworks(ids[0], frameworks)

    second = build_capability(store, "political-economy", book_ids=ids[:1], root=root)

    assert first["version"] == "1.0.0"
    assert second["version"] == "1.0.1"
    changelog = (root / "political-economy" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.count("# Changelog") == 1
    assert "## 1.0.1 |" in changelog


def test_list_capabilities_rebuilds_a_stale_index(tmp_path):
    root = tmp_path / "packs"
    _write_pack(root, "alpha", "Alpha", ["widget"], ["economics"])
    assert list_capabilities(root=root)["total"] == 1

    _write_pack(root, "beta", "Beta", ["gadget"], ["law"])
    assert list_capabilities(root=root)["total"] == 2


def test_mcp_capability_eval_uses_limit_cases_not_route_limit(tmp_path):
    store = Store(tmp_path / "library.db")
    ids = _seed(store, tmp_path)
    root = tmp_path / "packs"
    build_capability(store, "political-economy", book_ids=ids[:1], root=root)
    store.close()

    tool = next(item for item in TOOLS if item["name"] == "book_capability")
    assert "limit_cases" in tool["inputSchema"]["properties"]

    server = BookCompilerMCP(tmp_path / "library.db")
    result = server.call_tool(
        "book_capability",
        {
            "action": "eval",
            "domain": "political-economy",
            "root": str(root),
            "limit_cases": 2,
        },
    )

    assert result["ok"] is True
    assert result["cases"] == 2


def test_route_with_no_packs_returns_a_stable_shape(tmp_path):
    store = Store(tmp_path / "library.db")
    result = route_capability(store, "anything", root=tmp_path / "empty")
    store.close()

    assert result["ok"] is True
    assert result["top"] is None
    assert result["requires_confirmation"] is True
    assert result["confirmation_reason"] == "no capability packs"
