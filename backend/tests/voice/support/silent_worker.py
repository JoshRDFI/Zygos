"""Test fixture: connect back to the listener, then go silent forever.
Run as: python .../silent_worker.py <address>  (UDS path or host:port)."""
import socket
import sys
import time

addr = sys.argv[1]
if "/" in addr:
    s = socket.socket(socket.AF_UNIX)
    s.connect(addr)
else:
    host, port = addr.rsplit(":", 1)
    s = socket.socket()
    s.connect((host, int(port)))
time.sleep(30)   # never sends a health_ok
