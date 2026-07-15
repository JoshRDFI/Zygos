"""Single-session voice ownership gate (closes review finding I3).

Voice engines are shared single-connection local sidecars: only one session may
use voice at a time, so concurrent sessions can never interleave PCM/control
frames on the shared connection. A second session's voice-enable is refused. The
gate is bypassed for concurrency-safe (API-backed) engines — see
VoiceService.concurrent_sessions_ok; the caller decides whether to consult it.

Ownership is keyed by session id and held from first voice-enable until the
session disconnects or is deleted. Re-acquiring by the current owner is
idempotent (back-to-back utterances on one session).

Stability: Experimental.
"""
from __future__ import annotations


class VoiceGate:
    def __init__(self) -> None:
        self._owner: str | None = None

    @property
    def owner(self) -> str | None:
        return self._owner

    def try_acquire(self, session_id: str) -> bool:
        if self._owner is None or self._owner == session_id:
            self._owner = session_id
            return True
        return False

    def release(self, session_id: str) -> None:
        if self._owner == session_id:
            self._owner = None
