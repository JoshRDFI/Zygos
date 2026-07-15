"""ExecutionContext and cancellation (RFC-0002 §3).

An immutable object threaded through the runtime carrying correlation identity,
a bus-bound emitter, and a cancellation signal — and NO service references.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, replace

from zygos.runtime.events import Event, EventBus, EventPayload


class CancelToken:
    """Cooperative cancellation over a single-loop asyncio.Event."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def trip(self) -> None:
        self._event.set()

    @property
    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self) -> None:
        await self._event.wait()


@dataclass(frozen=True)
class ExecutionContext:
    run_id: str
    session_id: str | None
    span_id: str
    parent_span_id: str | None
    _bus: EventBus
    _cancel: CancelToken

    async def emit(self, payload: EventPayload, *, source: str) -> None:
        await self._bus.emit(
            Event(
                run_id=self.run_id,
                session_id=self.session_id,
                span_id=self.span_id,
                parent_span_id=self.parent_span_id,
                source=source,
                payload=payload,
            )
        )

    def child(self, span_id: str, *, cancel: "CancelToken | None" = None) -> "ExecutionContext":
        if cancel is None:
            return replace(self, span_id=span_id, parent_span_id=self.span_id)
        return replace(self, span_id=span_id, parent_span_id=self.span_id, _cancel=cancel)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set

    async def wait_cancelled(self) -> None:
        """Block until this context's CancelToken is tripped (cooperative cancel).

        Lets an awaiter race a long wait against cancellation instead of polling.
        """
        await self._cancel.wait()


def root_context(bus: EventBus, *, session_id: str | None = None) -> ExecutionContext:
    return ExecutionContext(
        run_id=uuid.uuid4().hex,
        session_id=session_id,
        span_id=uuid.uuid4().hex,
        parent_span_id=None,
        _bus=bus,
        _cancel=CancelToken(),
    )
