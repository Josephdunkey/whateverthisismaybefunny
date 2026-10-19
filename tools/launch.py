"""Knowledge Hub one-click launcher."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
RUN_DIR = ROOT / ".runtime"
PID_FILE = RUN_DIR / "pids.json"
LOG_DIR.mkdir(parents=True, exist_ok=True)
RUN_DIR.mkdir(parents=True, exist_ok=True)

HERMES_HOME = Path(r"D:\hermes agent")
BOOKCOMPILER_HOME = Path(r"C:\Users\mybea\projects\bookcompiler")
HINDSIGHT_HOME = Path(r"D:\hindsight")
BOOKCOMPILER_PY = BOOKCOMPILER_HOME / ".venv" / "Scripts" / "python.exe"
HINDSIGHT_PY = HINDSIGHT_HOME / ".venv" / "Scripts" / "python.exe"
HERMES_CLI = HERMES_HOME / "bin" / "hermes.cmd"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def wait_port(port: int, seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        if port_open(port):
            return True
        time.sleep(0.5)
    return port_open(port)


def read_pids() -> dict:
    try:
        data = json.loads(PID_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def write_pid(name: str, pid: int) -> None:
    data = read_pids()
    data[name] = {"pid": int(pid), "started_at": datetime.now(timezone.utc).isoformat()}
    PID_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def start_logged(name: str, command: list[str], cwd: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    out = LOG_DIR / f"{name}.out.log"
    err = LOG_DIR / f"{name}.err.log"
    with out.open("ab") as stdout, err.open("ab") as stderr:
        proc = subprocess.Popen(
            command, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
            stdout=stdout, stderr=stderr,
            creationflags=CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
        )
    write_pid(name, proc.pid)
    print(f"  started {name}: pid={proc.pid}")
    return proc


def ollama_exe() -> str | None:
    candidates = [shutil.which("ollama"), str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe")]
    return next((x for x in candidates if x and Path(x).is_file()), None)


def start_ollama() -> bool:
    if port_open(11434):
        print("  ollama: already running"); return True
    exe = ollama_exe()
    if not exe:
        print("  ollama: executable not found"); return False
    start_logged("ollama", [exe, "serve"], Path(exe).resolve().parent)
    ok = wait_port(11434, 30); print("  ollama:", "ready" if ok else "not ready"); return ok


def start_postgres() -> bool:
    if port_open(5432):
        print("  postgres: already running"); return True
    if not HINDSIGHT_PY.is_file():
        print(f"  postgres: missing {HINDSIGHT_PY}"); return False
    done = subprocess.run(
        [str(HINDSIGHT_PY), "-c", "import pg0; pg0.start('hindsight')"],
        cwd=str(HINDSIGHT_HOME), capture_output=True, text=True, encoding="utf-8",
        errors="replace", creationflags=CREATE_NO_WINDOW, timeout=90,
    )
    if done.returncode != 0:
        print("  postgres:", (done.stderr or done.stdout or "pg0 start failed")[-1200:]); return False
    ok = wait_port(5432, 30); print("  postgres:", "ready" if ok else "not ready"); return ok


def start_hindsight() -> bool:
    if port_open(8888):
        print("  hindsight: already running"); return True
    if not start_postgres():
        print("  hindsight: skipped because postgres is not ready"); return False
    if not HINDSIGHT_PY.is_file():
        print(f"  hindsight: missing {HINDSIGHT_PY}"); return False
    start_logged("hindsight", [str(HINDSIGHT_PY), str(HINDSIGHT_HOME / "run_server.py")], HINDSIGHT_HOME)
    ok = wait_port(8888, 50); print("  hindsight:", "ready" if ok else "not ready (see logs/hindsight.err.log)"); return ok


def start_bookcompiler() -> bool:
    if port_open(8765):
        print("  bookcompiler: already running"); return True
    if not BOOKCOMPILER_PY.is_file():
        print(f"  bookcompiler: missing {BOOKCOMPILER_PY}"); return False
    start_logged("bookcompiler", [str(BOOKCOMPILER_PY), "-m", "bookcompiler", "--db", str(BOOKCOMPILER_HOME / ".bookcompiler" / "library.db"), "gui", "--host", "127.0.0.1", "--port", "8765"], BOOKCOMPILER_HOME)
    ok = wait_port(8765, 35); print("  bookcompiler:", "ready" if ok else "not ready (see logs/bookcompiler.err.log)"); return ok


def start_hermes() -> bool:
    if port_open(9119):
        print("  hermes-dashboard: already running"); return True
    if not HERMES_CLI.is_file():
        print(f"  hermes: missing {HERMES_CLI}"); return False
    start_logged("hermes-dashboard", ["cmd.exe", "/c", str(HERMES_CLI), "dashboard", "--skip-build", "--no-open"], HERMES_HOME)
    ok = wait_port(9119, 45); print("  hermes-dashboard:", "ready" if ok else "not ready (see logs/hermes-dashboard.err.log)"); return ok


SERVICES = {"ollama": start_ollama, "postgres": start_postgres, "hindsight": start_hindsight, "bookcompiler": start_bookcompiler, "hermes": start_hermes}


def main() -> int:
    names = sys.argv[1:] or list(SERVICES)
    if names == ["all"]:
        names = list(SERVICES)
    failed = []
    for name in names:
        fn = SERVICES.get(name)
        if not fn:
            print(f"unknown service: {name}"); failed.append(name); continue
        print(f"[{name}]")
        try:
            if not fn():
                failed.append(name)
        except Exception as exc:
            print(f"  {name}: {type(exc).__name__}: {exc}"); failed.append(name)
    if failed:
        print("not ready: " + ", ".join(failed)); return 1
    print("all requested services are ready"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
