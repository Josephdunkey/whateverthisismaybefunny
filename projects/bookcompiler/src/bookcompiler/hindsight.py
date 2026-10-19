"""Optional Hindsight long-term memory bridge for BookCompiler.

BookCompiler keeps book evidence in local SQLite.  Hindsight is used for the
small, durable things that are not in books: user corrections, preferences,
feedback outcomes, and lessons learned across analyses.

Design rules
------------
* Never block the main workflow.  Every call returns an ``ok`` flag instead of
  raising when Hindsight is down.
* Never send API keys or absolute secrets in the payload.
* Disable with ``HINDSIGHT_ENABLED=0`` or an empty ``HINDSIGHT_BASE_URL``.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .config import load_env

DEFAULT_BASE_URL = "http://127.0.0.1:8888"
DEFAULT_BANK_ID = "bookcompiler"
DEFAULT_TIMEOUT = 20.0
DEFAULT_MISSION = (
    "Durable lessons from BookCompiler: user corrections, citation preferences, "
    "error patterns, workflow choices, and outcomes. Book text and exact quotes "
    "remain in the local BookCompiler library; this bank stores reusable lessons."
)
_BANK_READY: set[str] = set()


def _setting(name: str, default: str = "") -> str:
    load_env()
    return os.environ.get(name, default).strip()


def enabled() -> bool:
    if _setting("HINDSIGHT_ENABLED", "1").lower() in {"0", "false", "no", "off"}:
        return False
    return bool(base_url())


def base_url() -> str:
    return _setting("HINDSIGHT_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def bank_id() -> str:
    return _setting("HINDSIGHT_BANK_ID", DEFAULT_BANK_ID) or DEFAULT_BANK_ID


def timeout() -> float:
    try:
        return float(_setting("HINDSIGHT_TIMEOUT", str(DEFAULT_TIMEOUT)))
    except ValueError:
        return DEFAULT_TIMEOUT


def _request(
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout_seconds: float | None = None,
) -> dict[str, Any]:
    if not enabled():
        return {"ok": False, "enabled": False, "error": "Hindsight is disabled"}
    url = base_url() + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds or timeout()) as response:
            raw = response.read().decode("utf-8", "replace")
            body = json.loads(raw) if raw.strip() else {}
            return {"ok": True, "enabled": True, "status": response.status, "body": body}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        return {"ok": False, "enabled": True, "status": exc.code, "error": detail or str(exc)}
    except Exception as exc:  # network, timeout, JSON, DNS ...
        return {"ok": False, "enabled": True, "error": f"{type(exc).__name__}: {exc}"}


def status() -> dict[str, Any]:
    """Cheap health + bank check used by CLI, GUI, MCP and the tutorial."""
    if not enabled():
        return {"enabled": False, "reachable": False, "base_url": base_url(), "bank_id": bank_id()}
    health = _request("GET", "/health", timeout_seconds=min(timeout(), 8.0))
    bank = (
        _request("GET", f"/v1/default/banks?q={bank_id()}&limit=20", timeout_seconds=min(timeout(), 8.0))
        if health.get("ok")
        else {}
    )
    bank_body = bank.get("body") or {}
    bank_items = bank_body.get("banks") or bank_body.get("items") or []
    exists = any(str(item.get("bank_id") or item.get("id") or "") == bank_id() for item in bank_items)
    return {
        "enabled": True,
        "reachable": bool(health.get("ok")),
        "base_url": base_url(),
        "bank_id": bank_id(),
        "health": health.get("body") if health.get("ok") else health.get("error"),
        "bank_exists": exists,
        "bank": bank_body if bank.get("ok") else bank.get("error"),
    }


def ensure_bank(mission: str = DEFAULT_MISSION) -> dict[str, Any]:
    result = _request(
        "PUT",
        f"/v1/default/banks/{bank_id()}",
        {"reflect_mission": mission, "enable_observations": False},
    )
    if result.get("ok"):
        _BANK_READY.add(bank_id())
    return result


def _ready() -> None:
    if bank_id() not in _BANK_READY:
        ensure_bank()


def retain(
    content: str,
    *,
    context: str = "BookCompiler",
    document_id: str = "",
    tags: list[str] | None = None,
    metadata: dict[str, str] | None = None,
    asynchronous: bool = True,
) -> dict[str, Any]:
    """Store one durable lesson.  Default async: extraction happens in background."""
    if not content.strip():
        return {"ok": False, "enabled": enabled(), "error": "empty content"}
    _ready()
    item: dict[str, Any] = {
        "content": content,
        "context": context,
        "tags": tags or [],
        "metadata": {k: str(v) for k, v in (metadata or {}).items()},
    }
    if document_id:
        item["document_id"] = document_id
    result = _request(
        "POST",
        f"/v1/default/banks/{bank_id()}/memories",
        {"items": [item], "async": bool(asynchronous)},
        timeout_seconds=max(timeout(), float(_setting("HINDSIGHT_RETAIN_TIMEOUT", "180"))),
    )
    if result.get("ok"):
        body = result.get("body") or {}
        result["operation_id"] = body.get("operation_id")
    return result


def recall(
    query: str,
    *,
    limit: int = 8,
    budget: str = "low",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    _ready()
    payload: dict[str, Any] = {"query": query, "budget": budget, "max_tokens": 1600}
    if tags:
        payload["tags"] = tags
    result = _request("POST", f"/v1/default/banks/{bank_id()}/memories/recall", payload)
    if not result.get("ok"):
        return result
    body = result.get("body") or {}
    results = list(body.get("results") or [])[: max(1, limit)]
    return {"ok": True, "enabled": True, "results": results, "raw": body}


def reflect(query: str, *, budget: str = "low", max_tokens: int = 800) -> dict[str, Any]:
    result = _request(
        "POST",
        f"/v1/default/banks/{bank_id()}/reflect",
        {"query": query, "budget": budget, "max_tokens": max_tokens},
        timeout_seconds=max(timeout(), float(_setting("HINDSIGHT_REFLECT_TIMEOUT", "300"))),
    )
    if not result.get("ok"):
        return result
    body = result.get("body") or {}
    return {"ok": True, "enabled": True, "text": body.get("text", ""), "raw": body}


def merged_lessons(query: str, limit: int = 8, *, budget: str = "low") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return Hindsight results normalised into BookCompiler lesson shape."""
    result = recall(query, limit=limit, budget=budget)
    lessons: list[dict[str, Any]] = []
    for item in result.get("results", []):
        lessons.append(
            {
                "source": "hindsight",
                "text": item.get("text", ""),
                "type": item.get("type"),
                "document_id": item.get("document_id"),
                "tags": item.get("tags", []),
                "entities": item.get("entities", []),
                "relevance": (item.get("scores") or {}).get("final"),
                "hindsight_id": item.get("id"),
            }
        )
    return lessons, result

