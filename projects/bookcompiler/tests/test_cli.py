from pathlib import Path

from bookcompiler.cli import main
from tests.helpers import mark_verified


def test_cli_end_to_end_auto_mode(tmp_path, capsys):
    db = tmp_path / "library.db"
    assert main(["--db", str(db), "init"]) == 0
    assert main([
        "--db", str(db), "ingest", "examples/sample_book.md",
        "--title", "Policy Shocks", "--author", "Tester",
        "--discipline", "economics", "--discipline", "politics", "--discipline", "law",
    ]) == 0
    ingest_out = capsys.readouterr().out
    book_id = None
    for line in ingest_out.splitlines():
        if line.startswith("book_id="):
            book_id = line.split("=", 1)[1].strip()
    assert book_id
    assert main(["--db", str(db), "compile", book_id]) == 0
    mark_verified(db, book_id)
    assert main([
        "--db", str(db), "analyze", "--mode", "auto",
        "--query", "Central bank cuts reserve requirements",
        "--lenses", "economics", "politics", "law", "--render",
    ]) == 0
    output = capsys.readouterr().out
    assert "Framework cards used" in output
    assert "Draft" in output


def test_cli_direction_mode_requires_confirmation(tmp_path, capsys):
    db = tmp_path / "library.db"
    main(["--db", str(db), "init"])
    main([
        "--db", str(db), "ingest", "examples/sample_book.md",
        "--title", "Policy Shocks", "--author", "Tester",
        "--discipline", "economics", "--discipline", "politics", "--discipline", "law",
    ])
    code = main([
        "--db", str(db), "plan", "--mode", "direction",
        "--query", "bank regulation",
        "--direction", "legal regulation and statutory authority",
        "--lenses", "economics", "politics", "law",
    ])
    output = capsys.readouterr().out
    assert code == 0
    assert '"requires_confirmation": true' in output
    assert '"specified"' in output
def test_cli_text_selection_and_dashboard(tmp_path, capsys):
    db = tmp_path / "library.db"
    main(["--db", str(db), "init"])
    main([
        "--db", str(db), "ingest", "examples/sample_book.md",
        "--title", "Policy Shocks", "--author", "Tester",
        "--discipline", "economics", "--discipline", "politics", "--discipline", "law",
    ])
    ingest_out = capsys.readouterr().out
    book_id = next(line.split("=", 1)[1].strip() for line in ingest_out.splitlines() if line.startswith("book_id="))
    main(["--db", str(db), "compile", book_id])
    mark_verified(db, book_id)

    code = main([
        "--db", str(db), "plan", "--mode", "books", "--query", "bank lending regulation",
        "--books", book_id, "--lenses", "economics", "politics", "law", "--format", "text",
    ])
    output = capsys.readouterr().out
    assert code == 0
    assert "Selection card" in output
    assert "Consent gate" in output

    code = main(["--db", str(db), "dashboard"])
    dashboard = capsys.readouterr().out
    assert code == 0
    assert "BookCompiler dashboard" in dashboard
    assert "Policy Shocks" in dashboard
def test_cli_graph_shows_analysis_provenance(tmp_path, capsys):
    import json

    db = tmp_path / "library.db"
    main(["--db", str(db), "init"])
    main([
        "--db", str(db), "ingest", "examples/sample_book.md",
        "--title", "Policy Shocks", "--author", "Tester",
        "--discipline", "economics", "--discipline", "politics", "--discipline", "law",
    ])
    ingest_out = capsys.readouterr().out
    book_id = next(line.split("=", 1)[1].strip() for line in ingest_out.splitlines() if line.startswith("book_id="))
    main(["--db", str(db), "compile", book_id])
    mark_verified(db, book_id)
    capsys.readouterr()
    main([
        "--db", str(db), "analyze", "--mode", "auto",
        "--query", "Central bank cuts reserve requirements",
        "--lenses", "economics", "politics", "law",
    ])
    packet = json.loads(capsys.readouterr().out)
    analysis_id = packet["analysis_id"]

    code = main(["--db", str(db), "graph", "--node", analysis_id])
    edges = json.loads(capsys.readouterr().out)

    assert code == 0
    assert any(edge["src_type"] == "analysis" and edge["relation"] == "uses" for edge in edges)