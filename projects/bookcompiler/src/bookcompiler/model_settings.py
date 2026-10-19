"""Model selection helpers shared by the GUI, CLI, and documentation.

BookCompiler has several unrelated "model" slots.  This module keeps them
separate instead of pretending one environment variable controls everything:

* judge       -- the LLM used for independent blind review
* embedding   -- the vector space used by retrieval (changing it requires rebuild)
* rerank      -- the optional reranker
* hermes      -- the chat agent's own config.yaml (read-only here)

The helpers only write the three BOOKCOMPILER_JUDGE_* keys.  They never read
or write API keys from the Hermes config.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .config import load_env, project_root

_VALID_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MODEL_BLOCK_KEY = re.compile(r"^\s+([A-Za-z0-9_.-]+):\s*(.*?)\s*$")


def env_file_path() -> Path:
    """Return the .env file BookCompiler will load.

    ``BOOKCOMPILER_ENV_FILE`` wins, then the project root .env.  The GUI always
    runs from the project root in the documented setup, so this is stable.
    """
    load_env()
    explicit = os.environ.get("BOOKCOMPILER_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return project_root() / ".env"


def read_env_file(path: str | Path | None = None) -> dict[str, str]:
    target = Path(path) if path else env_file_path()
    values: dict[str, str] = {}
    try:
        lines = target.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        name = name.strip()
        if name.startswith("export "):
            name = name[7:].strip()
        values[name] = value.strip().strip('"').strip("'")
    return values


def update_env_file(updates: dict[str, str], path: str | Path | None = None) -> Path:
    """Update keys in a .env file without disturbing comments or key order.

    The update is written atomically and the current process environment is
    refreshed too, so a GUI save takes effect for the next judge run without a
    restart.
    """
    target = Path(path) if path else env_file_path()
    clean: dict[str, str] = {}
    for name, value in updates.items():
        if not _VALID_ENV_NAME.match(name):
            raise ValueError(f"invalid environment variable name: {name}")
        clean[name] = " ".join(str(value).splitlines()).strip()

    try:
        existing = target.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        existing = []

    written: set[str] = set()
    output: list[str] = []
    for line in existing:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name.startswith("export "):
                name = name[7:].strip()
            if name in clean:
                output.append(f"{name}={clean[name]}")
                written.add(name)
                continue
        output.append(line)

    if output and output[-1].strip():
        output.append("")
    for name, value in clean.items():
        if name not in written:
            output.append(f"{name}={value}")

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    os.replace(temporary, target)
    for name, value in clean.items():
        os.environ[name] = value
    return target


def set_judge_default(provider: str, model: str, base_url: str = "") -> dict[str, Any]:
    """Persist the default judge route and apply it to this process immediately."""
    aliases = {
        "local": "ollama",
        "openai": "openai-compatible",
        "compatible": "openai-compatible",
        "api": "openai-compatible",
    }
    normalized = aliases.get(provider.strip().lower(), provider.strip().lower())
    if normalized not in {"ollama", "openai-compatible"}:
        raise ValueError("judge provider must be ollama or openai-compatible")
    model = model.strip()
    if not model:
        raise ValueError("judge model is required")
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        base_url = "http://127.0.0.1:11434" if normalized == "ollama" else "https://api.openai.com/v1"
    if not re.match(r"^https?://", base_url):
        raise ValueError("judge base_url must start with http:// or https://")
    path = env_file_path()
    backup = _backup_file(path, "model-switch") if path.is_file() else None
    target = update_env_file(
        {
            "BOOKCOMPILER_JUDGE_PROVIDER": normalized,
            "BOOKCOMPILER_JUDGE_MODEL": model,
            "BOOKCOMPILER_JUDGE_BASE_URL": base_url,
        },
        path,
    )
    return {
        "provider": normalized,
        "model": model,
        "base_url": base_url,
        "env_file": str(target),
        "backup": str(backup) if backup else "",
        "applied_to_current_process": True,
    }


def set_reader_default(provider: str, model: str, base_url: str = "") -> dict[str, Any]:
    """Persist the book-reading route (independent from the judge route)."""
    aliases = {
        "local": "ollama",
        "openai": "openai-compatible",
        "compatible": "openai-compatible",
        "api": "openai-compatible",
        "xiaomi": "openai-compatible",
        "mimo": "openai-compatible",
    }
    normalized = aliases.get(provider.strip().lower(), provider.strip().lower())
    if normalized not in {"ollama", "openai-compatible"}:
        raise ValueError("reader provider must be ollama or openai-compatible")
    model = model.strip()
    if not model:
        raise ValueError("reader model is required")
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        base_url = "http://127.0.0.1:11434" if normalized == "ollama" else "https://api.openai.com/v1"
    if not re.match(r"^https?://", base_url):
        raise ValueError("reader base_url must start with http:// or https://")
    path = env_file_path()
    backup = _backup_file(path, "reader-switch") if path.is_file() else None
    target = update_env_file(
        {
            "BOOKCOMPILER_READER_PROVIDER": normalized,
            "BOOKCOMPILER_READER_MODEL": model,
            "BOOKCOMPILER_READER_BASE_URL": base_url,
        },
        path,
    )
    return {
        "provider": normalized,
        "model": model,
        "base_url": base_url,
        "env_file": str(target),
        "backup": str(backup) if backup else "",
        "applied_to_current_process": True,
    }


def judge_model_status() -> dict[str, Any]:
    from .judge import default_judge_config

    load_env()
    config = default_judge_config()
    persisted = read_env_file()
    keys = ("BOOKCOMPILER_JUDGE_PROVIDER", "BOOKCOMPILER_JUDGE_MODEL", "BOOKCOMPILER_JUDGE_BASE_URL")
    return {
        "provider": config.provider,
        "model": config.model,
        "base_url": config.base_url,
        "api_key_configured": bool(config.api_key),
        "timeout_seconds": config.timeout,
        "env_file": str(env_file_path()),
        "persisted": {key: persisted.get(key, "") for key in keys},
        "source": "env_file" if any(persisted.get(key) for key in keys) else "built_in_default",
    }


def reader_model_status() -> dict[str, Any]:
    """Resolved book-reading route (not the same as the judge route).

    A ``BOOKCOMPILER_READER_*`` override wins; otherwise reading falls back to
    the judge route for backward compatibility.  The DeepSeek cost guard is
    reported explicitly so the UI/CLI never implies that paid reading is on.
    """
    from .llm_compile import _looks_like_deepseek, _reader_config

    load_env()
    persisted = read_env_file()
    reader_keys = (
        "BOOKCOMPILER_READER_PROVIDER",
        "BOOKCOMPILER_READER_MODEL",
        "BOOKCOMPILER_READER_BASE_URL",
    )
    allow = os.environ.get("BOOKCOMPILER_READER_ALLOW_DEEPSEEK", "").strip().lower() in {"1", "true", "yes", "on"}
    error = ""
    try:
        config = _reader_config()
    except Exception as exc:
        config = None
        error = str(exc)
    if config is not None:
        provider, model, base_url = config.provider, config.model, config.base_url
        key_ok = bool(config.api_key)
    else:
        base = judge_model_status()
        provider = persisted.get("BOOKCOMPILER_READER_PROVIDER", "") or base.get("provider", "")
        model = persisted.get("BOOKCOMPILER_READER_MODEL", "") or base.get("model", "")
        base_url = persisted.get("BOOKCOMPILER_READER_BASE_URL", "") or base.get("base_url", "")
        key_ok = bool(base.get("api_key_configured"))
    guarded = _looks_like_deepseek(provider, model, base_url) and not allow
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "api_key_configured": key_ok,
        "source": "reader_env" if any(persisted.get(key) for key in reader_keys) else "judge_fallback",
        "deepseek_guard_enabled": not allow,
        "deepseek_blocked": guarded,
        "allow_deepseek": allow,
        "error": error,
        "env_file": str(env_file_path()),
    }


def list_ollama_models(base_url: str = "", timeout: float = 1.5) -> dict[str, Any]:
    """List local Ollama models without making Ollama a hard dependency."""
    root = (base_url or os.environ.get("BOOKCOMPILER_JUDGE_BASE_URL", "") or "http://127.0.0.1:11434").rstrip("/")
    if root.endswith("/v1"):
        root = root[:-3].rstrip("/")
    url = f"{root}/api/tags"
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {"available": False, "base_url": root, "models": [], "error": str(exc)}
    models = []
    for item in payload.get("models", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("model") or "").strip()
        if not name:
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        models.append(
            {
                "name": name,
                "size": item.get("size"),
                "modified_at": item.get("modified_at", ""),
                "parameter_size": details.get("parameter_size", ""),
                "quantization_level": details.get("quantization_level", ""),
            }
        )
    models.sort(key=lambda item: item["name"])
    return {"available": True, "base_url": root, "models": models}


def hermes_home() -> Path:
    for key in ("BOOKCOMPILER_HERMES_HOME", "HERMES_HOME"):
        value = os.environ.get(key, "").strip()
        if value:
            return Path(value).expanduser()
    return Path(r"D:\hermes agent")


def _parse_model_block(text: str) -> dict[str, str]:
    """Read only the top-level ``model:`` mapping from config.yaml.

    This deliberately uses a small line scanner so BookCompiler does not need
    PyYAML and never has to load unrelated secrets from the config.
    """
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^model:\s*(?:#.*)?$", line):
            start = index
            break
    if start is None:
        return {}
    result: dict[str, str] = {}
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith((" ", "\t")):
            break
        match = _MODEL_BLOCK_KEY.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        value = re.sub(r"\s+#.*$", "", value).strip().strip('"').strip("'")
        result.setdefault(key, value)
    return result


def hermes_status() -> dict[str, Any]:
    home = hermes_home()
    config = home / "config.yaml"
    cli = home / "bin" / "hermes.cmd"
    payload: dict[str, Any] = {
        "home": str(home),
        "config_path": str(config),
        "config_exists": config.is_file(),
        "cli_path": str(cli),
        "cli_exists": cli.is_file(),
        "model": "",
        "provider": "",
        "base_url": "",
        "config_mtime": "",
        "note": "Hermes 对话模型由 Hermes 自己管理；BookCompiler 只读取显示，不写入。",
    }
    if config.is_file():
        try:
            text = config.read_text(encoding="utf-8", errors="replace")
            block = _parse_model_block(text)
            payload["model"] = block.get("default") or block.get("model") or ""
            payload["provider"] = block.get("provider") or ""
            payload["base_url"] = block.get("base_url") or ""
            payload["config_mtime"] = str(config.stat().st_mtime)
        except OSError as exc:
            payload["error"] = str(exc)
    return payload


def embedding_status() -> dict[str, Any]:
    load_env()
    backend = os.environ.get("BOOKCOMPILER_EMBED_BACKEND", "local").strip() or "local"
    model = os.environ.get("BOOKCOMPILER_EMBED_MODEL", "").strip()
    if not model:
        model = "local-hash-ngram-v1" if backend == "local" else "BAAI/bge-small-zh-v1.5"
    rerank_raw = os.environ.get("BOOKCOMPILER_RERANK", "0").strip().lower()
    return {
        "backend": backend,
        "model": model,
        "device": os.environ.get("BOOKCOMPILER_EMBED_DEVICE", "auto").strip() or "auto",
        "rerank_enabled": rerank_raw not in {"", "0", "false", "off", "no"},
        "rerank_model": os.environ.get("BOOKCOMPILER_RERANK_MODEL", "").strip(),
        "warning": "切换 embedding 会产生不兼容的向量空间，旧向量不能混用；必须重建后再检索。",
    }




def _backup_file(path: Path, suffix: str) -> Path:
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(path.name + f".bak-{suffix}-{stamp}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup


def hindsight_home() -> Path:
    for key in ("BOOKCOMPILER_HINDSIGHT_HOME", "HINDSIGHT_HOME"):
        value = os.environ.get(key, "").strip()
        if value:
            return Path(value).expanduser()
    return Path(r"D:\hindsight")


def hindsight_env_path() -> Path:
    return hindsight_home() / ".env"


def hindsight_model_status() -> dict[str, Any]:
    path = hindsight_env_path()
    values = read_env_file(path)
    return {
        "home": str(hindsight_home()),
        "env_file": str(path),
        "env_exists": path.is_file(),
        "provider": values.get("HINDSIGHT_API_LLM_PROVIDER", "ollama"),
        "model": values.get("HINDSIGHT_API_LLM_MODEL", ""),
        "base_url": values.get("HINDSIGHT_API_LLM_BASE_URL", ""),
        "api_port": values.get("HINDSIGHT_API_PORT", "8888"),
        "restart_required": True,
    }


def set_hindsight_default(provider: str, model: str, base_url: str = "") -> dict[str, Any]:
    path = hindsight_env_path()
    provider = provider.strip().lower() or "ollama"
    model = model.strip()
    if not model:
        raise ValueError("hindsight model is required")
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        base_url = "http://127.0.0.1:11434/v1" if provider == "ollama" else "https://api.openai.com/v1"
    if not re.match(r"^https?://", base_url):
        raise ValueError("hindsight base_url must start with http:// or https://")
    backup = _backup_file(path, "model-switch") if path.is_file() else None
    update_env_file(
        {
            "HINDSIGHT_API_LLM_PROVIDER": provider,
            "HINDSIGHT_API_LLM_MODEL": model,
            "HINDSIGHT_API_LLM_BASE_URL": base_url,
        },
        path,
    )
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "env_file": str(path),
        "backup": str(backup) if backup else "",
        "restart_required": True,
    }


def hermes_config_path() -> Path:
    return hermes_home() / "config.yaml"


def _yaml_value(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _update_model_block(lines: list[str], updates: dict[str, str]) -> list[str]:
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^model:\s*(?:#.*)?$", line):
            start = index
            break
    if start is None:
        raise ValueError("top-level model: block not found")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip() and not lines[index].startswith((" ", "\t")):
            end = index
            break
    block = list(lines[start + 1 : end])
    seen: set[str] = set()
    for index, line in enumerate(block):
        match = re.match(r"^(\s+)([A-Za-z0-9_.-]+):\s*(.*?)\s*$", line)
        if not match:
            continue
        key = match.group(2)
        if key not in updates:
            continue
        indent, raw = match.group(1), match.group(3)
        comment = ""
        if " #" in raw:
            _, comment = raw.split(" #", 1)
            comment = "  #" + comment
        block[index] = f"{indent}{key}: {_yaml_value(updates[key])}{comment}"
        seen.add(key)
    insert_at = len(block)
    while insert_at > 0 and not block[insert_at - 1].strip():
        insert_at -= 1
    for key, value in updates.items():
        if key not in seen:
            block.insert(insert_at, f"  {key}: {_yaml_value(value)}")
            insert_at += 1
    return lines[: start + 1] + block + lines[end:]


def set_hermes_default(model: str, provider: str, base_url: str = "") -> dict[str, Any]:
    model = model.strip()
    provider = provider.strip()
    if not model:
        raise ValueError("hermes model is required")
    if not provider:
        raise ValueError("hermes provider is required")
    path = hermes_config_path()
    if not path.is_file():
        raise FileNotFoundError(f"hermes config not found: {path}")
    original = path.read_text(encoding="utf-8", errors="replace")
    newline = "\r\n" if "\r\n" in original else "\n"
    lines = original.splitlines()
    updates = {"default": model, "provider": provider}
    if base_url.strip():
        updates["base_url"] = base_url.strip().rstrip("/")
    lines = _update_model_block(lines, updates)
    backup = _backup_file(path, "model-switch")
    path.write_text(newline.join(lines) + newline, encoding="utf-8", newline="")
    return {
        "model": model,
        "provider": provider,
        "base_url": updates.get("base_url", ""),
        "config_path": str(path),
        "backup": str(backup),
        "restart_required": True,
    }

def model_overview() -> dict[str, Any]:
    load_env()
    judge = judge_model_status()
    return {
        "judge": judge,
        "reader": reader_model_status(),
        "ollama": list_ollama_models(os.environ.get("BOOKCOMPILER_OLLAMA_BASE_URL", "http://127.0.0.1:11434")),
        "hermes": hermes_status(),
        "embedding": embedding_status(),
        "hindsight": hindsight_model_status(),
        "notes": [
            "系统环境变量只对新进程生效；已打开的 GUI、终端、Hermes 需要重启。",
            "BookCompiler 的 .env 比系统变量更适合作为默认值。",
            "单次运行参数（GUI 输入框 / CLI --model）优先级最高。",
            "Hermes 的对话模型在 Hermes 的 config.yaml 中，不在 BookCompiler 的 .env 中。",
        ],
    }