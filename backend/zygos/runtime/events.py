"""Runtime event bus and typed event envelope (RFC-0002 §2).

Strictly observational: subscribers observe facts; dropping every subscriber
leaves runtime behavior identical. The payload is a closed discriminated union
of frozen per-event models, validated at construction.

Stability: Experimental.
"""

from __future__ import annotations

import logging
from typing import Annotated, Awaitable, Callable, Literal, Protocol, Union

from pydantic import BaseModel, ConfigDict, Field


class EventPayload(BaseModel):
    """Base for per-event-type payloads. Frozen; unknown fields forbidden."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RouteClaimed(EventPayload):
    type: Literal["route.claimed"] = "route.claimed"
    provider: str
    model: str
    probe: bool


class CircuitOpened(EventPayload):
    type: Literal["circuit.opened"] = "circuit.opened"
    provider: str
    model: str
    last_error_code: str


class CircuitClosed(EventPayload):
    type: Literal["circuit.closed"] = "circuit.closed"
    provider: str
    model: str


class RequestStarted(EventPayload):
    type: Literal["request.started"] = "request.started"
    prompt_chars: int


class RequestFinished(EventPayload):
    type: Literal["request.finished"] = "request.finished"
    ok: bool
    loops_used: int


class ModelSelected(EventPayload):
    type: Literal["model.selected"] = "model.selected"
    provider: str
    model: str
    classification: str


AnyPayload = Annotated[
    Union[RouteClaimed, CircuitOpened, CircuitClosed, RequestStarted, RequestFinished, ModelSelected],
    Field(discriminator="type"),
]


class Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    session_id: str | None = None
    span_id: str
    parent_span_id: str | None = None
    source: str
    payload: AnyPayload

    @property
    def type(self) -> str:
        return self.payload.type


logger = logging.getLogger("zygos.events")

Subscriber = Callable[[Event], Awaitable[None]]


class EventBus(Protocol):
    def subscribe(self, handler: Subscriber) -> None: ...

    async def emit(self, event: Event) -> None: ...


class InProcessEventBus:
    """Synchronous, in-loop, error-isolated delivery in registration order."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, handler: Subscriber) -> None:
        self._subscribers.append(handler)

    async def emit(self, event: Event) -> None:
        for handler in self._subscribers:
            try:
                await handler(event)
            except Exception:  # noqa: BLE001 - isolation is the contract
                logger.exception("event subscriber raised; isolated (type=%s)", event.type)
