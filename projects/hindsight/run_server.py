"""Launcher for Hindsight API with UTF-8 console output and .env loading."""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from pathlib import Path

root = Path(__file__).resolve().parent
env_path = root / ".env"
if env_path.is_file():
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

from hindsight_api.main import main

if __name__ == "__main__":
    main()
