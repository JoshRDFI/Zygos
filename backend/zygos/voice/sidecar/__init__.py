"""Voice sidecar workers and supervision.

Workers (e.g. fake_stt) speak the IPC contract in zygos.voice.ipc.
SidecarHandle supervises a worker subprocess: spawn, health,
restart-with-backoff, and shutdown.
"""
from __future__ import annotations

from zygos.voice.sidecar.handle import SidecarHandle, SidecarState

__all__ = ["SidecarHandle", "SidecarState"]
