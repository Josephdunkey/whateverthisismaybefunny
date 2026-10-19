import http.client
import json
import threading
from pathlib import Path

from tests.helpers import compile_verified
from bookcompiler.gui import make_server
from bookcompiler.parsing import parse_book
from bookcompiler.store import Store


def _server(tmp_path):
    parsed = parse_book(Path("examples/sample_book.md"), title="Policy Shocks", author="Tester", disciplines=["economics", "politics", "law"])
    store = Store(tmp_path / "library.db")
    store.add_book(parsed)
    compile_verified(store, parsed.book_id)
    store.close()
    server = make_server(tmp_path / "library.db", "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, parsed


def _request(server, method, path, body=None):
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=10)
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if payload else {}
    connection.request(method, path, body=payload, headers=headers)
    response = connection.getresponse()
    raw = response.read().decode("utf-8")
    connection.close()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = raw
    return response.status, data


def test_gui_serves_page_and_status(tmp_path):
    server, thread, parsed = _server(tmp_path)
    try:
        status, page = _request(server, "GET", "/")
        assert status == 200
        assert "BookCompiler" in page
        status, data = _request(server, "GET", "/api/status")
        assert status == 200
        assert data["coverage"]["books"] == 1
        assert data["coverage"]["frameworks"] >= 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_gui_plan_consent_and_analysis_flow(tmp_path):
    server, thread, parsed = _server(tmp_path)
    try:
        status, data = _request(
            server,
            "POST",
            "/api/plan",
            {"mode": "direction", "query": "Bank lending regulation", "lenses": ["economics", "politics", "law"], "direction": "bank credit"},
        )
        assert status == 200
        assert data["proposal"]["requires_confirmation"] is True
        assert data["proposal"]["source_recommendations"]

        status, data = _request(
            server,
            "POST",
            "/api/analyze",
            {"mode": "direction", "query": "Bank lending regulation", "lenses": ["economics", "politics", "law"], "direction": "bank credit"},
        )
        assert status == 409
        assert data["error"] == "confirmation_required"

        status, data = _request(
            server,
            "POST",
            "/api/analyze",
            {
                "mode": "auto",
                "query": "Central bank cuts reserve requirements",
                "lenses": ["economics", "politics", "law"],
            },
        )
        assert status == 200
        assert data["analysis"]["status"] == "draft"
        assert data["analysis"]["citations"]

        analysis_id = data["analysis"]["analysis_id"]
        status, data = _request(server, "GET", f"/api/analysis/{analysis_id}")
        assert status == 200
        assert data["book_titles"][parsed.book_id] == "Policy Shocks"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_gui_rejects_patch_with_fabricated_quote(tmp_path):
    server, thread, parsed = _server(tmp_path)
    try:
        status, data = _request(
            server,
            "POST",
            "/api/analyze",
            {"mode": "auto", "query": "Central bank cuts reserve requirements", "lenses": ["economics", "politics", "law"]},
        )
        assert status == 200
        analysis_id = data["analysis"]["analysis_id"]
        status, data = _request(
            server,
            "POST",
            "/api/analysis-patch",
            {
                "analysis_id": analysis_id,
                "patch": {
                    "status": "complete",
                    "conclusion": "A fabricated conclusion.",
                    "uncertainty": "Unknown.",
                    "citations": [
                        {
                            "book_id": parsed.book_id,
                            "quote": "This quote does not exist in the source.",
                            "chapter": "Fake",
                        }
                    ],
                },
            },
        )
        assert status == 400
        assert any(issue["code"] == "unsupported_quote" for issue in data["issues"])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_gui_ingest_and_feedback_endpoints(tmp_path):
    server, thread, parsed = _server(tmp_path)
    try:
        source = tmp_path / "extra.txt"
        source.write_text("中央银行通过公开市场操作改变基础货币。银行体系随后调整信贷供给。", encoding="utf-8")
        status, data = _request(
            server,
            "POST",
            "/api/ingest",
            {"path": str(source), "title": "Extra Book", "author": "Tester", "disciplines": ["economics"]},
        )
        assert status == 200
        assert data["chunks"] >= 1

        status, data = _request(
            server,
            "POST",
            "/api/analyze",
            {"mode": "auto", "query": "Reserve requirements", "lenses": ["economics", "politics", "law"]},
        )
        analysis_id = data["analysis"]["analysis_id"]
        status, data = _request(
            server,
            "POST",
            "/api/feedback",
            {"analysis_id": analysis_id, "rating": 2, "note": "Legal lens was thin.", "error_labels": ["lens_omission"]},
        )
        assert status == 200
        assert data["feedback_id"]

        status, data = _request(server, "POST", "/api/evolution/propose", {"min_support": 1})
        assert status == 200
        assert data["proposals"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_gui_rejects_invalid_mode_inputs(tmp_path):
    server, thread, parsed = _server(tmp_path)
    try:
        status, data = _request(
            server,
            "POST",
            "/api/plan",
            {"mode": "direction", "query": "bubble", "lenses": ["economics"], "direction": "  "},
        )
        assert status == 400
        assert "direction" in data["error"]

        status, data = _request(
            server,
            "POST",
            "/api/plan",
            {"mode": "books", "query": "bubble", "lenses": ["economics"], "book_ids": [], "framework_ids": []},
        )
        assert status == 400
        assert "book_id" in data["error"] or "framework_id" in data["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

def test_gui_models_endpoint_and_judge_save(tmp_path, monkeypatch):
    from bookcompiler import model_settings

    env_path = tmp_path / "models.env"
    monkeypatch.setattr(model_settings, "env_file_path", lambda: env_path)
    server, thread, parsed = _server(tmp_path)
    try:
        status, data = _request(server, "GET", "/api/models")
        assert status == 200
        assert data["judge"]["model"]
        assert data["judge"]["env_file"] == str(env_path)
        assert "hermes" in data

        status, data = _request(
            server,
            "POST",
            "/api/models/judge",
            {"provider": "ollama", "model": "qwen2.5:14b", "base_url": "http://127.0.0.1:11434"},
        )
        assert status == 200
        assert data["model"] == "qwen2.5:14b"
        assert "BOOKCOMPILER_JUDGE_MODEL=qwen2.5:14b" in env_path.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
