"""Small environment loader and shared runtime paths.

BookCompiler deliberately has no python-dotenv dependency.  A `.env` file in the
working directory (or the path in BOOKCOMPILER_ENV_FILE) is read once, and real
process environment variables always win.
"""
from __future__ import annotations

import os
from pathlib import Path

_LOADED = False

# Environment variables commonly used by the three local products.  Windows
# keeps User-level variables in the registry; a process started by an older
# terminal does not inherit variables added after that terminal was opened.
# Reading only these names keeps the compatibility fallback narrow and avoids
# copying unrelated secrets into the process.
_WINDOWS_USER_ENV_KEYS = (
    "MIMO_API_KEY",
    "MIMO_BASE_URL",
    "MIMO_MODEL",
    "XIAOMI_API_KEY",
    "XIAOMI_BASE_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "DASHSCOPE_API_KEY",
    "ANTHROPIC_API_KEY",
)


def _load_windows_user_env() -> None:
    """Fill missing known variables from the current Windows User environment.

    This is a compatibility path for long-lived terminals and GUI launchers.
    Existing process variables always win.  Failures are intentionally silent:
    the regular .env loader and explicit environment variables remain usable on
    non-Windows systems and in restricted environments.
    """
    if os.name != "nt":
        return
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as key:
            for name in _WINDOWS_USER_ENV_KEYS:
                if os.environ.get(name):
                    continue
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                except OSError:
                    continue
                if value:
                    os.environ[name] = str(value)
    except (ImportError, OSError):
        return


def load_env() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    _load_windows_user_env()
    candidates: list[Path] = []
    explicit = os.environ.get("BOOKCOMPILER_ENV_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path(__file__).resolve().parents[2] / ".env")
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            value = value.strip().strip('"').strip("'")
            if name and name not in os.environ:
                os.environ[name] = value


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]