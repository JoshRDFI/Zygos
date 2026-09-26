"""Test fixture: connect back to the listener, then die hard mid-startup.

Simulates a GPU worker that CUDA-aborts/segfaults/OOM-kills before running its
event loop: it never reads the queued `health` frame, so the runtime's
send_control/recv can observe either EOFError or OSError (BrokenPipeError /
ConnectionResetError), depending on OS timing, instead of a clean EOF.

Run as: python .../crash_worker.py <address>  (UDS path or host:port).
"""
import os
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
time.sleep(0.3)   # never runs an event loop, never reads the health frame
os._exit(1)       # hard kill: no clean shutdown, no FIN/close handshake
