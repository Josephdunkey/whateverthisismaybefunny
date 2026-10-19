"""Knowledge Hub dashboard plugin backend.

Mounted by Hermes at /api/plugins/knowledge-hub/.

The plugin is deliberately a thin control plane: it proxies the local
BookCompiler GUI, the Hindsight API, Obsidian status/sync endpoints, and the
existing model-switch helper.  No service state is duplicated here.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query
from pydantic import BaseModel, Field


router = APIRouter()


def _path_env(name: str, default: str) -> Path:
    value = os.environ.get(name, default)
    return Path(value).expanduser()


HERMES_HOME = _path_env("HERMES_HOME", r"D:\hermes agent")
KNOWLEDGE_HOME = _path_env("KNOWLEDGE_HUB_HOME", r"D:\knowledge-hub")
BOOKCOMPILER_HOME = _path_env("BOOKCOMPILER_HOME", r"C:\Users\mybea\projects\bookcompiler")
HINDSIGHT_HOME = _path_env("HINDSIGHT_HOME", r"D:\hindsight")
OBSIDIAN_VAULT = _path_env("OBSIDIAN_VAULT", r"C:\Users\mybea\Documents\Obsidian Vault")

BOOKCOMPILER_URL = os.environ.get("BOOKCOMPILER_URL", "http://127.0.0.1:8765").rstrip("/")
HINDSIGHT_URL = os.environ.get("HINDSIGHT_URL", "http://127.0.0.1:8888").rstrip("/")
BOOKCOMPILER_PY = BOOKCOMPILER_HOME / ".venv" / "Scripts" / "python.exe"
HINDSIGHT_PY = HINDSIGHT_HOME / ".venv" / "Scripts" / "python.exe"
HERMES_CLI = HERMES_HOME / "bin" / "hermes.cmd"
RUNTIME_DIR = KNOWLEDGE_HOME / ".runtime"
LOG_DIR = KNOWLEDGE_HOME / "logs"
PID_FILE = RUNTIME_DIR / "pids.json"

_BANK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
_CREATE_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0


class UpstreamError(RuntimeError):
    def __init__(self, service: str, status: int, detail: str):
        self.service = service
        self.status = status
        self.detail = detail
        super().__init__(f"{service}: {detail}")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _json_request(
    url: str,
    method: str = "GET",
    payload: Optional[Any] = None,
    timeout: float = 20.0,
) -> Any:
    body = None
    headers = {"Accept": "application/json", "User-Agent": "Hermes-KnowledgeHub/0.1"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            text = raw.decode("utf-8", "replace")
            if not text.strip():
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"ok": True, "raw": text}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        detail: Any = raw.strip()[:3000]
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                detail = parsed.get("detail") or parsed.get("error") or parsed.get("message") or detail
        except Exception:
            pass
        raise UpstreamError(url, exc.code, str(detail)) from exc
    except Exception as exc:
        raise UpstreamError(url, 0, f"{type(exc).__name__}: {exc}") from exc


def _safe(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Dict[str, Any]:
    try:
        result = fn(*args, **kwargs)
        if isinstance(result, dict):
            return result
        return {"ok": True, "data": result}
    except UpstreamError as exc:
        return {"ok": False, "error": exc.detail, "status": exc.status, "service": exc.service}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _proxy(url: str, *, method: str = "GET", payload: Optional[Any] = None, timeout: float = 30.0) -> Any:
    try:
        return _json_request(url, method=method, payload=payload, timeout=timeout)
    except UpstreamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _validate_bank(bank: str) -> str:
    if not bank or not _BANK_RE.match(bank):
        raise HTTPException(status_code=400, detail="invalid bank id")
    return bank


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_port(port: int, seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.4)
    return _port_open(port)


def _services() -> List[Dict[str, Any]]:
    return [
        {
            "id": "hermes",
            "label": "Hermes Agent",
            "port": 9119,
            "kind": "dashboard",
            "running": _port_open(9119),
            "url": "http://127.0.0.1:9119",
            "detail": "统一宿主 / Chat / Skills / MCP / Models",
        },
        {
            "id": "bookcompiler",
            "label": "BookCompiler",
            "port": 8765,
            "kind": "http",
            "running": _port_open(8765),
            "url": BOOKCOMPILER_URL,
            "detail": "书籍入库、编译、检索、GraphRAG、九维评分",
        },
        {
            "id": "hindsight",
            "label": "Hindsight",
            "port": 8888,
            "kind": "http",
            "running": _port_open(8888),
            "url": HINDSIGHT_URL,
            "detail": "长期记忆：偏好、经验、反馈、跨会话教训",
        },
        {
            "id": "ollama",
            "label": "Ollama",
            "port": 11434,
            "kind": "http",
            "running": _port_open(11434),
            "url": "http://127.0.0.1:11434",
            "detail": "本地模型 / 本地记忆抽取",
        },
        {
            "id": "postgres",
            "label": "Hindsight DB",
            "port": 5432,
            "kind": "pg",
            "running": _port_open(5432),
            "url": "",
            "detail": "pg0 / PostgreSQL 记忆数据库",
        },
    ]


def _count_md(root: Path) -> int:
    if not root.exists():
        return 0
    try:
        return sum(1 for item in root.rglob("*.md") if item.is_file())
    except OSError:
        return 0


def _recent_notes(root: Path, vault: Path, limit: int = 12) -> List[Dict[str, Any]]:
    if not root.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        files = [item for item in root.rglob("*.md") if item.is_file()]
        files.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        for item in files[: max(1, min(limit, 50))]:
            try:
                rel = item.relative_to(vault).as_posix()
            except ValueError:
                rel = item.as_posix()
            rows.append(
                {
                    "name": item.name,
                    "path": str(item),
                    "relative_path": rel,
                    "modified_at": datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    except OSError:
        return rows
    return rows


def _obsidian_snapshot() -> Dict[str, Any]:
    book_root = OBSIDIAN_VAULT / "BookCompiler"
    hs_root = OBSIDIAN_VAULT / "Hindsight"
    return {
        "ok": OBSIDIAN_VAULT.exists(),
        "vault": str(OBSIDIAN_VAULT),
        "vault_exists": OBSIDIAN_VAULT.exists(),
        "bookcompiler_root": str(book_root),
        "hindsight_root": str(hs_root),
        "bookcompiler_notes": _count_md(book_root),
        "hindsight_notes": _count_md(hs_root),
        "recent_bookcompiler": _recent_notes(book_root, OBSIDIAN_VAULT, 10),
        "recent_hindsight": _recent_notes(hs_root, OBSIDIAN_VAULT, 10),
    }


def _snapshot() -> Dict[str, Any]:
    book_status = _safe(_json_request, f"{BOOKCOMPILER_URL}/api/status", timeout=8)
    models = _safe(_json_request, f"{BOOKCOMPILER_URL}/api/models", timeout=10)
    hs_health = _safe(_json_request, f"{HINDSIGHT_URL}/health", timeout=6)
    hs_banks = _safe(_json_request, f"{HINDSIGHT_URL}/v1/default/banks", timeout=8)
    hs_stats = _safe(_json_request, f"{HINDSIGHT_URL}/v1/default/banks/bookcompiler/stats", timeout=8)
    obs_book = _safe(_json_request, f"{BOOKCOMPILER_URL}/api/obsidian/status", timeout=10)
    obs_hs = _safe(_json_request, f"{BOOKCOMPILER_URL}/api/obsidian/hindsight/status", timeout=10)
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "services": _services(),
        "bookcompiler": book_status,
        "models": models,
        "hindsight": {
            "health": hs_health,
            "banks": hs_banks,
            "stats_bookcompiler": hs_stats,
        },
        "obsidian": {
            "snapshot": _obsidian_snapshot(),
            "bookcompiler": obs_book,
            "hindsight": obs_hs,
        },
        "paths": {
            "knowledge_home": str(KNOWLEDGE_HOME),
            "bookcompiler_home": str(BOOKCOMPILER_HOME),
            "bookcompiler_db": str(BOOKCOMPILER_HOME / ".bookcompiler" / "library.db"),
            "bookcompiler_graph_db": str(BOOKCOMPILER_HOME / ".bookcompiler" / "library.graph.db"),
            "hindsight_home": str(HINDSIGHT_HOME),
            "hermes_home": str(HERMES_HOME),
            "obsidian_vault": str(OBSIDIAN_VAULT),
            "plugin_dir": str(Path(__file__).resolve().parent),
        },
    }


def _trim_framework(item: Dict[str, Any]) -> Dict[str, Any]:
    keys = (
        "framework_id", "book_id", "book_title", "name", "one_liner",
        "lenses", "applicable_when", "status", "confidence",
    )
    return {key: item.get(key) for key in keys if key in item}


def _record_pid(service: str, pid: int) -> None:
    data = _read_json(PID_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data[service] = {"pid": int(pid), "started_at": datetime.now(timezone.utc).isoformat()}
    _write_json(PID_FILE, data)


def _popen_logged(name: str, command: List[str], cwd: Path) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out_path = LOG_DIR / f"{name}.out.log"
    err_path = LOG_DIR / f"{name}.err.log"
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    flags = _CREATE_NO_WINDOW | _CREATE_NEW_GROUP
    with open(out_path, "ab") as out, open(err_path, "ab") as err:
        return subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            creationflags=flags,
        )


def _start_service(service: str) -> Dict[str, Any]:
    service = (service or "").strip().lower()
    if service in {"bookcompiler", "bc"}:
        if _port_open(8765):
            return {"ok": True, "service": "bookcompiler", "already_running": True}
        if not BOOKCOMPILER_PY.is_file():
            raise HTTPException(status_code=500, detail=f"BookCompiler Python not found: {BOOKCOMPILER_PY}")
        proc = _popen_logged(
            "bookcompiler",
            [
                str(BOOKCOMPILER_PY), "-m", "bookcompiler",
                "--db", str(BOOKCOMPILER_HOME / ".bookcompiler" / "library.db"),
                "gui", "--host", "127.0.0.1", "--port", "8765",
            ],
            BOOKCOMPILER_HOME,
        )
        _record_pid("bookcompiler", proc.pid)
        return {"ok": _wait_port(8765, 25), "service": "bookcompiler", "pid": proc.pid}

    if service == "hindsight":
        if _port_open(8888):
            return {"ok": True, "service": "hindsight", "already_running": True}
        if not HINDSIGHT_PY.is_file():
            raise HTTPException(status_code=500, detail=f"Hindsight Python not found: {HINDSIGHT_PY}")
        if not _port_open(5432):
            pg = subprocess.run(
                [str(HINDSIGHT_PY), "-c", "import pg0; pg0.start('hindsight')"],
                cwd=str(HINDSIGHT_HOME),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                creationflags=_CREATE_NO_WINDOW,
            )
            if pg.returncode != 0:
                raise HTTPException(status_code=500, detail=(pg.stderr or pg.stdout or "pg0 start failed")[-2000:])
            _wait_port(5432, 25)
        proc = _popen_logged("hindsight", [str(HINDSIGHT_PY), str(HINDSIGHT_HOME / "run_server.py")], HINDSIGHT_HOME)
        _record_pid("hindsight", proc.pid)
        return {"ok": _wait_port(8888, 45), "service": "hindsight", "pid": proc.pid}

    if service == "ollama":
        if _port_open(11434):
            return {"ok": True, "service": "ollama", "already_running": True}
        candidates = [
            shutil.which("ollama"),
            str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"),
        ]
        exe = next((item for item in candidates if item and Path(item).is_file()), None)
        if not exe:
            raise HTTPException(status_code=500, detail="ollama executable not found")
        proc = _popen_logged("ollama", [exe, "serve"], Path(exe).resolve().parent)
        _record_pid("ollama", proc.pid)
        return {"ok": _wait_port(11434, 25), "service": "ollama", "pid": proc.pid}

    if service in {"hermes", "dashboard", "hermes-dashboard"}:
        if _port_open(9119):
            return {"ok": True, "service": "hermes-dashboard", "already_running": True}
        if not HERMES_CLI.is_file():
            raise HTTPException(status_code=500, detail=f"Hermes CLI not found: {HERMES_CLI}")
        proc = _popen_logged(
            "hermes-dashboard",
            ["cmd.exe", "/c", str(HERMES_CLI), "dashboard", "--skip-build", "--no-open"],
            HERMES_HOME,
        )
        _record_pid("hermes-dashboard", proc.pid)
        return {"ok": _wait_port(9119, 35), "service": "hermes-dashboard", "pid": proc.pid}

    raise HTTPException(status_code=400, detail="unknown service")


def _open_path(target: str) -> Dict[str, Any]:
    allowed = {
        "vault": OBSIDIAN_VAULT,
        "bookcompiler": BOOKCOMPILER_HOME,
        "bookcompiler-data": BOOKCOMPILER_HOME / ".bookcompiler",
        "hindsight": HINDSIGHT_HOME,
        "hermes": HERMES_HOME,
        "knowledge-hub": KNOWLEDGE_HOME,
        "logs": LOG_DIR,
    }
    path = allowed.get((target or "").strip().lower())
    if path is None:
        raise HTTPException(status_code=400, detail="path target not allowed")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"path does not exist: {path}")
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
    return {"ok": True, "target": target, "path": str(path)}


class RecallBody(BaseModel):
    bank: str = Field(default="bookcompiler")
    query: str = Field(min_length=1)
    budget: str = Field(default="mid")
    max_tokens: int = Field(default=4096, ge=256, le=32768)


class ReflectBody(BaseModel):
    bank: str = Field(default="bookcompiler")
    query: str = Field(min_length=1)
    budget: str = Field(default="low")
    max_tokens: int = Field(default=4096, ge=256, le=32768)


class RetainBody(BaseModel):
    bank: str = Field(default="bookcompiler")
    text: str = Field(min_length=1)
    context: str = ""
    tags: List[str] = Field(default_factory=list)


class PresetBody(BaseModel):
    name: str


class SwitchModelBody(BaseModel):
    target: str
    provider: str
    model: str
    base_url: str = ""


class SyncBody(BaseModel):
    vault: str = ""


class StartBody(BaseModel):
    service: str


class OpenPathBody(BaseModel):
    target: str


@router.get("/ping")
def ping() -> Dict[str, Any]:
    return {"ok": True, "plugin": "knowledge-hub", "service": "hermes-dashboard"}


@router.get("/overview")
def overview() -> Dict[str, Any]:
    return _snapshot()


@router.get("/books")
def books() -> Dict[str, Any]:
    book_payload = _proxy(f"{BOOKCOMPILER_URL}/api/books", timeout=30)
    framework_payload = _proxy(f"{BOOKCOMPILER_URL}/api/frameworks", timeout=30)
    frameworks = framework_payload.get("frameworks", []) if isinstance(framework_payload, dict) else []
    analyses: Dict[str, Any] = {"analyses": []}
    try:
        analyses = _json_request(f"{BOOKCOMPILER_URL}/api/analyses", timeout=20)
    except Exception:
        pass
    return {
        "ok": True,
        "books": book_payload.get("books", []) if isinstance(book_payload, dict) else [],
        "frameworks": [_trim_framework(item) for item in frameworks if isinstance(item, dict)],
        "analyses": analyses.get("analyses", []) if isinstance(analyses, dict) else [],
    }


@router.get("/analyses")
def analyses() -> Any:
    return _proxy(f"{BOOKCOMPILER_URL}/api/analyses", timeout=25)


@router.get("/retrieval")
def retrieval(q: str = Query(..., min_length=1), limit: int = Query(8, ge=1, le=30)) -> Any:
    url = f"{BOOKCOMPILER_URL}/api/retrieval?query={urllib.parse.quote(q)}&limit={int(limit)}"
    return _proxy(url, timeout=60)


@router.post("/plan")
def plan(payload: Dict[str, Any] = Body(...)) -> Any:
    return _proxy(f"{BOOKCOMPILER_URL}/api/plan", method="POST", payload=payload, timeout=60)


@router.post("/analyze")
def analyze(payload: Dict[str, Any] = Body(...)) -> Any:
    return _proxy(f"{BOOKCOMPILER_URL}/api/analyze", method="POST", payload=payload, timeout=300)


@router.get("/hindsight/banks")
def hindsight_banks() -> Any:
    return _proxy(f"{HINDSIGHT_URL}/v1/default/banks", timeout=20)


@router.get("/hindsight/stats")
def hindsight_stats(bank: str = Query("bookcompiler")) -> Any:
    bank = _validate_bank(bank)
    return _proxy(f"{HINDSIGHT_URL}/v1/default/banks/{bank}/stats", timeout=20)


@router.get("/hindsight/memories")
def hindsight_memories(
    bank: str = Query("bookcompiler"),
    q: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Any:
    bank = _validate_bank(bank)
    params = {"limit": int(limit), "offset": int(offset)}
    if q.strip():
        params["q"] = q.strip()
    url = f"{HINDSIGHT_URL}/v1/default/banks/{bank}/memories/list?{urllib.parse.urlencode(params)}"
    return _proxy(url, timeout=30)


@router.post("/hindsight/recall")
def hindsight_recall(body: RecallBody) -> Any:
    bank = _validate_bank(body.bank)
    payload = {
        "query": body.query,
        "budget": body.budget,
        "max_tokens": body.max_tokens,
    }
    return _proxy(f"{HINDSIGHT_URL}/v1/default/banks/{bank}/memories/recall", method="POST", payload=payload, timeout=180)


@router.post("/hindsight/reflect")
def hindsight_reflect(body: ReflectBody) -> Any:
    bank = _validate_bank(body.bank)
    payload = {
        "query": body.query,
        "budget": body.budget,
        "max_tokens": body.max_tokens,
    }
    return _proxy(f"{HINDSIGHT_URL}/v1/default/banks/{bank}/reflect", method="POST", payload=payload, timeout=300)


@router.post("/hindsight/retain")
def hindsight_retain(body: RetainBody) -> Any:
    bank = _validate_bank(body.bank)
    item: Dict[str, Any] = {"content": body.text}
    if body.context.strip():
        item["context"] = body.context.strip()
    if body.tags:
        item["tags"] = body.tags
    payload = {"items": [item], "async": False}
    return _proxy(f"{HINDSIGHT_URL}/v1/default/banks/{bank}/memories", method="POST", payload=payload, timeout=300)


@router.get("/obsidian/status")
def obsidian_status() -> Dict[str, Any]:
    book_status = _safe(_json_request, f"{BOOKCOMPILER_URL}/api/obsidian/status", timeout=15)
    hs_status = _safe(_json_request, f"{BOOKCOMPILER_URL}/api/obsidian/hindsight/status", timeout=15)
    return {
        "ok": True,
        "snapshot": _obsidian_snapshot(),
        "bookcompiler": book_status,
        "hindsight": hs_status,
    }


def _resolve_vault(raw: str) -> str:
    """Only allow the configured Obsidian vault, never an arbitrary path."""
    configured = OBSIDIAN_VAULT.expanduser().resolve()
    if not raw.strip():
        return str(configured)
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = configured / candidate
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"invalid vault path: {exc}") from exc
    if resolved != configured:
        raise HTTPException(status_code=400, detail="vault must equal the configured Obsidian vault")
    return str(resolved)


@router.post("/obsidian/sync-all")
def obsidian_sync_all(body: SyncBody = Body(default=SyncBody())) -> Any:
    payload = {"vault": _resolve_vault(body.vault), "direction": "both"}
    return _proxy(f"{BOOKCOMPILER_URL}/api/obsidian/sync-all", method="POST", payload=payload, timeout=300)


@router.get("/models")
def models() -> Any:
    return _proxy(f"{BOOKCOMPILER_URL}/api/models", timeout=20)


@router.post("/models/preset")
def models_preset(body: PresetBody) -> Any:
    return _proxy(f"{BOOKCOMPILER_URL}/api/models/preset", method="POST", payload={"name": body.name}, timeout=90)


@router.post("/models/switch")
def models_switch(body: SwitchModelBody) -> Dict[str, Any]:
    target = (body.target or "").strip().lower()
    allowed = {"reader", "bookcompiler", "judge", "hindsight", "hermes"}
    if target not in allowed:
        raise HTTPException(status_code=400, detail="target must be reader/bookcompiler/judge/hindsight/hermes")
    provider = (body.provider or "").strip()
    model = (body.model or "").strip()
    base_url = (body.base_url or "").strip()
    if not provider or not model:
        raise HTTPException(status_code=400, detail="provider and model are required")
    if not re.match(r"^[A-Za-z0-9_.:/+-]+$", provider):
        raise HTTPException(status_code=400, detail="invalid provider")
    if base_url and not re.match(r"^https?://", base_url):
        raise HTTPException(status_code=400, detail="base_url must start with http:// or https://")
    if not BOOKCOMPILER_PY.is_file():
        raise HTTPException(status_code=500, detail=f"BookCompiler Python not found: {BOOKCOMPILER_PY}")
    command = [
        str(BOOKCOMPILER_PY), "-m", "bookcompiler.switch_models", "set",
        "--target", target, "--provider", provider, "--model", model,
    ]
    if base_url:
        command.extend(["--base-url", base_url])
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(BOOKCOMPILER_HOME / "src") + os.pathsep + env.get("PYTHONPATH", "")
    try:
        done = subprocess.run(
            command,
            cwd=str(BOOKCOMPILER_HOME),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env=env,
            creationflags=_CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="model switch timed out") from exc
    output = "\n".join(part.strip() for part in (done.stdout, done.stderr) if part and part.strip())
    return {
        "ok": done.returncode == 0,
        "target": target,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "exit_code": done.returncode,
        "output": output[-6000:],
        "restart_required": target in {"hindsight", "hermes"},
        "overview": _safe(_json_request, f"{BOOKCOMPILER_URL}/api/models", timeout=15),
    }


@router.post("/actions/start")
def actions_start(body: StartBody) -> Dict[str, Any]:
    return _start_service(body.service)


@router.post("/actions/open-path")
def actions_open_path(body: OpenPathBody) -> Dict[str, Any]:
    return _open_path(body.target)


@router.get("/actions/pids")
def actions_pids() -> Dict[str, Any]:
    data = _read_json(PID_FILE, {})
    if not isinstance(data, dict):
        data = {}
    return {"ok": True, "pids": data}


@router.get("/logs")
def logs(name: str = Query("hindsight"), lines: int = Query(200, ge=20, le=2000)) -> Dict[str, Any]:
    allowed = {
        "hindsight": LOG_DIR / "hindsight.out.log",
        "hindsight-error": LOG_DIR / "hindsight.err.log",
        "bookcompiler": LOG_DIR / "bookcompiler.out.log",
        "bookcompiler-error": LOG_DIR / "bookcompiler.err.log",
        "ollama": LOG_DIR / "ollama.out.log",
        "hermes-dashboard": LOG_DIR / "hermes-dashboard.out.log",
    }
    path = allowed.get((name or "").strip().lower())
    if path is None:
        raise HTTPException(status_code=400, detail="unknown log")
    if not path.exists():
        return {"ok": True, "name": name, "path": str(path), "text": ""}
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "name": name, "path": str(path), "text": "\n".join(content[-lines:])}