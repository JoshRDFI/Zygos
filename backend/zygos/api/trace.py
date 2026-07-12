"""Per-session trace bridge (RFC-0007 §10).

One process-global bus subscriber (the InProcessEventBus is subscribe-only by
RFC-0002's design — subscribers are process-lifetime) that mirrors each emitted
event to the originating session as a trace:event frame, filtered by run_id. It
only enqueues (never does socket I/O inside emit) and is a pure observer:
dropping it changes no turn output (RFC-0002 observational invariant).

Stability: Experimental.
"""

from __future__ import annotations

from zygos.api.frames import TRACE, Frame
from zygos.api.session import SessionRegistry
from zygos.runtime.events import Event, EventBus


def install_trace_bridge(bus: EventBus, registry: SessionRegistry) -> None:
    async def _bridge(event: Event) -> None:
        session = registry.get_by_run_id(event.run_id)
        if session is None or not session.connected:
            return
        payload = {**event.payload.model_dump(), "span_id": event.span_id, "source": event.source}
        session.enqueue(Frame(channel=TRACE, type="event", payload=payload))

    bus.subscribe(_bridge)