def list_memories(
    *,
    limit: int = 200,
    offset: int = 0,
    query: str = "",
    fact_type: str = "",
    state: str = "",
) -> dict[str, Any]:
    """List memory units for the Obsidian mirror.

    Returns ``ok=False`` instead of raising when Hindsight is disabled or down.
    """
    from urllib.parse import urlencode

    params: dict[str, str] = {"limit": str(max(1, min(int(limit), 1000))), "offset": str(max(0, int(offset)))}
    if query:
        params["q"] = query
    if fact_type:
        params["type"] = fact_type
    if state:
        params["state"] = state
    path = f"/v1/default/banks/{bank_id()}/memories/list?{urlencode(params)}"
    result = _request("GET", path)
    if not result.get("ok"):
        return result
    body = result.get("body") or {}
    items = body.get("items") or body.get("memories") or []
    return {
        "ok": True,
        "enabled": True,
        "items": items,
        "total": body.get("total", len(items)),
        "limit": body.get("limit", limit),
        "offset": body.get("offset", offset),
    }


def update_memory(
    memory_id: str,
    *,
    text: str | None = None,
    context: str | None = None,
    state: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Edit or invalidate one memory unit.

    Hindsight rejects edits to observations; callers should check ``fact_type``
    first and treat those notes as read-only.
    """
    if not memory_id.strip():
        return {"ok": False, "enabled": enabled(), "error": "empty memory_id"}
    payload: dict[str, Any] = {}
    if text is not None:
        payload["text"] = text
    if context is not None:
        payload["context"] = context
    if state is not None:
        payload["state"] = state
    if reason:
        payload["reason"] = reason
    if not payload:
        return {"ok": False, "enabled": enabled(), "error": "nothing to update"}
    return _request("PATCH", f"/v1/default/banks/{bank_id()}/memories/{memory_id}", payload)

