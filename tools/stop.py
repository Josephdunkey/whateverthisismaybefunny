"""Stop only services recorded by launch.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / ".runtime" / "pids.json"
DEFAULT = {"bookcompiler", "hindsight", "hermes-dashboard"}


def main() -> int:
    try:
        data = json.loads(PID_FILE.read_text(encoding="utf-8"))
    except Exception:
        print("no pid file; nothing to stop")
        return 0
    names = set(sys.argv[1:]) or DEFAULT
    if "all" in names:
        names = set(data)
    for name in sorted(names):
        row = data.get(name) or {}
        pid = row.get("pid")
        if not isinstance(pid, int):
            continue
        done = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        detail = "stopped" if done.returncode == 0 else (done.stderr or done.stdout).strip()
        print(f"{name} ({pid}): {detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
