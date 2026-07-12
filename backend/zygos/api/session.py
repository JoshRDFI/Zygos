"""In-memory sessions: registry, per-session state, and pull-snapshot (RFC-0007 §3).

A session owns one root ExecutionContext whose run_id is the memory trail id; each
turn is a child span with a fresh CancelToken. State escapes only as a frozen
SessionState snapshot. The registry is the single-user, in-memory source of truth.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from zygos.api.frames import Frame
from zygos.runtime.context import CancelToken, ExecutionContext


class SessionState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    created_at: float
    turn_count: int
    turn_status: str
    connected: bool


class Session:
    def __init__(self, id: str, root: ExecutionContext, *, created_at: float) -> None:
        self.id = id
        self.root = root
        self.created_at = created_at
        self.turn_count = 0
        self.turn_status = "idle"
        self.connected = False
        self.outbound: asyncio.Queue[Frame] = asyncio.Queue()
        self.active_cancel: CancelToken | None = None
        self.active_task: asyncio.Task | None = None
        # connection bookkeeping used by the WS handler (Task 8)
        self._writer: asyncio.Task | None = None
        self._conn: object | None = None

    def enqueue(self, frame: Frame) -> None:
        self.outbound.put_nowait(frame)

    def begin_turn(self) -> None:
        self.turn_status = "running"
        self.turn_count += 1

    def end_turn(self) -> None:
        self.turn_status = "idle"

    def snapshot(self) -> SessionState:
        return SessionState(
            id=self.id,
            created_at=self.created_at,
            turn_count=self.turn_count,
            turn_status=self.turn_status,
            connected=self.connected,
        )


class SessionRegistry:
    def __init__(
        self,
        *,
        new_context: Callable[[str], ExecutionContext],
        clock: Callable[[], float],
        new_id: Callable[[], str],
    ) -> None:
        self._sessions: dict[str, Session] = {}
        self._new_context = new_context
        self._clock = clock
        self._new_id = new_id

    def create(self) -> Session:
        sid = self._new_id()
        session = Session(sid, self._new_context(sid), created_at=self._clock())
        self._sessions[sid] = session
        return session

    def get(self, id: str) -> Session | None:
        return self._sessions.get(id)

    def get_by_run_id(self, run_id: str) -> Session | None:
        for session in self._sessions.values():
            if session.root.run_id == run_id:
                return session
        return None

    def list(self) -> list[SessionState]:
        return [s.snapshot() for s in self._sessions.values()]

    def sessions(self) -> list[Session]:
        return list(self._sessions.values())

    def delete(self, id: str) -> bool:
        session = self._sessions.pop(id, None)
        if session is None:
            return False
        if (
            session.active_task is not None
            and not session.active_task.done()
            and session.active_cancel is not None
        ):
            session.active_cancel.trip()
        return True

    def count(self) -> int:
        return len(self._sessions)
