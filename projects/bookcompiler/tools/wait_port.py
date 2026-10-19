"""Wait until a local TCP port accepts connections (used by start-all.bat)."""
import socket
import sys
import time

port = int(sys.argv[1])
timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
deadline = time.time() + timeout
while time.time() < deadline:
    s = socket.socket()
    s.settimeout(0.4)
    try:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            sys.exit(0)
    finally:
        s.close()
    time.sleep(0.4)
sys.exit(1)